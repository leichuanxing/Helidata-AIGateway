"""Own the upstream and resource leases until the ASGI response really finishes."""
import asyncio
import json
import anyio
import httpx
from fastapi.responses import StreamingResponse
from starlette.requests import ClientDisconnect
from pydantic import ValidationError
from time import monotonic
from app.core.exceptions import APIError
from app.providers.base import ProviderFailure
from app.schemas.chat import ChatCompletionChunk
from app.gateway.sse import events
from app.gateway import call_log


def frame(data, event=None):
    prefix = ('event: ' + event + '\n') if event else ''
    return (prefix + 'data: ' + data + '\n\n').encode('utf-8')


class GatewayStreamingResponse(StreamingResponse):
    def __init__(self, ctx, upstream, resources):
        self.ctx, self.upstream, self.resources = ctx, upstream, resources
        self.outcome, self.code, self.closed = 'client_cancelled', 'CLIENT_DISCONNECTED', False
        super().__init__(self.chunks(), media_type='text/event-stream', headers={
            'X-Request-ID': ctx.request_id, 'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

    async def chunks(self):
        try:
            async for event, data in events(self.upstream.aiter_bytes()):
                if event == 'heartbeat':
                    yield b': keep-alive\n\n'
                    continue
                if event == 'error':
                    raise ProviderFailure('UPSTREAM_STREAM_ERROR')
                if data.strip() == '[DONE]':
                    self.ctx.generation_end=monotonic()
                    self.outcome, self.code = 'success', None
                    yield frame('[DONE]')
                    return
                decoded = json.loads(data)
                if isinstance(decoded, dict) and 'error' in decoded:
                    raise ProviderFailure('UPSTREAM_STREAM_ERROR')
                ChatCompletionChunk.model_validate(decoded)
                from app.gateway.quota import observe
                observe(self.ctx,decoded)
                from app.gateway.usage import effective
                if effective(decoded):
                    if self.ctx.first_effective is None:self.ctx.first_effective=monotonic()
                    self.ctx.generation_end=monotonic()
                decoded['model'] = self.ctx.original_model or self.ctx.logical_model
                from app.services.body_logs import response as capture
                capture(self.ctx,decoded,stream=True)
                self.ctx.stream_chunks += 1
                yield frame(json.dumps(decoded, ensure_ascii=False, separators=(',', ':')))
            raise ProviderFailure('UPSTREAM_STREAM_INTERRUPTED')
        except asyncio.CancelledError:
            self.ctx.generation_end=monotonic()
            raise
        except (ProviderFailure, httpx.HTTPError, ValueError, ValidationError, APIError) as error:
            self.ctx.generation_end=monotonic()
            self.outcome = 'failure'
            if isinstance(error, (httpx.TimeoutException, TimeoutError)):
                self.code = 'UPSTREAM_TIMEOUT'
            elif isinstance(error, ProviderFailure):
                self.code = error.code
            elif isinstance(error, httpx.HTTPError):
                self.code = 'UPSTREAM_NETWORK_ERROR'
            else:
                self.code = 'UPSTREAM_INVALID_RESPONSE'
            yield self.error_frame()
        except Exception:
            self.ctx.generation_end=monotonic()
            self.outcome, self.code = 'failure', 'INTERNAL_ERROR'
            yield self.error_frame()

    def error_frame(self):
        return frame(json.dumps({'error': {'type': 'gateway_error', 'code': self.code,
            'message': '上游流式响应中断', 'request_id': self.ctx.request_id}}, ensure_ascii=False), 'error')

    async def close(self):
        if self.closed:
            return
        self.closed = True
        if self.ctx.attempts and self.ctx.upstream_started is not None:
            entry=self.ctx.attempts[-1]
            entry['elapsed_ms']=round((monotonic()-self.ctx.upstream_started)*1000,2)
            self.ctx.upstream_elapsed_ms=(self.ctx.upstream_elapsed_ms or 0)+entry['elapsed_ms']
            self.ctx.upstream_started=None
        with anyio.CancelScope(shield=True):
            try:
                from app.gateway import provider_health, provider_scheduler
                try:
                    await provider_health.finish(self.ctx, self.outcome, self.code)
                    if self.outcome == 'success':
                        await provider_scheduler.remember(self.ctx)
                finally:
                    await self.resources.aclose()
            except Exception:
                self.outcome, self.code = 'failure', 'RESOURCE_CLOSE_FAILED'
            finally:
                self.ctx.stages.extend(['usage', 'call_log'])
                self.ctx.response_status=200  # Headers are already sent; terminal status records in-stream errors separately.
                if self.ctx.attempts:
                    entry=self.ctx.attempts[-1];entry['status']=self.outcome;entry['code']=self.code
                await call_log.write(self.ctx, self.outcome, self.code)

    async def __call__(self, scope, receive, send):
        try:
            # Always watch disconnects, including ASGI2.4+ while an upstream is idle.
            async with anyio.create_task_group() as group:
                async def emit():
                    try:
                        await self.stream_response(send)
                    except (ClientDisconnect, OSError):
                        self.outcome, self.code = 'client_cancelled', 'CLIENT_DISCONNECTED'
                    except Exception:
                        self.outcome, self.code = 'failure', 'INTERNAL_STREAM_ERROR'
                    finally:
                        group.cancel_scope.cancel()
                group.start_soon(emit)
                await self.listen_for_disconnect(receive)
                self.outcome, self.code = 'client_cancelled', 'CLIENT_DISCONNECTED'
                group.cancel_scope.cancel()
        finally:
            if self.ctx.provider_lease_lost or self.ctx.lease_error:
                self.outcome, self.code = 'failure', self.ctx.lease_error or 'SCHEDULER_UNAVAILABLE'
            await self.close()
