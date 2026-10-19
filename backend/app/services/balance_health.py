"""Bounded non-generating node probes and persistent circuit recovery."""
import asyncio,logging
from uuid import uuid4
from app.core.redis import redis_client
from redis.exceptions import RedisError
from datetime import timedelta
from time import monotonic
from sqlalchemy import select,update,or_
from app.core.database import session_factory
from app.core.security import now
from app.models.balance import BalancedRoute,BalancedNode
from app.models.user import Provider,ProviderModelMapping,LogicalModel
from app.schemas.balance import matching_type
from app.services.balance_capabilities import operation_for
from app.providers.registry import build_adapter
from app.providers.base import ProviderFailure
from app.services.provider_crypto import decrypt_secret

logger=logging.getLogger(__name__)

async def reset_nodes(db,provider_id,mapping_ids=None):
    ids=select(ProviderModelMapping.id).where(ProviderModelMapping.provider_id==provider_id)
    if mapping_ids is not None:ids=ids.where(ProviderModelMapping.id.in_(mapping_ids))
    await db.execute(update(BalancedNode).where(BalancedNode.mapping_id.in_(ids)).values(
        health_status='unknown',failure_count=0,cooldown_until=None,last_checked_at=None,
        last_latency_ms=None,last_error_code=None,next_check_at=now()))

async def finish(ctx,outcome,code=None):
    node=getattr(ctx,'balance_node',None);route=getattr(ctx,'balance_route',None)
    if not node or not route or outcome=='client_cancelled':return
    if outcome!='success' and (not code or not code.startswith('UPSTREAM_') or code in ('UPSTREAM_REQUEST_REJECTED','UPSTREAM_POOL_EXHAUSTED')):return
    try:
        async with session_factory.begin() as db:
            current=await db.scalar(select(BalancedRoute).where(BalancedRoute.id==route.id,BalancedRoute.config_version==route.config_version).with_for_update())
            if current is None:return
            live=await db.scalar(select(Provider.id).where(Provider.id==ctx.provider.id,
                Provider.config_version==ctx.provider.config_version,Provider.status=='enabled',Provider.deleted_at.is_(None)).with_for_update())
            if live is None:return
            row=await db.scalar(select(BalancedNode).where(BalancedNode.id==node.id).with_for_update())
            if not current or not row:return
            row.last_latency_ms=round((monotonic()-ctx.attempt_started)*1000);row.last_error_code=code
            if outcome=='success':row.health_status='healthy';row.failure_count=0;row.cooldown_until=None
            else:
                row.failure_count+=1
                if row.failure_count>=route.failure_threshold or code in ('UPSTREAM_AUTH_FAILED','UPSTREAM_RATE_LIMITED'):
                    row.health_status='unhealthy';row.cooldown_until=now()+timedelta(seconds=route.cooldown_seconds)
    except Exception as error:logger.warning('Balanced health persistence pending [%s]',type(error).__name__)

async def probe(route_id,node_id):
    token=uuid4().hex;key=f'balance:probe:{node_id}'
    try:
        if not await redis_client.set(key,token,ex=20,nx=True):return {'success':False,'code':'CHECK_BUSY'}
    except RedisError:return {'success':False,'code':'SCHEDULER_UNAVAILABLE'}
    try:return await _probe(route_id,node_id)
    finally:
        import anyio
        with anyio.CancelScope(shield=True):
            try:await redis_client.eval("if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",1,key,token)
            except RedisError:pass

async def _probe(route_id,node_id):
    async with session_factory() as db:
        result=(await db.execute(select(BalancedRoute,BalancedNode,ProviderModelMapping,Provider).join(BalancedNode,BalancedNode.route_id==BalancedRoute.id)
            .join(ProviderModelMapping,ProviderModelMapping.id==BalancedNode.mapping_id).join(Provider,Provider.id==ProviderModelMapping.provider_id)
            .where(BalancedRoute.id==route_id,BalancedNode.id==node_id))).first()
        if not result:return {'success':False,'code':'NODE_NOT_FOUND'}
        route,node,mapping,provider=result
        if route.status!='enabled' or node.status!='enabled' or mapping.status!='enabled' or mapping.deleted_at or provider.status!='enabled' or provider.deleted_at:
            return {'success':False,'code':'NODE_DISABLED'}
        alias=await db.get(LogicalModel,route.model_name)
        operation=operation_for(alias.model_type,provider) if alias else None
        if not alias or not matching_type(alias.model_type,mapping.model_type) or not operation:
            return {'success':False,'code':'BALANCE_NODE_INCOMPATIBLE'}
    started=monotonic();code=None;success=False;unsupported=False;model_available=None
    try:
        async with asyncio.timeout(12):
            adapter=build_adapter(provider,decrypt_secret(provider.api_key_encrypted),operation);models=await adapter.list_models()
        model_available=mapping.upstream_model in {item['id'] for item in models}
        success=model_available
        if not success:code='TEST_MODEL_NOT_FOUND'
    except ProviderFailure as error:
        code=error.code;unsupported=error.status in (404,405,501) or getattr(locals().get('adapter'),'http_status',None) in (404,405,501)
    except TimeoutError:code='UPSTREAM_TIMEOUT'
    except Exception:code='PROVIDER_CHECK_FAILED'
    latency=round((monotonic()-started)*1000)
    async with session_factory.begin() as db:
        current=await db.scalar(select(BalancedRoute).where(BalancedRoute.id==route_id,BalancedRoute.config_version==route.config_version).with_for_update())
        live=await db.scalar(select(Provider.id).where(Provider.id==provider.id,Provider.config_version==provider.config_version,Provider.deleted_at.is_(None),Provider.status=='enabled').with_for_update())
        row=await db.scalar(select(BalancedNode).where(BalancedNode.id==node_id).with_for_update())
        if not current or not live or not row:return {'success':False,'code':'CONFIG_CHANGED'}
        row.last_checked_at=now();row.next_check_at=now()+timedelta(seconds=route.health_interval)
        row.last_latency_ms=latency;row.last_error_code=code
        if success:
            row.health_status='healthy';row.failure_count=0;row.cooldown_until=None
            await db.execute(update(Provider).where(Provider.id==provider.id,Provider.config_version==provider.config_version).values(health_status='healthy',failure_count=0,cooldown_until=None))
        elif not unsupported:
            row.failure_count+=1
            if row.failure_count>=route.failure_threshold or code in ('UPSTREAM_AUTH_FAILED','UPSTREAM_RATE_LIMITED'):
                row.health_status='unhealthy';row.cooldown_until=now()+timedelta(seconds=route.cooldown_seconds)
    return {'success':success,'code':code,'latency_ms':latency,'unsupported':unsupported,'model_available':model_available,'generation_tested':False}

async def loop():
    semaphore=asyncio.Semaphore(4)
    while True:
        try:
            async with session_factory.begin() as db:
                rows=(await db.execute(select(BalancedNode,BalancedRoute.health_interval).join(BalancedRoute).where(
                    BalancedNode.status=='enabled',BalancedRoute.status=='enabled',
                    or_(BalancedNode.next_check_at.is_(None),BalancedNode.next_check_at<=now()))
                    .order_by(BalancedNode.next_check_at.asc().nullsfirst(),BalancedNode.id).limit(20).with_for_update(of=BalancedNode,skip_locked=True))).all()
                jobs=[(node.route_id,node.id) for node,interval in rows]
                for node,interval in rows:node.next_check_at=now()+timedelta(seconds=interval)
            async def check(route_id,node_id):
                async with semaphore:await probe(route_id,node_id)
            await asyncio.gather(*(check(*job) for job in jobs))
        except Exception as error:logger.warning('Balanced health check pending [%s]',type(error).__name__)
        await asyncio.sleep(1)
