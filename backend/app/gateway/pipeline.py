"""Orchestrate independent stages; streaming responses take ownership of leases."""
import asyncio
from contextlib import AsyncExitStack
import anyio
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeout
from redis.exceptions import RedisError
from app.core.exceptions import APIError
from app.gateway import (authentication, user_validation, group_validation, model_permission,
    quota, concurrency, compliance, smart_routing, model_selection, provider_scheduler,
    provider_concurrency, protocol_adapter, upstream, call_log, model_directory)
from app.gateway.context import GatewayContext
from app.services.key_auth import record_key_use
from app.providers.operations import INFERENCE
from app.gateway import preparation
from app.services import body_logs


class GatewayPipeline:
    async def run(self, request, db, operation, logical_model=None, payload=None):
        ctx = GatewayContext(request.state.request_id, operation, logical_model, payload)
        body_logs.begin(ctx)
        ctx.started=getattr(request.state,"started",ctx.started)
        ctx.received_at=getattr(request.state,"received_at",ctx.received_at)
        ctx.client_ip = request.client.host if request.client else ''
        ctx.request=request
        request.state.gateway_context=ctx
        resources = AsyncExitStack()
        preparation_lease = AsyncExitStack()
        recorded = False
        outcome,code,stream_owned='success',None,False
        try:
            await preparation_lease.enter_async_context(preparation.acquire())
            ctx.stages.append('authentication')
            ctx.key, ctx.user, ctx.group = await authentication.authenticate(request, db)
            ctx.stages.append('user_validation'); user_validation.validate(ctx.user)
            ctx.stages.append('group_validation'); group_validation.validate(ctx.group)
            if operation == 'models':
                ctx.stages.append('model_permission')
                result = await model_directory.listing(db, ctx)
            elif operation in ('preflight',)+INFERENCE:
                ctx.stages.append('model_permission'); await model_permission.check(db, ctx)
                ctx.stages.append('compliance'); await compliance.check(db,ctx)
                ctx.stages.append('smart_routing'); await smart_routing.route(db,ctx)
                if ctx.route_config_id and ctx.original_model!=ctx.logical_model:
                    ctx.stages.append('routed_compliance'); await compliance.check(db,ctx,routed=True)
                ctx.stages.append('model_selection'); await model_selection.select_model(db, ctx)
                ctx.stages.append('provider_scheduler')
                await record_key_use(db, ctx)  # Commit and release DB connection before network I/O.
                recorded = True
                ctx.stages.append('quota'); await quota.check(ctx)
                await preparation_lease.aclose()
                ctx.stages.append('concurrency')
                await resources.enter_async_context(concurrency.acquire(ctx))
                result = await provider_scheduler.execute(request, ctx, resources)
                if operation in INFERENCE and payload.get('stream'):
                    stream_owned=True
                    return result
            else:
                raise APIError(501, 'OPERATION_NOT_IMPLEMENTED', '该操作尚未开放')
            if not recorded:
                await record_key_use(db, ctx)
            body_logs.response(ctx,result)
            ctx.stages.extend(['usage', 'call_log'])
            return result
        except BaseException as error:
            if ctx.provider_lease_lost or ctx.lease_error:
                code=ctx.lease_error or 'SCHEDULER_UNAVAILABLE'
                outcome='failure';ctx.response_status=503
                if ctx.attempts:
                    ctx.attempts[-1]['status']='failure';ctx.attempts[-1]['code']=code
                raise APIError(503,code,'资源占用状态已失效') from None
            unavailable=isinstance(error,(DBAPIError,PoolTimeout,RedisError))
            code = error.detail['code'] if isinstance(error, APIError) else 'DEPENDENCY_UNAVAILABLE' if unavailable else 'INTERNAL_ERROR'
            cancelled = isinstance(error, asyncio.CancelledError) or code == 'CLIENT_DISCONNECTED'
            outcome='client_cancelled' if cancelled else 'failure'
            if cancelled:code='CLIENT_DISCONNECTED'
            ctx.response_status=499 if cancelled else error.status_code if isinstance(error,APIError) else 503 if unavailable else 500
            raise
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    await resources.aclose()
                    await preparation_lease.aclose()
                except Exception:
                    outcome,code,ctx.response_status='failure','RESOURCE_CLOSE_FAILED',500
                    raise
                finally:
                    # Detach loaded snapshots before rollback expires ORM attributes.
                    if db.in_transaction():
                        db.expunge_all();await db.rollback()
                    await compliance.finalize(ctx)
                    if not stream_owned:
                        if ctx.stages[-2:]!=['usage','call_log']:ctx.stages.extend(['usage','call_log'])
                        await call_log.write(ctx,outcome,code)
