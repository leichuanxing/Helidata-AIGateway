"""Explicit, metered admin tests pinned to one saved account; never auto-failover."""
import asyncio
from time import monotonic
import anyio
from sqlalchemy import select,update
from app.core.database import session_factory
from app.core.exceptions import APIError
from app.core.security import now
from app.models.user import User,Provider,ProviderModelMapping
from app.gateway.context import GatewayContext
from app.gateway.request_id import generate
from app.gateway import protocol_adapter,upstream,provider_health,call_log
from app.services.route_jobs import lease
from app.providers.operations import compatible
from app.providers.base import ProviderFailure
from app.gateway.upstream_errors import translate

def operation_for(mapping,provider):
    choices={'embedding':['embeddings'],'rerank':['rerank'],'image':['images']}.get(mapping.model_type,['chat','responses','messages'])
    return next((op for op in choices if compatible(op,provider)),None)

def payload_for(operation,model):
    payload={'model':model}
    if operation=='chat':payload.update(messages=[{'role':'user','content':'Reply OK.'}],max_tokens=8,stream=False)
    elif operation=='messages':payload.update(messages=[{'role':'user','content':'Reply OK.'}],max_tokens=8,stream=False)
    elif operation=='responses':payload.update(input='Reply OK.',max_output_tokens=8,stream=False)
    elif operation=='embeddings':payload.update(input='test',encoding_format='float')
    elif operation=='rerank':payload.update(query='test',documents=['test'],top_n=1)
    elif operation=='images':payload.update(prompt='A small blue circle on a white background.',n=1)
    return payload

def valid_actor(actor):
    return actor and not actor.deleted_at and actor.status=='enabled' and actor.role in ('admin','super_admin') and not actor.must_change_password

async def run_one(actor_id,account,mapping,request):
    operation=operation_for(mapping,account)
    ctx=GatewayContext(generate(),operation or 'preflight',mapping.logical_model,
        payload_for(operation,mapping.logical_model),client_ip=request.client.host)
    ctx.provider,ctx.mapping=account,mapping
    ctx.stages=['admin_provider_test'];ctx.deferred['smart_routing']='not_applicable';ctx.deferred['compliance']='not_applicable'
    outcome,code='failure',None
    try:
        async with session_factory() as db:
            ctx.user=await db.get(User,actor_id)
            if not valid_actor(ctx.user):raise APIError(403,'ADMIN_TEST_FORBIDDEN','管理员权限已失效')
        if not operation:raise APIError(422,'UNSUPPORTED_OPERATION','账号没有支持该模型类型的协议')
        protocol_adapter.bind(ctx)
        ctx.attempts.append({'provider_id':account.id,'provider_name':account.name,'logical_model':mapping.logical_model,
            'upstream_model':mapping.upstream_model,'protocol':ctx.adapter.protocol_name,'config_version':account.config_version,
            'status':'not_sent','code':None,'http_status':None,'elapsed_ms':None})
        async with asyncio.timeout(150):
            async with lease(ctx):
                async with session_factory() as db:
                    actor=await db.get(User,actor_id);fresh=await db.get(Provider,account.id);m=await db.get(ProviderModelMapping,mapping.id)
                    if not valid_actor(actor):raise APIError(403,'ADMIN_TEST_FORBIDDEN','管理员权限已失效')
                    if not fresh or fresh.config_version!=account.config_version or fresh.deleted_at or fresh.status!='enabled' or not m or m.deleted_at or m.status!='enabled':
                        raise APIError(409,'PROVIDER_CHANGED','测试期间账号或映射已变化，请重新加载')
                ctx.upstream_started=ctx.attempt_started=monotonic();ctx.attempts[-1]['status']='started'
                ctx.stages.extend(['provider_concurrency','protocol_adapter','upstream'])
                await upstream.nonstream(request,ctx)
                ctx.upstream_elapsed_ms=(monotonic()-ctx.upstream_started)*1000;ctx.upstream_started=None
                ctx.attempts[-1].update(status='success',http_status=ctx.adapter.http_status,elapsed_ms=ctx.upstream_elapsed_ms)
                await provider_health.finish(ctx,'success');outcome='success'
    except BaseException as error:
        if isinstance(error,ProviderFailure):error=translate(error)
        code=ctx.lease_error or (error.detail['code'] if isinstance(error,APIError) else 'UPSTREAM_TIMEOUT' if isinstance(error,TimeoutError) else 'ADMIN_TEST_INTERRUPTED')
        ctx.response_status=error.status_code if isinstance(error,APIError) else 503
        if ctx.upstream_started is not None:ctx.upstream_elapsed_ms=(monotonic()-ctx.upstream_started)*1000;ctx.upstream_started=None
        if ctx.attempts:ctx.attempts[-1].update(status='failure',code=code,http_status=getattr(ctx.adapter,'http_status',None),elapsed_ms=ctx.upstream_elapsed_ms)
        await provider_health.finish(ctx,'failure',code)
        if isinstance(error,asyncio.CancelledError) and not ctx.lease_error:raise
        if code=='CLIENT_DISCONNECTED':raise error
    finally:
        ctx.stages.extend(['usage','call_log'])
        with anyio.CancelScope(shield=True):await call_log.write(ctx,outcome,code)
    async with session_factory.begin() as db:
        await db.execute(update(Provider).where(Provider.id==account.id,Provider.config_version==account.config_version,
            Provider.deleted_at.is_(None)).values(last_test_at=now()))
    return {'request_id':ctx.request_id,'logical_model':mapping.logical_model,'upstream_model':mapping.upstream_model,
        'operation':operation,'success':outcome=='success','error_code':code,
        'http_status':getattr(ctx.adapter,'http_status',None),'latency_ms':round((monotonic()-ctx.started)*1000),
        'total_tokens':ctx.usage_snapshot.get('total_tokens'),'message':'模型调用成功' if outcome=='success' else '模型调用失败，请查看调用日志'}
