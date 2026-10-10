"""Web chat authorization, payload limits and shared gateway regression tests."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from starlette.requests import Request
from pydantic import ValidationError
from app.api.admin.chat_test import ChatTestInput, models, completion
from app.core.exceptions import APIError
from app.gateway import authentication
from app.gateway.provider_scheduler import sticky_key
from app.services.key_auth import record_key_use

class ChatTests(unittest.IsolatedAsyncioTestCase):
    def request(self,path='/api/admin/chat-test/completions'):
        return Request({'type':'http','method':'POST','path':path,'headers':[(b'authorization',b'Bearer web-token')],'state':{}})

    async def test_admin_session_uses_no_implicit_api_key(self):
        user=NS(id=1,role='admin',user_group_id=2,must_change_password=False)
        group=NS(id=2)
        with patch('app.core.dependencies.current_user',AsyncMock(return_value=user)), patch('app.services.group_access.resolve_group',AsyncMock(return_value=group)):
            request=self.request();key,actor,resolved=await authentication.authenticate(request,NS())
            self.assertIsNone(key);self.assertIs(actor,user);self.assertIs(resolved,group);self.assertTrue(request.state.web_chat)

    async def test_ordinary_user_rejected(self):
        user=NS(role='user',user_group_id=2,must_change_password=False)
        with patch('app.core.dependencies.current_user',AsyncMock(return_value=user)):
            with self.assertRaises(APIError) as caught:await authentication.authenticate(self.request(),NS())
            self.assertEqual(caught.exception.status_code,403)

    async def test_password_change_required_rejected(self):
        user=NS(role='admin',must_change_password=True)
        with patch('app.core.dependencies.current_user',AsyncMock(return_value=user)):
            with self.assertRaises(APIError) as caught:await authentication.authenticate(self.request(),NS())
            self.assertEqual(caught.exception.detail['code'],'PASSWORD_CHANGE_REQUIRED')

    async def test_web_token_not_accepted_on_public_gateway(self):
        with self.assertRaises(APIError) as caught:await authentication.authenticate(self.request('/v1/chat/completions'),NS())
        self.assertEqual(caught.exception.status_code,401)

    async def test_revoked_session_rejected(self):
        with patch('app.core.dependencies.current_user',AsyncMock(side_effect=APIError(401,'SESSION_INVALID','invalid'))):
            with self.assertRaises(APIError):await authentication.authenticate(self.request(),NS())

    async def test_web_chat_commits_without_api_key_write(self):
        db=NS(commit=AsyncMock(),execute=AsyncMock())
        await record_key_use(db,NS(key=None));db.commit.assert_awaited_once();db.execute.assert_not_awaited()

    async def test_catalog_filters_types_and_deduplicates(self):
        item=dict(logical_model='chat',model_type='text',configured=True,virtual=False)
        groups=[dict(name='first',models=[item,dict(item,logical_model='vector',model_type='embedding')]),dict(name='second',models=[dict(item,configured=False),dict(item,logical_model='virtual',virtual=True)])]
        with patch('app.api.admin.chat_test.catalog',AsyncMock(return_value=groups)):
            result=await models(NS(user_group_id=1),NS())
        self.assertEqual(len(result['data']['models']),2);self.assertEqual(result['data']['models'][0]['groups'],['first','second']);self.assertTrue(result['data']['models'][0]['configured'])

    async def test_completion_uses_full_pipeline(self):
        body=ChatTestInput(model='chat',messages=[dict(role='user',content='hello')])
        with patch('app.api.admin.chat_test.pipeline.run',AsyncMock(return_value={'ok':True})) as run:
            await completion(body,self.request(),NS(),NS())
        args=run.call_args.args;self.assertEqual(args[2:4],('chat','chat'));self.assertTrue(args[4]['stream_options']['include_usage'])

    def test_identity_namespaces_are_separate(self):
        web=NS(key=None,user=NS(id=7),client_ip='127.0.0.1',logical_model='chat')
        keyed=NS(key=NS(id=7),user=NS(id=7),client_ip=web.client_ip,logical_model='chat')
        self.assertNotEqual(sticky_key(web),sticky_key(keyed))

    def test_payload_limits(self):
        for fields in [dict(max_tokens=4097),dict(messages=[dict(role='tool',content='test')]),dict(stream='true'),dict(messages=[dict(role='user',content='中'*16000)]*100)]:
            body=dict(model='chat',messages=[dict(role='user',content='hello')]);body.update(fields)
            with self.assertRaises(ValidationError):ChatTestInput.model_validate(body)

    def test_multimodal_content_validation(self):
        import base64
        image='data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()
        pdf='data:application/pdf;base64,'+base64.b64encode(b'%PDF-1.4 fixture').decode()
        parts=[dict(type='text',text='analyze'),dict(type='image_url',image_url=dict(url=image)),dict(type='file',file=dict(filename='test.pdf',file_data=pdf))]
        body=ChatTestInput(model='vision',messages=[dict(role='user',content=parts)])
        self.assertEqual(body.model_dump()['messages'][0]['content'],parts)
        invalid=[dict(role='assistant',content=parts),dict(role='user',content=[]),dict(role='user',content=[dict(type='image_url',image_url=dict(url='https://example.com/image.png'))]),dict(role='user',content=[dict(type='file',file=dict(filename='../bad.pdf',file_data=pdf))]),dict(role='user',content=[dict(type='file',file=dict(filename='test.pdf',file_data=pdf+'!'))]),dict(role='user',content=[dict(type='image_url',image_url=dict(url='data:image/png;base64,'+base64.b64encode(b'not png').decode()))])]
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValidationError):ChatTestInput(model='vision',messages=[item])
        large='data:application/pdf;base64,'+base64.b64encode(b'%PDF-'+b'x'*600000).decode()
        with self.assertRaises(ValidationError):ChatTestInput(model='vision',messages=[dict(role='user',content=[dict(type='file',file=dict(filename='test.pdf',file_data=large))]*2)])

    async def test_text_models_reject_attachments_before_upstream(self):
        body=ChatTestInput(model='chat',messages=[dict(role='user',content=[dict(type='text',text='file contents')])])
        db=NS(get=AsyncMock(return_value=NS(model_type='text')))
        with patch('app.api.admin.chat_test.pipeline.run',AsyncMock()) as run:
            with self.assertRaises(APIError) as caught:await completion(body,self.request(),NS(),db)
            self.assertEqual(caught.exception.detail['code'],'MULTIMODAL_MODEL_REQUIRED');run.assert_not_awaited()

    async def test_multimodal_pipeline_preserves_media(self):
        import base64
        from app.providers.translator import chat_to_messages
        pdf='data:application/pdf;base64,'+base64.b64encode(b'%PDF-1.4 fixture').decode()
        parts=[dict(type='text',text='analyze'),dict(type='file',file=dict(filename='report.pdf',file_data=pdf))]
        body=ChatTestInput(model='vision',messages=[dict(role='user',content=parts)])
        with patch('app.api.admin.chat_test.pipeline.run',AsyncMock()) as run:
            await completion(body,self.request(),NS(),NS(get=AsyncMock(return_value=NS(model_type='multimodal'))))
        payload=run.call_args.args[4]
        self.assertEqual(payload['messages'][0]['content'],parts)
        converted=chat_to_messages(payload)['messages'][0]['content'][1]
        self.assertEqual(converted['type'],'document');self.assertEqual(converted['source']['media_type'],'application/pdf')
        self.assertEqual(converted['source']['data'],pdf.split(',',1)[1]);self.assertEqual(converted['title'],'report.pdf')

    def test_media_compliance_still_fails_closed(self):
        from app.gateway.compliance import content
        with self.assertRaises(APIError) as caught:content(NS(operation='chat',payload={'messages':[{'content':[{'type':'file','file':{'filename':'a.pdf'}}]}]}))
        self.assertEqual(caught.exception.detail['code'],'COMPLIANCE_MEDIA_UNSUPPORTED')
