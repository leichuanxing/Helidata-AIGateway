from time import monotonic
from datetime import datetime, timezone
import logging
import asyncio
import re
from contextlib import suppress
from app.services import dashboard_live
from app.gateway import call_log
from app.gateway.context import GatewayContext
from app.gateway.request_id import generate, request_id, configure_logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from app.api.health import router as health_router
from app.api.auth.routes import router as auth_router
from app.api.admin.users import router as users_router
from app.api.portal.profile import router as profile_router
from app.api.admin.groups import router as groups_router
from app.api.portal.keys import router as keys_router
from app.api.key_identity import router as identity_router
from app.api.admin.providers import router as providers_router
from app.api.admin.model_mappings import router as mappings_router
from app.api.admin.model_groups import router as model_groups_router
from app.api.model_catalog import router as catalog_router
from app.api.gateway_core import router as gateway_router
from app.api.resources import router as resources_router
from app.api.admin.call_logs import router as call_logs_router
from starlette.exceptions import HTTPException
from app.core.config import get_settings
from app.core.database import engine
from app.core.exceptions import APIError
from app.core.redis import redis_client

logging.basicConfig(level=get_settings().logging.level)
configure_logging()
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app):
    from app.services import route_jobs,compliance_jobs,compliance_logs,backups
    from app.services import operations_settings,operations_jobs
    await operations_settings.load()
    from app.services import external_logs
    external_worker=asyncio.create_task(external_logs.loop())
    operations_worker=asyncio.create_task(operations_jobs.loop())
    backup_worker=asyncio.create_task(backups.loop())
    vectorizer=asyncio.create_task(route_jobs.loop())
    compliance_vectorizer=asyncio.create_task(compliance_jobs.loop())
    compliance_replay=asyncio.create_task(compliance_logs.replay())
    replay=asyncio.create_task(call_log.replay_loop())
    sampler=asyncio.create_task(dashboard_live.sample_loop())
    yield
    external_worker.cancel()
    with suppress(asyncio.CancelledError):await external_worker
    operations_worker.cancel()
    with suppress(asyncio.CancelledError):await operations_worker
    backup_worker.cancel()
    with suppress(asyncio.CancelledError):await backup_worker
    compliance_vectorizer.cancel();compliance_replay.cancel()
    with suppress(asyncio.CancelledError):await compliance_vectorizer
    with suppress(asyncio.CancelledError):await compliance_replay
    vectorizer.cancel()
    with suppress(asyncio.CancelledError):await vectorizer
    sampler.cancel()
    with suppress(asyncio.CancelledError):await sampler
    replay.cancel()
    with suppress(asyncio.CancelledError):await replay
    from app.providers.pool import pools
    await pools.close()
    await redis_client.aclose()
    await engine.dispose()


app=FastAPI(title='合力数据AI网关',version='1.0.3',lifespan=lifespan)
from app.core.body_limit import BodyLimitMiddleware
app.add_middleware(BodyLimitMiddleware)


@app.middleware('http')
async def request_context(request: Request,call_next):
    request.state.started=monotonic()
    request.state.received_at=datetime.now(timezone.utc)
    request.state.request_id=generate()
    token=request_id.set(request.state.request_id)
    try:
        try:
            response=await call_next(request)
        except Exception as error:
            # Consume unexpected application errors here so Uvicorn never logs raw exceptions.
            response=await unexpected(request,error)
        response.headers['X-Request-ID']=request.state.request_id
        fallback_operation={('/v1/chat/completions','POST'):'chat',('/api/admin/chat-test/completions','POST'):'chat',('/v1/responses','POST'):'responses',('/v1/messages','POST'):'messages',('/v1/embeddings','POST'):'embeddings',('/v1/rerank','POST'):'rerank',('/v1/images/generations','POST'):'images',('/api/gateway/preflight','POST'):'preflight',('/v1/models','GET'):'models'}.get((request.url.path,request.method))
        if fallback_operation and not hasattr(request.state,'gateway_context'):
            # Schema/body failures occur before Pipeline creation. Persist only safe metadata.
            ctx=GatewayContext(request.state.request_id,fallback_operation,getattr(request.state,'safe_model',None))
            ctx.started=request.state.started;ctx.received_at=request.state.received_at
            ctx.client_ip=request.client.host if request.client else ''
            ctx.payload={'stream':getattr(request.state,'safe_stream',False)}
            ctx.response_status=response.status_code;ctx.stages=['request_validation','call_log']
            await call_log.write(ctx,'failure',getattr(request.state,'failure_code','INTERNAL_ERROR'))
        public_brand_asset=(request.method in ('GET','HEAD') and response.status_code in (200,304)
            and request.url.path in ('/api/public/settings/assets/logo','/api/public/settings/assets/icon'))
        if request.url.path.startswith(('/api/','/v1/')) and not public_brand_asset:
            response.headers['Cache-Control']='no-store'
        logging.getLogger('app.requests').info('method=%s status=%s',request.method,response.status_code)
        return response
    finally:
        request_id.reset(token)



def error_body(request,code,message,status):
    error={'code':code,'message':message,'type':'gateway_error','request_id':request.state.request_id}
    if request.url.path=='/v1/messages':
        error['type']='authentication_error' if status==401 else 'permission_error' if status==403 else 'rate_limit_error' if status==429 else 'invalid_request_error' if status<500 else 'api_error'
        return {'type':'error','error':error,'request_id':request.state.request_id}
    return {'error':error}


@app.exception_handler(APIError)
async def api_error(request,error):
    request.state.failure_code=error.detail['code']
    return JSONResponse(error_body(request,error.detail['code'],error.detail['message'],error.status_code),status_code=error.status_code)


@app.exception_handler(RequestValidationError)
async def validation(request,error):
    request.state.failure_code='VALIDATION_ERROR'
    body=error.body
    if isinstance(body,dict):
        model=body.get('model')
        if isinstance(model,str) and re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,99}',model):request.state.safe_model=model
        request.state.safe_stream=body.get('stream') is True
    # Object-key locations may themselves contain secrets supplied by a caller.
    return JSONResponse(error_body(request,'VALIDATION_ERROR','请检查请求参数的格式、必填字段及取值范围',422),status_code=422)


@app.exception_handler(Exception)
async def unexpected(request,error):
    logging.getLogger(__name__).error('Request failed [%s] %s',type(error).__name__,request.state.request_id,extra={'request_id':request.state.request_id})
    from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeout
    from redis.exceptions import RedisError
    unavailable=isinstance(error,(DBAPIError,PoolTimeout,RedisError))
    status=503 if unavailable else 500
    code='DEPENDENCY_UNAVAILABLE' if unavailable else 'INTERNAL_ERROR'
    request.state.failure_code=code
    return JSONResponse(error_body(request,code,'服务暂不可用',status),status_code=status,headers={'X-Request-ID':request.state.request_id,'Cache-Control':'no-store'})


app.include_router(health_router)
app.include_router(health_router,prefix='/api',include_in_schema=False)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(profile_router)

app.include_router(groups_router)
app.include_router(keys_router)
app.include_router(identity_router)


app.include_router(providers_router)


app.include_router(mappings_router)
app.include_router(model_groups_router)
app.include_router(catalog_router)



@app.exception_handler(HTTPException)
async def http_error(request,error):
    return JSONResponse({'error':{'type':'gateway_error','code':'HTTP_'+str(error.status_code),
        'message':'请求资源不存在' if error.status_code==404 else '请求无法处理',
        'request_id':request.state.request_id}},status_code=error.status_code,headers=error.headers)

app.include_router(gateway_router)
app.include_router(resources_router)
app.include_router(call_logs_router)
from app.api.admin.smart_route import router as smart_route_router
app.include_router(smart_route_router)

from app.api.usage import router as usage_router
app.include_router(usage_router)

from app.api.admin.dashboard import router as dashboard_router
app.include_router(dashboard_router)

from app.api.admin.compliance import router as compliance_router
app.include_router(compliance_router)
from app.api.admin.audit_logs import router as audit_logs_router
from app.api.admin.backups import router as backups_router
app.include_router(audit_logs_router)
app.include_router(backups_router)
from app.api.admin.runtime import router as runtime_router
app.include_router(runtime_router)

from app.api.admin.settings import router as settings_router
app.include_router(settings_router)

from app.api.admin.chat_test import router as chat_test_router
app.include_router(chat_test_router)
