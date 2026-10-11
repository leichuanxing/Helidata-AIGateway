"""Routing compliance regression checks without model calls or database writes."""
import unittest
from contextlib import asynccontextmanager, ExitStack
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from starlette.requests import Request
from app.core.exceptions import APIError
from app.gateway import compliance, pipeline
from app.gateway.context import GatewayContext
from app.models.compliance import CompliancePolicy, AuditWord, AuditSample
from app.services import operations_settings


def policy(ident, models=(), action='block', groups=(78,), samples=()):
    return NS(id=ident, name=f'policy-{ident}', status='enabled', action=action,
              risk=None, description='', word_ids=[] if samples else [1],
              sample_ids=list(samples), group_ids=list(groups), models=list(models), threshold=.85)


class DB:
    def __init__(self, policies):
        self.policies=policies

    async def scalars(self, query):
        entity=query.column_descriptions[0]['entity']
        rows=self.policies if entity is CompliancePolicy else [NS(id=1, pattern='blocked-text',
             kind='text', risk='high', status='enabled')] if entity is AuditWord else [NS(
             id=2, revision=1, vector_status='ready', risk='high', status='enabled', text='sample')]
        return NS(all=lambda: rows)

    async def commit(self): pass
    def in_transaction(self): return False


def context(model='virtual', operation='chat', inherited=False):
    ctx=GatewayContext('req_regression', operation, model,
        {'model':model, 'messages':[{'role':'user','content':'blocked-text'}]})
    ctx.user=NS(id=1);ctx.group=NS(id=78)
    ctx.request=Request({'type':'http', 'state':{'compliance_checked':inherited}, 'headers':[]})
    return ctx


class ComplianceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(operations_settings.governance,
            {'compliance_enabled':True,'semantic_threshold':None}))
        self.logs=self.stack.enter_context(patch.object(compliance.compliance_logs,'write',
            AsyncMock(return_value='stored')))

    async def test_multimodal_text_blocks_and_media_metadata_does_not(self):
        from copy import deepcopy
        for prompt,blocked in [('提取图片文字',False),('blocked-text',True)]:
            ctx=context('real')
            ctx.payload['messages'][0]['content']=[{'type':'text','text':prompt},
                {'type':'image_url','image_url':{'url':'https://example.com/blocked-text.png'}},
                {'type':'file','file':{'filename':'blocked-text.pdf','file_data':'blocked-text'}}]
            original=deepcopy(ctx.payload)
            if blocked:
                with self.assertRaises(APIError) as caught:await compliance.check(DB([policy(1,['real'])]),ctx)
                self.assertEqual(caught.exception.detail['code'],'CONTENT_BLOCKED')
            else:
                await compliance.check(DB([policy(1,['real'])]),ctx)
                self.assertEqual(ctx.deferred['compliance']['action'],'pass')
            self.assertEqual(ctx.payload,original)

    async def test_media_only_skips_empty_semantic_embedding(self):
        ctx=context('real');ctx.payload['messages'][0]['content']=[{'type':'input_image','image_url':'https://example.com/a.png'}]
        with patch.object(compliance,'embed',AsyncMock()) as embed:
            await compliance.check(DB([policy(1,['real'],samples=[2])]),ctx)
        embed.assert_not_awaited()
        self.assertEqual(ctx.deferred['compliance']['action'],'pass')

    def test_protocols_extract_text_without_media(self):
        for operation,payload in [('messages',{'messages':[{'content':[{'type':'text','text':'问题'},{'type':'document','source':{'data':'blocked-text'},'text':'blocked-text'}]}]}),
            ('responses',{'input':[{'content':[{'type':'input_text','text':'问题'},{'type':'input_image','image_url':'blocked-text'},{'type':'input_file','file_data':'blocked-text'}]}]})]:
            self.assertEqual(compliance.content(NS(operation=operation,payload=payload)),'问题')

    async def test_multiline_sample_literal_blocks_without_embedding(self):
        sample=dict(id=2,revision=1,vector_status='ready',risk='high',status='enabled',
                    text='山东弘信天诚信息技术有限公司\n北京思源佳通科技有限公司')
        p=policy(1,['real'],samples=[2]);snapshot=([{k:getattr(p,k) for k in
            ('id','name','action','risk','description','word_ids','sample_ids','group_ids','models','threshold')}],[],[sample])
        for prompt in ['山东弘信天诚信息技术有限公司','请介绍北京思源佳通科技有限公司']:
            ctx=context('real');ctx.payload['messages'][0]['content']=prompt
            with patch.object(compliance,'load',AsyncMock(return_value=snapshot)), \
                 patch.object(compliance,'embed',AsyncMock()) as embed:
                with self.assertRaises(APIError) as caught:await compliance.check(DB([]),ctx)
            self.assertEqual(caught.exception.detail['code'],'CONTENT_BLOCKED');embed.assert_not_awaited()
            self.assertEqual(ctx.deferred['compliance']['matches'][0]['evidence'][0]['match_type'],'literal')

    async def test_literal_audit_does_not_repeat_semantic_call(self):
        p=policy(1,['real'],action='audit',samples=[2]);sample=dict(id=2,revision=1,
            vector_status='pending',risk='high',status='enabled',text='blocked-text')
        snapshot=([{k:getattr(p,k) for k in ('id','name','action','risk','description','word_ids','sample_ids','group_ids','models','threshold')}],[],[sample])
        ctx=context('real')
        with patch.object(compliance,'load',AsyncMock(return_value=snapshot)),patch.object(compliance,'embed',AsyncMock()) as embed:
            await compliance.check(DB([]),ctx)
        self.assertEqual(ctx.deferred['compliance']['action'],'audit');embed.assert_not_awaited()

    def test_literal_normalization_and_no_partial_line_false_positive(self):
        from app.services.compliance_sources import sample_literal_matches
        sample=dict(id=2,text='ＡＢＣ Company\nSecond Company',risk='high')
        self.assertEqual(sample_literal_matches([sample],'please review abc company')[0]['matched_text'],'ＡＢＣ Company')
        self.assertEqual(sample_literal_matches([sample],'Company'),[])

    async def test_actual_model_policy_blocks_after_route(self):
        db=DB([policy(1,['real'])]);ctx=context()
        await compliance.check(db,ctx)
        self.assertEqual(ctx.deferred['compliance'],'not_applicable')
        ctx.original_model='virtual';ctx.logical_model='real'
        with self.assertRaises(APIError) as caught: await compliance.check(db,ctx,routed=True)
        self.assertEqual(caught.exception.detail['code'],'CONTENT_BLOCKED')
        await compliance.finalize(ctx);await compliance.finalize(ctx)
        self.logs.assert_awaited_once()
        record=self.logs.call_args.args[0]
        self.assertEqual((record['model'],record['status_code']),('virtual',403))

    async def test_virtual_policy_blocks_before_route(self):
        ctx=context();db=DB([policy(1,['virtual'])])
        with self.assertRaises(APIError): await compliance.check(db,ctx)
        self.assertEqual(ctx.deferred['compliance']['action'],'block')

    async def test_global_and_target_audits_merge_once(self):
        db=DB([policy(1,action='audit'),policy(2,['real'],action='audit')]);ctx=context()
        await compliance.check(db,ctx)
        ctx.original_model='virtual';ctx.logical_model='real'
        await compliance.check(db,ctx,routed=True)
        await compliance.check(db,ctx,routed=True)
        await compliance.finalize(ctx)
        self.assertEqual([m['policy_id'] for m in self.logs.call_args.args[0]['matches']],[1,2])

    async def test_other_models_and_user_groups_do_not_match(self):
        db=DB([policy(1,['other']),policy(2,['real'],groups=[999])]);ctx=context('real')
        await compliance.check(db,ctx,routed=True);await compliance.finalize(ctx)
        self.logs.assert_not_awaited()

    async def test_disabled_governance_and_preflight_skip(self):
        ctx=context();db=DB([policy(1)])
        with patch.dict(operations_settings.governance,{'compliance_enabled':False}):
            await compliance.check(db,ctx)
        self.assertEqual(ctx.deferred['compliance'],'disabled')
        ctx=context(operation='preflight');await compliance.check(db,ctx,routed=True)
        self.assertEqual(ctx.deferred['compliance'],'preflight_not_checked')

    async def test_embedding_child_inherits_parent_check(self):
        ctx=context('real',inherited=True);db=DB([policy(1)])
        await compliance.check(db,ctx);await compliance.check(db,ctx,routed=True)
        self.assertEqual(ctx.deferred['compliance'],'parent_checked')

    async def test_failover_model_policy_is_checked(self):
        ctx=context('real');db=DB([policy(1,['fallback'])])
        await compliance.check(db,ctx)
        with self.assertRaises(APIError):
            await compliance.check(db,ctx,routed=True,model='fallback')
        self.assertEqual(ctx.logical_model,'real')

    async def test_routed_semantic_policy_blocks(self):
        db=DB([policy(1,['real'],samples=[2])]);ctx=context('real')
        @asynccontextmanager
        async def session(): yield db
        with patch.object(compliance,'session_factory',session), \
             patch.object(compliance,'embed',AsyncMock(return_value=[[1,0]])) as embed, \
             patch.object(compliance,'semantic',AsyncMock(return_value={2:{'source':'sample',
                  'id':2,'risk':'high','text':'sample','similarity':.99}})):
            with self.assertRaises(APIError): await compliance.check(db,ctx,routed=True)
        embed.assert_awaited_once()

    async def test_pipeline_blocks_before_provider_and_delivers_log(self):
        db=DB([policy(1,['real'])]);request=context().request
        request.state.request_id='req_pipeline_regression'
        @asynccontextmanager
        async def lease(*args): yield
        async def route(db,ctx):
            ctx.original_model=ctx.logical_model;ctx.logical_model='real';ctx.route_config_id=3
        with ExitStack() as stack:
            stack.enter_context(patch.object(pipeline.preparation,'acquire',lease))
            stack.enter_context(patch.object(pipeline.authentication,'authenticate',AsyncMock(
                return_value=(NS(id=1),NS(id=1),NS(id=78)))))
            for module,name in [(pipeline.user_validation,'validate'),(pipeline.group_validation,'validate'),
                                (pipeline.body_logs,'begin')]:
                stack.enter_context(patch.object(module,name,lambda *args:None))
            stack.enter_context(patch.object(pipeline.model_permission,'check',AsyncMock()))
            stack.enter_context(patch.object(pipeline.smart_routing,'route',route))
            upstream=stack.enter_context(patch.object(pipeline.provider_scheduler,'execute',AsyncMock()))
            calls=stack.enter_context(patch.object(pipeline.call_log,'write',AsyncMock()))
            with self.assertRaises(APIError) as caught:
                await pipeline.GatewayPipeline().run(request,db,'chat','virtual',
                    {'model':'virtual','messages':[{'role':'user','content':'blocked-text'}]})
        self.assertEqual(caught.exception.detail['code'],'CONTENT_BLOCKED')
        upstream.assert_not_awaited();calls.assert_awaited_once();self.logs.assert_awaited_once()


if __name__=='__main__': unittest.main()
