"""Metered administrator previews share bounded global/account embedding leases."""
import asyncio
from time import monotonic
import anyio
from app.core.database import session_factory
from app.core.exceptions import APIError
from app.models.user import User
from app.services.model_catalog import candidates
from app.services.route_jobs import lease,embedding_value
from app.gateway.context import GatewayContext
from app.gateway.request_id import generate
from app.gateway import protocol_adapter,upstream,provider_health,call_log
from app.providers.operations import compatible


async def embedding(actor_id,model,text,client_ip):
    ctx=GatewayContext(generate(),'embeddings',model,{'model':model,'input':text,'encoding_format':'float'},client_ip=client_ip)
    ctx.stages=['admin_route_preview'];ctx.deferred['smart_routing']='preview_embedding'
    outcome,code='failure',None
    try:
        async with session_factory() as db:
            ctx.user=await db.get(User,actor_id)
            if not ctx.user or ctx.user.deleted_at or ctx.user.status!='enabled' or ctx.user.role not in ('admin','super_admin') or ctx.user.must_change_password:
                raise APIError(403,'ROUTE_PREVIEW_FORBIDDEN','管理员权限已失效')
            pairs=[(m,p) for m,p in await candidates(db,model) if compatible('embeddings',p)]
        if not pairs:raise APIError(503,'ROUTE_EMBEDDING_UNAVAILABLE','Embedding模型无可用账号')
        ctx.mapping,ctx.provider=pairs[0];protocol_adapter.bind(ctx)
        ctx.attempts.append({'provider_id':ctx.provider.id,'provider_name':ctx.provider.name,'logical_model':model,
            'upstream_model':ctx.mapping.upstream_model,'protocol':ctx.provider.protocol,'config_version':ctx.provider.config_version,
            'status':'not_sent','code':None,'http_status':None,'elapsed_ms':None})
        async with asyncio.timeout(120):
            async with lease(ctx):
                async with session_factory() as db:
                    actor=await db.get(User,actor_id);fresh=await candidates(db,model)
                    if not actor or actor.deleted_at or actor.status!='enabled' or actor.role not in ('admin','super_admin') or actor.must_change_password:
                        raise APIError(403,'ROUTE_PREVIEW_FORBIDDEN','管理员权限已失效')
                    if not any(m.id==ctx.mapping.id and p.config_version==ctx.provider.config_version for m,p in fresh):
                        raise APIError(409,'ROUTE_PROVIDER_CHANGED','Embedding账号配置已变化，请重试')
                ctx.upstream_started=ctx.attempt_started=monotonic();ctx.attempts[-1]['status']='started'
                ctx.stages.extend(['provider_concurrency','protocol_adapter','upstream'])
                result=await upstream.execute(ctx)
                ctx.upstream_elapsed_ms=(monotonic()-ctx.upstream_started)*1000;ctx.upstream_started=None
                vector=embedding_value(result)
                ctx.attempts[-1].update(status='success',http_status=200,elapsed_ms=ctx.upstream_elapsed_ms)
                await provider_health.finish(ctx,'success')
                outcome='success';return vector,ctx.request_id
    except BaseException as error:
        code=ctx.lease_error or (error.detail['code'] if isinstance(error,APIError) else 'UPSTREAM_TIMEOUT' if isinstance(error,TimeoutError) else 'ROUTE_PREVIEW_INTERRUPTED')
        ctx.response_status=error.status_code if isinstance(error,APIError) else 503
        if ctx.upstream_started is not None:
            ctx.upstream_elapsed_ms=(monotonic()-ctx.upstream_started)*1000;ctx.upstream_started=None
        if ctx.attempts:ctx.attempts[-1].update(status='failure',code=code,elapsed_ms=ctx.upstream_elapsed_ms)
        await provider_health.finish(ctx,'failure',code)
        if isinstance(error,APIError):raise
        if isinstance(error,asyncio.CancelledError) and not ctx.lease_error:raise
        raise APIError(503,code,'预览向量请求未完成，请重试') from None
    finally:
        ctx.stages.extend(['usage','call_log'])
        with anyio.CancelScope(shield=True):await call_log.write(ctx,outcome,code)
