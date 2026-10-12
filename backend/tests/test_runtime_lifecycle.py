"""Regression coverage for shutdown and real ASGI stream cancellation."""
import asyncio
import unittest
from contextlib import AsyncExitStack, asynccontextmanager
from unittest.mock import AsyncMock, patch
from app.services.lifecycle import shutdown
from app.gateway.context import GatewayContext
from app.gateway.streaming import GatewayStreamingResponse
from app.gateway.sse import events
from app.providers.base import ProviderFailure


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_worker_and_closer_do_not_skip_remaining_cleanup(self):
        stopped=asyncio.Event()
        async def failed():raise RuntimeError('secret must not be logged')
        async def running():
            try:await asyncio.Event().wait()
            finally:stopped.set()
        workers=[asyncio.create_task(failed()),asyncio.create_task(running())]
        await asyncio.sleep(0)
        first=AsyncMock(side_effect=RuntimeError('private connection URL'))
        last=AsyncMock()
        with self.assertLogs('app.lifecycle',level='ERROR') as captured:
            await shutdown(workers,[first,last])
        self.assertTrue(stopped.is_set())
        self.assertTrue(all(t.done() for t in workers))
        last.assert_awaited_once()
        self.assertNotIn('secret',' '.join(captured.output))
        self.assertNotIn('private',' '.join(captured.output))

    async def test_idle_stream_disconnect_closes_resources_and_records_cancel_once(self):
        started=asyncio.Event();released=[]
        class Upstream:
            async def aiter_bytes(self):
                started.set()
                await asyncio.Event().wait()
                yield b''
        @asynccontextmanager
        async def lease():
            try:yield
            finally:released.append(True)
        stack=AsyncExitStack();await stack.enter_async_context(lease())
        ctx=GatewayContext('req_disconnected','chat','fixture')
        response=GatewayStreamingResponse(ctx,Upstream(),stack)
        async def receive():
            await started.wait()
            return {'type':'http.disconnect'}
        sent=[]
        async def send(message):sent.append(message)
        with patch('app.gateway.provider_health.finish',AsyncMock()),patch('app.gateway.call_log.write',AsyncMock()) as log:
            await asyncio.wait_for(response({'type':'http','asgi':{'spec_version':'2.4'}},receive,send),1)
            await response.close()
            log.assert_awaited_once_with(ctx,'client_cancelled','CLIENT_DISCONNECTED')
        self.assertEqual(released,[True]);self.assertTrue(response.closed)
        self.assertEqual(sent[0]['type'],'http.response.start')

    async def test_sse_handles_every_byte_boundary_and_multiline(self):
        raw='\ufeff: ping\r\nevent: message\r\ndata: 中文\r\ndata: second\r\n\r\n'.encode()
        async def chunks():
            for byte in raw:yield bytes([byte])
        parsed=[item async for item in events(chunks())]
        self.assertIn(('message','中文\nsecond'),parsed)

    async def test_incomplete_sse_is_not_success(self):
        async def chunks():yield b'data: {"partial":true}'
        with self.assertRaises(ProviderFailure) as caught:
            _=[item async for item in events(chunks())]
        self.assertEqual(caught.exception.code,'UPSTREAM_STREAM_INTERRUPTED')
