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
