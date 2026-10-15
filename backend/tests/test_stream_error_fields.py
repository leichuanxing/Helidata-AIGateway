"""SSE compatibility must distinguish null error fields from real errors."""
import json,unittest
from contextlib import AsyncExitStack
from unittest.mock import patch
from app.gateway.context import GatewayContext
from app.gateway.streaming import GatewayStreamingResponse
from app.gateway.protocol_streaming import ProtocolStreamingResponse

class StreamErrorFieldTests(unittest.IsolatedAsyncioTestCase):
    async def run_frames(self,operation,frames):
        class Upstream:
            async def aiter_bytes(self):
                for item in frames:yield ('data: '+(item if isinstance(item,str) else json.dumps(item))+'\n\n').encode()
        ctx=GatewayContext('req_null_error',operation,'fixture');ctx.wire_operation=operation
        cls=GatewayStreamingResponse if operation=='chat' else ProtocolStreamingResponse
        response=cls(ctx,Upstream(),AsyncExitStack())
        with patch('app.gateway.quota.observe'),patch('app.services.body_logs.response'):
            body=b''.join([part async for part in response.chunks()])
        return response,body

    async def test_chat_null_error_is_success(self):
        chunk={'id':'chunk','object':'chat.completion.chunk','created':1,'model':'fixture','choices':[{'index':0,'delta':{'content':'ok'},'finish_reason':None}],'error':None}
        response,body=await self.run_frames('chat',[chunk,'[DONE]'])
        self.assertEqual(response.outcome,'success');self.assertIn(b'[DONE]',body)

    async def test_chat_real_error_is_sanitized_failure(self):
        response,body=await self.run_frames('chat',[{'error':{'message':'upstream-private-key'}}])
        self.assertEqual(response.outcome,'failure');self.assertNotIn(b'upstream-private-key',body)

    async def test_responses_null_error_is_success(self):
        result={'id':'r','object':'response','model':'fixture','output':[],'status':'completed'}
        response,body=await self.run_frames('responses',[{'type':'response.created','response':result,'error':None},{'type':'response.completed','response':result,'error':None}])
        self.assertEqual(response.outcome,'success');self.assertIn(b'response.completed',body)

    async def test_responses_real_error_is_sanitized_failure(self):
        response,body=await self.run_frames('responses',[{'error':{'message':'upstream-private-key'}}])
        self.assertEqual(response.outcome,'failure');self.assertNotIn(b'upstream-private-key',body)
