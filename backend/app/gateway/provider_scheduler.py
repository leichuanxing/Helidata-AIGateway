"""Sticky affinity, capacity-aware ranking and bounded pre-response failover."""
import asyncio
import hashlib
from contextlib import AsyncExitStack
from time import monotonic
import anyio
from redis.exceptions import RedisError
from app.core.redis import redis_client
from app.core.config import get_settings
from app.core.database import session_factory
from app.core.exceptions import APIError
from app.gateway import model_selection,provider_concurrency,protocol_adapter,upstream,provider_health,quota

from app.providers.operations import INFERENCE,TEXT,prepare

MAX_ATTEMPTS=8
REQUEST_TIMEOUT=120
STICKY_TTL=1800
RETRYABLE={'UPSTREAM_AUTH_FAILED','UPSTREAM_RATE_LIMITED','UPSTREAM_HTTP_ERROR','UPSTREAM_TIMEOUT',
    'UPSTREAM_NETWORK_ERROR','UPSTREAM_INVALID_RESPONSE','UPSTREAM_RESPONSE_TOO_LARGE','UPSTREAM_STREAM_INTERRUPTED'}

def sticky_key(ctx):
    return f'sticky:{ctx.key.id}:{hashlib.sha256(ctx.client_ip.encode()).hexdigest()[:24]}:{ctx.logical_model}'

async def remember(ctx):
    try: await redis_client.set(sticky_key(ctx),str(ctx.provider.id),ex=get_settings().gateway.sticky_timeout)
    except RedisError: pass

async def ranked(ctx,db,filter_capacity=True):
    routes,incompatible=await model_selection.routes(db,ctx)
    try: sticky=await redis_client.get(sticky_key(ctx))
    except RedisError: raise APIError(503,'SCHEDULER_UNAVAILABLE','调度状态暂不可用') from None
    result=[]
    for name,pairs in routes:
        providers=[provider for mapping,provider in pairs]
        counts=await provider_concurrency.loads(providers)
        pending=getattr(getattr(ctx,'admission',None),'pending',None)
        if pending in counts:counts[pending]=max(0,counts[pending]-1)
        pairs.sort(key=lambda pair:(0 if pair[1].id==pending else 1,0 if str(pair[1].id)==sticky else 1,pair[1].priority,
            counts[pair[1].id]/pair[1].max_concurrency,counts[pair[1].id],pair[1].failure_count,pair[1].id))
        result.extend((mapping,provider) for mapping,provider in pairs if not filter_capacity or counts[provider.id]<provider.max_concurrency)
    return result,incompatible

async def execute(request,ctx,resources):
    tried=set(); last=None
    def finish_timing(entry):
        if ctx.upstream_started is not None:
            entry['elapsed_ms']=round((monotonic()-ctx.upstream_started)*1000,2)
            ctx.upstream_elapsed_ms=(ctx.upstream_elapsed_ms or 0)+entry['elapsed_ms']
            ctx.upstream_started=None
    async def attempts():
        nonlocal last
        while len(tried)<MAX_ATTEMPTS:
            async with session_factory() as db: rows,incompatible=await ranked(ctx,db)
            rows=[pair for pair in rows if pair[0].id not in tried]
            if not rows:
                if ctx.admission:
                    async with session_factory() as db:remaining,_=await ranked(ctx,db,filter_capacity=False)
                    if any(mapping.id not in tried for mapping,provider in remaining):
                        await ctx.admission.readmit(tried);continue
                if last: raise last
                raise APIError(503,'NO_COMPATIBLE_PROVIDER' if incompatible else 'NO_AVAILABLE_PROVIDER','该模型及授权后继模型没有可用上游账号')
            if ctx.operation=='preflight':
                ctx.mapping,ctx.provider=rows[0]
                ctx.stages.append('protocol_adapter');protocol_adapter.bind(ctx)
                ctx.stages.append('upstream')
                return await upstream.execute(ctx)
            for mapping,provider in rows:
                if len(tried)>=MAX_ATTEMPTS: break
                tried.add(mapping.id);ctx.mapping,ctx.provider=mapping,provider
                attempt=AsyncExitStack()
                entry={'provider_id':provider.id,'provider_name':provider.name,'logical_model':mapping.logical_model,
                    'upstream_model':mapping.upstream_model,'protocol':provider.protocol,'config_version':provider.config_version,
                    'status':'not_sent','code':None,'http_status':None,'elapsed_ms':None}
                ctx.attempts.append(entry)
                transferred=False
                try:
                    await attempt.enter_async_context(provider_concurrency.acquire(ctx))
                    async with session_factory() as db:
                        fresh,_=await model_selection.routes(db,ctx)
                        valid=any(m.id==mapping.id and p.config_version==provider.config_version for _,pairs in fresh for m,p in pairs)
                    if not valid: continue
                    ctx.stages.extend(['provider_concurrency','protocol_adapter']);protocol_adapter.bind(ctx)
                    entry['protocol']=ctx.adapter.protocol_name
                    prepare(ctx)  # Reject lossy translations before reserving quota or sending upstream.
                    await attempt.enter_async_context(quota.acquire(ctx))
                    ctx.usage_snapshot={}
                    ctx.attempt_started=monotonic();ctx.stages.append('upstream')
                    ctx.upstream_started=ctx.attempt_started;entry['status']='started'
                    if ctx.operation in TEXT and ctx.payload.get('stream'):
                        response=await upstream.streaming(request,ctx,attempt)
                        await resources.enter_async_context(response.resources)
                        response.resources=resources.pop_all()
                        transferred=True
                        entry['http_status']=200
                        return response
                    result=await upstream.nonstream(request,ctx)
                    if ctx.operation in TEXT:
                        ctx.first_effective=ctx.generation_end=monotonic()
                        ctx.generation_start=ctx.upstream_started
                    finish_timing(entry)
                    quota.observe(ctx,result)
                    entry['status']='success';entry['http_status']=200
                    await provider_health.finish(ctx,'success')
                    if ctx.operation in TEXT: await remember(ctx)
                    return result
                except APIError as error:
                    finish_timing(entry)
                    code=error.detail['code']
                    entry['status']='client_cancelled' if code=='CLIENT_DISCONNECTED' else 'failure'
                    entry['code']=code;entry['http_status']=getattr(error,'upstream_status',None)
                    if code=='PROVIDER_BUSY': continue
                    if code=='CLIENT_DISCONNECTED': raise
                    await provider_health.finish(ctx,'failure',code)
                    if ctx.operation not in INFERENCE or code not in RETRYABLE: raise
                    last=error
                except BaseException as error:
                    finish_timing(entry)
                    entry['status']='client_cancelled' if isinstance(error,asyncio.CancelledError) else 'failure'
                    entry['code']='CLIENT_DISCONNECTED' if isinstance(error,asyncio.CancelledError) else 'INTERNAL_ERROR'
                    raise
                finally:
                    with anyio.CancelScope(shield=True): await attempt.aclose()
                    if not transferred and entry['status']!='not_sent' and ctx.upstream_started is not None:
                        finish_timing(entry)
        if last: raise last
        raise APIError(503,'NO_AVAILABLE_PROVIDER','账号当前并发已满或不可用')
    try:
        async with asyncio.timeout(REQUEST_TIMEOUT if REQUEST_TIMEOUT!=120 else get_settings().gateway.nonstream_timeout): return await attempts()
    except TimeoutError:
        if ctx.attempts:
            ctx.attempts[-1]['status']='failure';ctx.attempts[-1]['code']='UPSTREAM_TIMEOUT'
        await provider_health.finish(ctx,'failure','UPSTREAM_TIMEOUT')
        raise APIError(504,'UPSTREAM_TIMEOUT','上游调用超过调度总期限') from None
