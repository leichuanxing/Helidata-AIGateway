"""Focused scheduler edge tests, supplementing real HTTP/Redis regression tests."""
import asyncio,unittest
from contextlib import asynccontextmanager,AsyncExitStack,ExitStack
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
from app.core.exceptions import APIError
from app.gateway.context import GatewayContext
from app.gateway import provider_scheduler as scheduler,compliance

class SchedulerBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self,waiting=False,fallback=False):
        ctx=GatewayContext('boundary','chat','primary',{'messages':[],'stream':False})
        a=NS(id=1,logical_model='fallback' if fallback else 'primary',upstream_model='upstream')
        b=NS(id=2,logical_model='primary',upstream_model='upstream')
        pa=NS(id=1,name='a',protocol='openai',config_version=1,priority=0,max_concurrency=2)
        pb=NS(id=2,name='b',protocol='openai',config_version=1,priority=0,max_concurrency=2)
        ctx.balancing={'strategy':'round_robin','group_id':1,'max_retries':1,'attempt_timeout':120,'retry_uncertain':False,'weights':{}}
        @asynccontextmanager
        async def session():yield NS()
        @asynccontextmanager
        async def lease(*args):yield
        async def blocked(*args):await asyncio.Event().wait()
        async def failed(*args):
            error=APIError(502,'UPSTREAM_NETWORK_ERROR','connection failed');error.safe_to_retry=True;raise error
        ctx.admission=NS(readmit=AsyncMock(side_effect=blocked)) if waiting else None
        def bind(ctx):ctx.adapter=NS(protocol_name='openai-completions',http_status=None)
        with ExitStack() as stack:
            stack.enter_context(patch.object(scheduler,'REQUEST_TIMEOUT',.04))
            stack.enter_context(patch.object(scheduler,'session_factory',session))
            stack.enter_context(patch.object(scheduler,'ranked',AsyncMock(side_effect=[([(a,pa)],False),([(b,pb)],False)])))
            stack.enter_context(patch.object(scheduler.model_selection,'routes',AsyncMock(return_value=([('primary',[(a,pa)])],False))))
            stack.enter_context(patch.object(scheduler.provider_concurrency,'acquire',lease))
            stack.enter_context(patch.object(scheduler.protocol_adapter,'bind',bind))
            stack.enter_context(patch.object(scheduler,'prepare',lambda ctx:None))
            stack.enter_context(patch.object(scheduler.quota,'acquire',lease))
            upstream=stack.enter_context(patch.object(scheduler.upstream,'nonstream',AsyncMock(side_effect=failed if waiting else blocked)))
            health=stack.enter_context(patch.object(scheduler.provider_health,'finish',AsyncMock()))
            check=stack.enter_context(patch.object(compliance,'check',AsyncMock(side_effect=APIError(403,'CONTENT_BLOCKED','blocked')) if fallback else AsyncMock()))
            with self.assertRaises(APIError) as caught:
                async with AsyncExitStack() as resources:await scheduler.execute(NS(),ctx,resources)
            return ctx,caught.exception,health,check,upstream

    async def test_total_deadline_during_readmission_does_not_reclassify_previous_failure(self):
        ctx,error,health,_,_=await self.run_case(waiting=True)
        self.assertEqual(error.detail['code'],'UPSTREAM_TIMEOUT')
        self.assertEqual(ctx.attempts[0]['code'],'UPSTREAM_NETWORK_ERROR')
        self.assertTrue(ctx.upstream_not_processed)
        health.assert_awaited_once_with(ctx,'failure','UPSTREAM_NETWORK_ERROR')

    async def test_total_deadline_in_flight_is_one_failure_not_client_cancellation(self):
        ctx,error,health,_,_=await self.run_case()
        self.assertEqual(error.detail['code'],'UPSTREAM_TIMEOUT')
        self.assertEqual(ctx.attempts[0]['status'],'failure')
        self.assertEqual(ctx.attempts[0]['code'],'UPSTREAM_TIMEOUT')
        health.assert_awaited_once_with(ctx,'failure','UPSTREAM_TIMEOUT')

    async def test_plain_model_group_fallback_checks_target_compliance_before_upstream(self):
        ctx,error,health,check,upstream=await self.run_case(fallback=True)
        self.assertEqual(error.detail['code'],'CONTENT_BLOCKED')
        self.assertIsNone(ctx.route_config_id)
        self.assertEqual(check.await_args.kwargs,{'routed':True,'model':'fallback'})
        upstream.assert_not_awaited();health.assert_not_awaited()

    async def test_local_pool_exhaustion_is_known_unsent_for_json_and_sse(self):
        from app.providers.base import OpenAIProvider,ProviderFailure,pools
        from app.providers.pool import PoolCapacityError
        from app.gateway.upstream_errors import translate
        @asynccontextmanager
        async def exhausted(*args):
            raise PoolCapacityError()
            yield
        adapter=OpenAIProvider('http://127.0.0.1:1/v1')
        with patch.object(pools,'acquire',exhausted):
            with self.assertRaises(ProviderFailure) as failed:await adapter.chat_completion({'model':'fixture','messages':[]})
            self.assertTrue(translate(failed.exception).safe_to_retry)
            async with AsyncExitStack() as resources:
                with self.assertRaises(ProviderFailure) as failed:await adapter.open_chat_stream({'model':'fixture'},resources,10)
            self.assertTrue(translate(failed.exception).safe_to_retry)
