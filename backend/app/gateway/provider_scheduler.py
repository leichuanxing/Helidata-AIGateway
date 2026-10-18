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
    identity = str(ctx.key.id) if ctx.key else f'webchat:{ctx.user.id}'
    return f'sticky:{identity}:{hashlib.sha256(ctx.client_ip.encode()).hexdigest()[:24]}:{ctx.logical_model}'

async def remember(ctx):
    try: await redis_client.set(sticky_key(ctx),str(ctx.provider.id),ex=get_settings().gateway.sticky_timeout)
    except RedisError: pass

async def ranked(ctx,db,filter_capacity=True):
    routes,incompatible=await model_selection.routes(db,ctx)
    if getattr(ctx,'balance_route',None):
        pairs=[pair for name,rows in routes for pair in rows]
        pending=getattr(getattr(ctx,'admission',None),'pending_mapping',None)
        pairs.sort(key=lambda pair:(pair[0].id!=pending,ctx.balance_nodes[pair[0].id].id))
        # Admission owns account/node/group capacity atomically. Its reserved mapping
        # must be attempted first, including multiple mappings of the same account.
        return pairs,incompatible
    try: sticky=await redis_client.get(sticky_key(ctx))
    except RedisError: raise APIError(503,'SCHEDULER_UNAVAILABLE','调度状态暂不可用') from None
    result=[]
    for name,pairs in routes:
        providers=[provider for mapping,provider in pairs]
        counts=await provider_concurrency.loads(providers)
        pending=getattr(getattr(ctx,'admission',None),'pending',None)
        if pending in counts:counts[pending]=max(0,counts[pending]-1)
        from app.providers.configuration import NATIVE,select_protocol
        pairs.sort(key=lambda pair:(0 if select_protocol(pair[1],ctx.operation)==NATIVE.get(ctx.operation) else 1,0 if pair[1].id==pending else 1,0 if str(pair[1].id)==sticky else 1,pair[1].priority,
            counts[pair[1].id]/pair[1].max_concurrency,counts[pair[1].id],pair[1].failure_count,pair[1].id))
        result.extend((mapping,provider) for mapping,provider in pairs if not filter_capacity or counts[provider.id]<provider.max_concurrency)
    return result,incompatible

async def execute(request,ctx,resources):
    tried=set(); last=None
    sent=0
    route=None
    deadline=asyncio.timeout(REQUEST_TIMEOUT if REQUEST_TIMEOUT!=120 else get_settings().gateway.nonstream_timeout)
    async def send(stream,attempt):
        try:
            async with asyncio.timeout(route.timeout_seconds):
                return await upstream.streaming(request,ctx,attempt) if stream else await upstream.nonstream(request,ctx)
        except TimeoutError:raise APIError(504,'UPSTREAM_TIMEOUT','上游调用超过路由单次期限') from None
    def finish_timing(entry):
        if ctx.upstream_started is not None:
            entry['elapsed_ms']=round((monotonic()-ctx.upstream_started)*1000,2)
            ctx.upstream_elapsed_ms=(ctx.upstream_elapsed_ms or 0)+entry['elapsed_ms']
            ctx.upstream_started=None
    async def attempts():
        nonlocal last,sent,route
        while len(tried)<MAX_ATTEMPTS:
            async with session_factory() as db: rows,incompatible=await ranked(ctx,db)
            route=getattr(ctx,'balance_route',None)
            if route and sent>=route.max_retries+1:
                if last:raise last
                raise APIError(503,'NO_AVAILABLE_PROVIDER','已达到路由重试次数上限')
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
                if route and sent>=route.max_retries+1:
                    if last:raise last
                    break
                tried.add(mapping.id);ctx.mapping,ctx.provider=mapping,provider
                ctx.balance_node=ctx.balance_nodes.get(mapping.id) if route else None
                if (ctx.route_config_id or route) and mapping.logical_model!=ctx.logical_model:
                    # Failover within the selected group must not bypass its model policies.
                    from app.gateway import compliance
                    async with session_factory() as db:
                        ctx.stages.append('routed_compliance')
                        await compliance.check(db,ctx,routed=True,model=mapping.logical_model)
                attempt=AsyncExitStack()
                entry={'provider_id':provider.id,'provider_name':provider.name,'logical_model':mapping.logical_model,
                    'upstream_model':mapping.upstream_model,'protocol':provider.protocol,'config_version':provider.config_version,
                    'status':'not_sent','code':None,'http_status':None,'elapsed_ms':None}
                if route:entry.update(balance_route_id=route.id,balance_route_name=route.name,balance_model=route.model_name,
                    balance_node_id=ctx.balance_node.id,balancing_strategy=route.strategy,retry_count=sent,
                    switch_reason=last.detail['code'] if last else None)
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
                    sent+=1
                    if ctx.operation in TEXT and ctx.payload.get('stream'):
                        response=await send(True,attempt) if route else await upstream.streaming(request,ctx,attempt)
                        await resources.enter_async_context(response.resources)
                        response.resources=resources.pop_all()
                        transferred=True
                        entry['http_status']=200
                        return response
                    result=await send(False,attempt) if route else await upstream.nonstream(request,ctx)
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
                    ctx.upstream_not_processed=getattr(error,'safe_to_retry',False)
                    if code=='PROVIDER_BUSY': continue
                    if code=='CLIENT_DISCONNECTED': raise
                    await provider_health.finish(ctx,'failure',code)
                    if ctx.operation not in INFERENCE or code not in RETRYABLE: raise
                    if route:
                        from app.gateway.balanced_routing import safe_retry
                        if not safe_retry(error,route):entry['retry_suppressed']='upstream_may_have_processed';raise
                    last=error
                except BaseException as error:
                    finish_timing(entry)
                    timed_out=isinstance(error,asyncio.CancelledError) and deadline.expired()
                    was_sent=entry['status']=='started'
                    entry['status']='failure' if timed_out else 'client_cancelled' if isinstance(error,asyncio.CancelledError) else 'failure'
                    entry['code']='UPSTREAM_TIMEOUT' if timed_out else 'CLIENT_DISCONNECTED' if isinstance(error,asyncio.CancelledError) else 'INTERNAL_ERROR'
                    if timed_out and was_sent:
                        with anyio.CancelScope(shield=True):await provider_health.finish(ctx,'failure','UPSTREAM_TIMEOUT')
                    raise
                finally:
                    with anyio.CancelScope(shield=True): await attempt.aclose()
                    if not transferred and entry['status']!='not_sent' and ctx.upstream_started is not None:
                        finish_timing(entry)
                if route and last and ctx.admission:
                    if sent>=route.max_retries+1:raise last
                    async with session_factory() as db:remaining,_=await ranked(ctx,db,filter_capacity=False)
                    if not any(m.id not in tried for m,p in remaining):raise last
                    await ctx.admission.readmit(tried);break
        if last: raise last
        raise APIError(503,'NO_AVAILABLE_PROVIDER','账号当前并发已满或不可用')
    try:
        async with deadline:return await attempts()
    except TimeoutError:
        raise APIError(504,'UPSTREAM_TIMEOUT','上游调用超过调度总期限') from None
