"""Recoverable admin sample jobs; bounded global/account leases, actual usage logs."""
import asyncio
from contextlib import asynccontextmanager,suppress
from datetime import timedelta
from time import monotonic
import anyio
from sqlalchemy import select,update
from app.core.database import session_factory
from app.core.config import get_settings
from app.core.redis import redis_client
from app.core.security import now
from app.core.exceptions import APIError
from app.models.routing import RouteConfig,RouteSample
from app.models.user import User
from app.services.model_catalog import candidates
from app.services.route_vectors import encode_vector,store_vector
from app.gateway.context import GatewayContext
from app.gateway.request_id import generate
from app.gateway import protocol_adapter,upstream,call_log,provider_health
from app.gateway.provider_concurrency import key,RENEW,TTL,RENEW_SECONDS
from app.providers.operations import compatible

ACQUIRE_JOB='''
local t=redis.call('TIME');local n=tonumber(t[1])+tonumber(t[2])/1000000
for i=1,2 do redis.call('ZREMRANGEBYSCORE',KEYS[i],'-inf',n) end
for _,expired in ipairs(redis.call('ZRANGEBYSCORE',KEYS[4],'-inf',n)) do redis.call('ZREM',KEYS[3],expired) end
redis.call('ZREMRANGEBYSCORE',KEYS[4],'-inf',n)
if redis.call('ZCARD',KEYS[3])>0 or redis.call('ZCARD',KEYS[1])>=tonumber(ARGV[2]) or redis.call('ZCARD',KEYS[2])>=tonumber(ARGV[3]) then return 0 end
for i=1,2 do redis.call('ZADD',KEYS[i],n+tonumber(ARGV[4]),ARGV[1]);redis.call('EXPIRE',KEYS[i],tonumber(ARGV[4])+30) end
return 1
'''


def embedding_value(result):
    data=result.get('data')
    if not isinstance(data,list) or len(data)!=1 or type(data[0].get('index')) is not int or data[0]['index']!=0:
        raise APIError(502,'ROUTE_INVALID_VECTOR','Embedding必须返回索引0的单条向量')
    vector=data[0].get('embedding');encode_vector(vector);return vector


@asynccontextmanager
async def lease(ctx):
    slots=['gateway:concurrency',key(ctx.provider.id)]
    limit=1 if ctx.provider.cooldown_until and ctx.provider.cooldown_until<=now() else ctx.provider.max_concurrency
    deadline=monotonic()+get_settings().gateway.queue_timeout
    while not await redis_client.eval(ACQUIRE_JOB,4,*slots,'gateway:queue','gateway:queue:leases',ctx.request_id,get_settings().gateway.max_concurrency,limit,TTL):
        if monotonic()>=deadline:raise APIError(429,'ROUTE_JOB_BUSY','向量任务等待并发名额超时')
        await asyncio.sleep(.25)
    owner=asyncio.current_task()
    async def renew():
        while True:
            await asyncio.sleep(RENEW_SECONDS)
            try:
                for slot in slots:
                    if not await redis_client.eval(RENEW,1,slot,ctx.request_id,TTL):raise RuntimeError()
            except Exception:
                ctx.lease_error='CONCURRENCY_UNAVAILABLE';owner.cancel();return
    task=asyncio.create_task(renew())
    try:yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):await task
        with anyio.CancelScope(shield=True):
            for slot in slots:
                with suppress(Exception):await redis_client.zrem(slot,ctx.request_id)


async def claim():
    async with session_factory.begin() as db:
        # Recovery always advances revision so a late completion cannot overwrite a retry.
        await db.execute(update(RouteSample).where(RouteSample.vector_status=='processing',RouteSample.job_started_at<now()-timedelta(seconds=180))
                         .values(vector_status='pending',revision=RouteSample.revision+1,job_started_at=None,vector_request_id=None))
        ident=await db.scalar(select(RouteSample.config_id).where(RouteSample.vector_status=='pending',RouteSample.vector_requested.is_(True)).order_by(RouteSample.id).limit(1))
        if ident is None:return None
        config=await db.scalar(select(RouteConfig).where(RouteConfig.id==ident).with_for_update())
        if not config:return None
        row=await db.scalar(select(RouteSample).where(RouteSample.config_id==ident,RouteSample.vector_status=='pending',RouteSample.vector_requested.is_(True)).order_by(RouteSample.id).limit(1).with_for_update(skip_locked=True))
        if not row:return None
        row.vector_status='processing';row.job_started_at=now();row.vector_request_id=generate()
        return dict(config_id=ident,sample_id=row.id,generation=config.vector_generation,revision=row.revision,
                    model=config.embedding_model,prompt=row.prompt,actor=row.requested_by,request_id=row.vector_request_id)


async def process(job):
    ctx=GatewayContext(job['request_id'],'embeddings',job['model'],{'model':job['model'],'input':job['prompt'],'encoding_format':'float'})
    ctx.stages=['admin_sample_vectorization'];ctx.deferred['smart_routing']='sample_vectorization'
    outcome,code='failure','ROUTE_EMBEDDING_UNAVAILABLE'
    try:
        async with session_factory() as db:
            ctx.user=await db.get(User,job['actor']) if job['actor'] else None
            if not ctx.user or ctx.user.deleted_at or ctx.user.status!='enabled' or ctx.user.role not in ('admin','super_admin') or ctx.user.must_change_password:
                raise APIError(403,'ROUTE_JOB_FORBIDDEN','提交样本的管理员权限已失效')
            pairs=[(m,p) for m,p in await candidates(db,job['model']) if compatible('embeddings',p)]
        if not pairs:raise APIError(503,code,'Embedding模型无可用账号')
        # Each durable job tries one account; explicit retry rebuilds a new version.
        ctx.mapping,ctx.provider=pairs[0];protocol_adapter.bind(ctx)
        entry={'provider_id':ctx.provider.id,'provider_name':ctx.provider.name,'logical_model':ctx.mapping.logical_model,
               'upstream_model':ctx.mapping.upstream_model,'protocol':ctx.adapter.protocol_name,'config_version':ctx.provider.config_version,
               'status':'not_sent','code':None,'http_status':None,'elapsed_ms':None}
        ctx.attempts.append(entry)
        async with asyncio.timeout(120):
            async with lease(ctx):
                async with session_factory() as db:
                    valid=await db.scalar(select(RouteSample.id).join(RouteConfig,RouteConfig.id==RouteSample.config_id).where(
                        RouteSample.id==job['sample_id'],RouteSample.revision==job['revision'],RouteSample.vector_status=='processing',
                        RouteSample.vector_request_id==job['request_id'],RouteConfig.vector_generation==job['generation'],RouteConfig.embedding_model==job['model']))
                    actor=await db.get(User,job['actor'])
                    fresh=await candidates(db,job['model'])
                    if not valid or not actor or actor.deleted_at or actor.status!='enabled' or actor.role not in ('admin','super_admin') or actor.must_change_password:
                        raise APIError(409,'ROUTE_JOB_STALE','样本版本或管理员权限已变化')
                    if not any(m.id==ctx.mapping.id and p.config_version==ctx.provider.config_version for m,p in fresh):
                        raise APIError(409,'ROUTE_PROVIDER_CHANGED','Embedding账号配置已变化，请重试')
                ctx.upstream_started=ctx.attempt_started=monotonic()
                entry['status']='started';ctx.stages.extend(['provider_concurrency','protocol_adapter','upstream'])
                result=await upstream.execute(ctx)
                ctx.upstream_elapsed_ms=(monotonic()-ctx.upstream_started)*1000;ctx.upstream_started=None
                entry['status']='success';entry['http_status']=200;entry['elapsed_ms']=ctx.upstream_elapsed_ms
                vector=embedding_value(result)
                await provider_health.finish(ctx,'success')
                async with session_factory.begin() as db:
                    stored=await store_vector(db,job['config_id'],job['sample_id'],job['generation'],job['revision'],job['model'],vector)
                    if not stored:raise APIError(409,'ROUTE_JOB_STALE','向量结果已过期，未覆盖当前样本')
        outcome,code='success',None
    except BaseException as error:
        code=ctx.lease_error or (error.detail['code'] if isinstance(error,APIError) else 'UPSTREAM_TIMEOUT' if isinstance(error,TimeoutError) else 'ROUTE_JOB_INTERRUPTED' if isinstance(error,asyncio.CancelledError) else 'ROUTE_VECTORIZATION_FAILED')
        ctx.response_status=error.status_code if isinstance(error,APIError) else 503
        if ctx.upstream_started is not None:
            ctx.upstream_elapsed_ms=(monotonic()-ctx.upstream_started)*1000;ctx.upstream_started=None
        if ctx.attempts:
            ctx.attempts[-1].update(status='failure',code=code,http_status=getattr(ctx.adapter,'http_status',None),elapsed_ms=ctx.upstream_elapsed_ms)
        await provider_health.finish(ctx,'failure',code)
        with anyio.CancelScope(shield=True):
            async with session_factory.begin() as db:
                await db.execute(update(RouteSample).where(RouteSample.id==job['sample_id'],RouteSample.revision==job['revision'],RouteSample.vector_request_id==job['request_id'],RouteSample.vector_status=='processing').values(vector_status='failed',vector_error=code))
        if isinstance(error,asyncio.CancelledError) and not ctx.lease_error:raise
    finally:
        ctx.stages.extend(['usage','call_log'])
        with anyio.CancelScope(shield=True):await call_log.write(ctx,outcome,code)


async def loop():
    while True:
        try:
            job=await claim()
            if job:await process(job)
        except asyncio.CancelledError:raise
        except Exception:pass  # Retry DB/Redis availability; never log Prompt or credential-bearing exceptions.
        await asyncio.sleep(1)
