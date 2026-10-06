from app.core.exceptions import APIError
import asyncio
from pydantic import ValidationError
from app.providers.base import ProviderFailure
from app.schemas.chat import ChatCompletion
from app.providers.operations import INFERENCE,PATHS,prepare,validate
from app.gateway.upstream_errors import translate
from app.gateway.streaming import GatewayStreamingResponse
from app.core.config import get_settings
import anyio

CHAT_TIMEOUT_SECONDS = 120

async def nonstream(request,ctx):
    result,failure,disconnected=None,None,False
    async with anyio.create_task_group() as group:
        async def monitor():
            nonlocal disconnected
            while True:
                message=await request.receive()
                if message['type']=='http.disconnect':
                    disconnected=True;group.cancel_scope.cancel();return
        group.start_soon(monitor)
        try:result=await execute(ctx)
        except Exception as error:failure=error
        finally:group.cancel_scope.cancel()
    if disconnected:raise APIError(499,'CLIENT_DISCONNECTED','客户端已断开')
    if failure:raise failure
    return result


async def execute(ctx):
    # Preflight performs zero network I/O or token consumption.
    if ctx.operation == 'preflight':
        return {'model': ctx.original_model or ctx.logical_model, 'ready': True, 'inference_enabled': ctx.adapter.wire_protocol in ('openai','anthropic') and ctx.mapping.model_type in ('text', 'reasoning', 'multimodal'),
                'deferred': ctx.deferred, 'quota':ctx.quota_status}
    if ctx.operation in INFERENCE:
        payload=prepare(ctx)
        ctx.adapter.request_id=ctx.request_id
        try:
            async with asyncio.timeout(CHAT_TIMEOUT_SECONDS if CHAT_TIMEOUT_SECONDS!=120 else getattr(get_settings().gateway,'nonstream_timeout',120)):
                if ctx.operation=='chat' and ctx.wire_operation=='chat':result=await ctx.adapter.chat_completion(payload)
                else:result=await ctx.adapter.request('POST',PATHS[ctx.wire_operation],payload,timeout=getattr(get_settings().gateway,'nonstream_timeout',120),max_bytes=32*1024*1024 if ctx.operation=='images' else 8*1024*1024)
            return validate(ctx,result)
        except (TimeoutError,ProviderFailure) as error:raise translate(error) from None
        except ValidationError:raise APIError(502,'UPSTREAM_INVALID_RESPONSE','上游响应格式无效') from None
    raise APIError(501, 'OPERATION_NOT_IMPLEMENTED', '模型生成将在后续阶段开放')


async def streaming(request, ctx, resources):
    payload=prepare(ctx)
    ctx.adapter.request_id = ctx.request_id
    response, failure, disconnected = None, None, False
    async with anyio.create_task_group() as group:
        async def open_headers():
            nonlocal response, failure
            try:
                response = await ctx.adapter.open_chat_stream(payload, resources, get_settings().gateway.stream_idle_timeout) if ctx.operation=='chat' and ctx.wire_operation=='chat' else await ctx.adapter.open_stream(PATHS[ctx.wire_operation],payload,resources,get_settings().gateway.stream_idle_timeout)
            except Exception as error:
                failure = error
            finally:
                group.cancel_scope.cancel()
        async def watch_disconnect():
            nonlocal disconnected
            while True:
                message = await request.receive()
                if message['type'] == 'http.disconnect':
                    disconnected = True
                    group.cancel_scope.cancel()
                    return
        group.start_soon(watch_disconnect)
        await open_headers()
    if disconnected:
        raise APIError(499, 'CLIENT_DISCONNECTED', '客户端已断开')
    if failure:
        if isinstance(failure, ProviderFailure):
            raise translate(failure) from None
        raise failure
    if response is None:
        raise APIError(502, 'UPSTREAM_STREAM_INTERRUPTED', '上游连接已中断')
    from app.gateway.protocol_streaming import ProtocolStreamingResponse
    response_class=GatewayStreamingResponse if ctx.operation=='chat' and ctx.wire_operation=='chat' else ProtocolStreamingResponse
    return response_class(ctx,response,resources.pop_all())
