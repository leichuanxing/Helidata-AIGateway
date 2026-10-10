"""Regression tests for request-target isolation and bounded log redaction."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from starlette.requests import Request
from app.core.exceptions import APIError
from app.gateway.authentication import authenticate
from app.services.body_logs import redact

class SecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_poisoned_host_never_selects_web_session_on_gateway(self):
        scope={'type':'http','method':'POST','path':'/v1/chat/completions',
               'headers':[(b'host',b'evil/api/admin/chat-test/completions?ignored='),
                          (b'authorization',b'Bearer web-token')],'state':{}}
        with patch('app.core.dependencies.current_user',AsyncMock()) as session:
            with self.assertRaises(APIError) as caught:await authenticate(Request(scope),NS())
            self.assertEqual(caught.exception.detail['code'],'INVALID_API_KEY')
            session.assert_not_called()

    async def test_poisoned_host_cannot_switch_admin_chat_to_api_key(self):
        scope={'type':'http','method':'POST','path':'/api/admin/chat-test/completions',
               'headers':[(b'host',b'evil/v1/chat/completions?ignored='),
                          (b'authorization',b'Bearer sk-hd-' + b'a'*43)],'state':{}}
        with patch('app.core.dependencies.current_user',AsyncMock(side_effect=APIError(401,'SESSION_INVALID','invalid'))) as session:
            with self.assertRaises(APIError) as caught:await authenticate(Request(scope),NS())
            self.assertEqual(caught.exception.detail['code'],'SESSION_INVALID')
            session.assert_awaited_once()

    async def test_password_change_throttle_prevents_verification(self):
        from app.api.auth.routes import change_password
        request=Request({'type':'http','path':'/api/auth/change-password','headers':[], 'client':('127.0.0.1',1)})
        with patch('app.api.auth.routes.redis_client.eval',AsyncMock(return_value=0)), patch('app.api.auth.routes.verify_password',AsyncMock()) as verify:
            with self.assertRaises(APIError) as caught:await change_password(NS(old_password='guess'),request,NS(),NS(id=1),NS())
            self.assertEqual(caught.exception.status_code,429);verify.assert_not_called()

    async def test_password_change_throttle_fails_closed_if_redis_down(self):
        from app.api.auth.routes import change_password
        request=Request({'type':'http','path':'/api/auth/change-password','headers':[]})
        with patch('app.api.auth.routes.redis_client.eval',AsyncMock(side_effect=RuntimeError('offline'))), patch('app.api.auth.routes.verify_password',AsyncMock()) as verify:
            with self.assertRaises(APIError) as caught:await change_password(NS(),request,NS(),NS(id=1),NS())
            self.assertEqual(caught.exception.status_code,503);verify.assert_not_called()

    async def test_incorrect_old_password_is_audited_without_mutating_credentials(self):
        from app.api.auth.routes import change_password
        request=Request({'type':'http','path':'/api/auth/change-password','headers':[], 'client':('127.0.0.1',1)})
        user=NS(id=1,password_hash='old-hash');db=NS(refresh=AsyncMock(),commit=AsyncMock())
        with patch('app.api.auth.routes.redis_client.eval',AsyncMock(return_value=1)), patch('app.api.auth.routes.verify_password',AsyncMock(return_value=False)), patch('app.api.auth.routes.hash_password',AsyncMock()) as hashing, patch('app.api.auth.routes.audit') as audit:
            with self.assertRaises(APIError) as caught:await change_password(NS(old_password='wrong'),request,NS(),user,db)
            self.assertEqual(caught.exception.status_code,400);self.assertEqual(user.password_hash,'old-hash')
            hashing.assert_not_called();db.commit.assert_awaited_once();self.assertEqual(audit.call_args.kwargs['result'],'failure')

    async def test_successful_password_change_still_revokes_sessions(self):
        from app.api.auth.routes import change_password
        from starlette.responses import Response
        request=Request({'type':'http','path':'/api/auth/change-password','headers':[], 'client':('127.0.0.1',1)})
        user=NS(id=1,password_hash='old-hash');db=NS(refresh=AsyncMock(),commit=AsyncMock())
        with patch('app.api.auth.routes.redis_client.eval',AsyncMock(return_value=1)), patch('app.api.auth.routes.redis_client.delete',AsyncMock()), patch('app.api.auth.routes.verify_password',AsyncMock(side_effect=[True,False])), patch('app.api.auth.routes.hash_password',AsyncMock(return_value='new-hash')), patch('app.api.auth.routes.revoke_all',AsyncMock()) as revoke, patch('app.api.auth.routes.audit'):
            await change_password(NS(old_password='old',new_password='new'),request,Response(),user,db)
            self.assertEqual(user.password_hash,'new-hash');revoke.assert_awaited_once_with(db,user);db.commit.assert_awaited_once()

    async def test_unauthenticated_payload_never_runs_custom_redaction(self):
        from contextlib import asynccontextmanager
        from app.gateway.pipeline import GatewayPipeline
        @asynccontextmanager
        async def lease():yield
        request=Request({'type':'http','method':'POST','path':'/v1/chat/completions','headers':[],
                         'client':('127.0.0.1',1),'state':{'request_id':'req_security_test'}})
        with patch('app.gateway.pipeline.preparation.acquire',lease), patch('app.gateway.pipeline.authentication.authenticate',AsyncMock(side_effect=APIError(401,'INVALID_API_KEY','invalid'))), patch('app.gateway.pipeline.body_logs.begin') as begin, patch('app.gateway.pipeline.compliance.finalize',AsyncMock()), patch('app.gateway.pipeline.call_log.write',AsyncMock()):
            with self.assertRaises(APIError):await GatewayPipeline().run(request,NS(in_transaction=lambda:False),'chat','test',{'messages':[]})
            begin.assert_not_called()

    def test_initial_password_handoff_is_private_and_never_overwrites(self):
        import tempfile,os
        from pathlib import Path
        from app.services.bootstrap import publish_initial_password
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'initial.txt'
            with patch('app.services.bootstrap.INITIAL_PASSWORD_FILE',target):
                publish_initial_password('example-only-secret')
                self.assertEqual(target.stat().st_mode & 0o777,0o600)
                with self.assertRaises(FileExistsError):publish_initial_password('replacement')
                self.assertEqual(target.read_text().strip(),'example-only-secret')

    def test_redaction_has_whole_document_deadline_and_fails_closed(self):
        with patch('app.services.body_logs.monotonic',side_effect=[0,.1,.1,.1,.1]):
            output=redact(['private prompt','sk-sensitive-key','private output'],{})
        self.assertEqual(output,['[REDACTION_TIMEOUT]']*3)

    def test_regular_redaction_preserves_shape_without_secrets(self):
        output=redact({'api_key':'private','messages':[{'content':'Bearer abc123 and sk-private-key'}]}, {})
        self.assertEqual(output['api_key'],'[REDACTED]')
        self.assertNotIn('abc123',str(output));self.assertNotIn('private-key',str(output))

if __name__=='__main__':unittest.main()
