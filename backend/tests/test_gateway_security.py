import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from starlette.requests import Request
from pydantic import ValidationError
from app.schemas.gateway_security import SecurityPolicy,AccessRule,KeyBinding,Ban
from app.services import gateway_security as security
from app.core.exceptions import APIError

def request(path='/v1/models',peer='192.0.2.10',headers=()):
    return Request({'type':'http','method':'GET','path':path,'headers':[(k.encode(),v.encode()) for k,v in headers],'client':(peer,42),'state':{}})

class PolicyTests(unittest.TestCase):
    def test_default_admin_access_unrestricted(self):
        self.assertFalse(SecurityPolicy().admin_access.enabled)
        self.assertIsNone(security.rejection('203.0.113.10','admin',SecurityPolicy()))
    def test_invalid_and_empty_allowlist_rejected(self):
        for values in [{'addresses':['not-ip']},{'enabled':True,'mode':'whitelist'}]:
            with self.assertRaises(ValidationError):AccessRule(**values)
    def test_single_ip_and_cidr_canonicalized(self):
        self.assertEqual(AccessRule(addresses=['192.0.2.5','192.0.2.17/24']).addresses,['192.0.2.5/32','192.0.2.0/24'])
    def test_ipv6_and_mapped_peer(self):
        self.assertTrue(security.matches('2001:db8::5',['2001:db8::/32']))
        self.assertTrue(security.matches('::ffff:192.0.2.5',['192.0.2.0/24']))
    def test_untrusted_forward_headers_ignored(self):
        self.assertEqual(security.resolve_ip('192.0.2.5','127.0.0.1','127.0.0.1',[]),'192.0.2.5')
    def test_proxy_chain_stops_at_untrusted_hop(self):
        self.assertEqual(security.resolve_ip('10.0.0.2','127.0.0.1, 192.0.2.4, 10.0.0.1',trusted=['10.0.0.0/24']),'192.0.2.4')
    def test_invalid_chain_falls_back_to_peer(self):
        self.assertEqual(security.resolve_ip('10.0.0.2','192.0.2.4, bad',trusted=['10.0.0.0/24']),'10.0.0.2')
    def test_trusted_real_ip(self):
        self.assertEqual(security.resolve_ip('10.0.0.2',real='192.0.2.4',trusted=['10.0.0.0/24']),'192.0.2.4')
    def test_external_peer_cannot_forge_private_header(self):
        self.assertEqual(security.client(request(headers=[('x-gateway-peer-ip','127.0.0.1')]),SecurityPolicy()),'192.0.2.10')
    def test_admin_and_api_separate(self):
        cfg=SecurityPolicy(admin_access=AccessRule(enabled=True,mode='whitelist',addresses=['192.0.2.0/24']))
        self.assertEqual(security.rejection('203.0.113.5','admin',cfg),'WHITELIST_REJECTED')
        self.assertIsNone(security.rejection('203.0.113.5','api',cfg))
    def test_blacklist_overrides_scoped_allowlist(self):
        cfg=SecurityPolicy(global_access=AccessRule(enabled=True,addresses=['192.0.2.5']),admin_access=AccessRule(enabled=True,mode='whitelist',addresses=['192.0.2.0/24']))
        self.assertEqual(security.rejection('192.0.2.5','admin',cfg),'BLACKLIST_HIT')
    def test_ban_priority_and_expiry(self):
        cfg=SecurityPolicy(bans=[Ban(address='192.0.2.0/24',expires_at=datetime.now(timezone.utc)-timedelta(seconds=1))])
        self.assertIsNone(security.rejection('192.0.2.5','admin',cfg))
        cfg.bans[0].expires_at=None
        self.assertEqual(security.rejection('192.0.2.5','admin',cfg),'IP_BANNED')
    def test_current_admin_cannot_be_locked_out(self):
        cfg=SecurityPolicy(admin_access=AccessRule(enabled=True,mode='whitelist',addresses=['203.0.113.0/24']))
        with self.assertRaises(APIError) as caught:security.prevent_lockout(request(),cfg)
        self.assertEqual(caught.exception.detail['code'],'ADMIN_IP_LOCKOUT')
    def test_proxy_change_lockout_checked(self):
        req=request(peer='127.0.0.1',headers=[('x-gateway-peer-ip','10.0.0.1'),('x-forwarded-for','192.0.2.10')])
        cfg=SecurityPolicy(trusted_proxies=['10.0.0.1'],admin_access=AccessRule(enabled=True,mode='whitelist',addresses=['10.0.0.0/24']))
        with self.assertRaises(APIError):security.prevent_lockout(req,cfg)
    def test_duplicate_key_and_empty_binding_rejected(self):
        with self.assertRaises(ValidationError):KeyBinding(key_id=1,addresses=[])
        with self.assertRaises(ValidationError):SecurityPolicy(key_bindings=[KeyBinding(key_id=1,addresses=['192.0.2.1'])]*2)
    def test_all_internet_trust_rejected(self):
        with self.assertRaises(ValidationError):SecurityPolicy(trusted_proxies=['0.0.0.0/0'])

class EnforcementTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_scope_and_cached_client_updated(self):
        req=request(peer='127.0.0.1',headers=[('x-gateway-peer-ip','192.0.2.10'),('x-forwarded-for','127.0.0.1')])
        self.assertEqual(req.client.host,'127.0.0.1')
        with patch.object(security,'policy',SecurityPolicy()):await security.enforce(req)
        self.assertEqual(req.client.host,'192.0.2.10')
    async def test_deny_records_security_event(self):
        req=request('/api/auth/login')
        cfg=SecurityPolicy(admin_access=AccessRule(enabled=True,addresses=['192.0.2.0/24']))
        with patch.object(security,'policy',cfg),patch.object(security,'event',AsyncMock()) as log:
            with self.assertRaises(APIError):await security.enforce(req)
            log.assert_awaited_once_with(req,'BLACKLIST_HIT')
    async def test_key_binding_enforced_even_without_api_allowlist(self):
        req=request();cfg=SecurityPolicy(key_bindings=[KeyBinding(key_id=7,addresses=['203.0.113.0/24'])])
        with patch.object(security,'policy',cfg),patch.object(security,'event',AsyncMock()) as log:
            with self.assertRaises(APIError) as caught:await security.enforce_key(req,NS(id=7))
            self.assertEqual(caught.exception.detail['code'],'API_KEY_IP_MISMATCH');log.assert_awaited_once()
    async def test_reauthentication_does_not_charge_rate_twice(self):
        req=request()
        with patch.object(security.redis_client,'eval',AsyncMock(return_value=[1,60])) as redis:
            await security.rate(req,'key',7,2);await security.rate(req,'key',7,2)
            redis.assert_awaited_once()
    async def test_rate_limit_retry_header_and_log(self):
        req=request()
        with patch.object(security.redis_client,'eval',AsyncMock(return_value=[3,12])),patch.object(security,'event',AsyncMock()) as log:
            with self.assertRaises(APIError) as caught:await security.rate(req,'key',7,2)
            self.assertEqual(caught.exception.status_code,429);self.assertEqual(caught.exception.headers['Retry-After'],'12');log.assert_awaited_once()
    async def test_disabled_rate_never_contacts_redis(self):
        with patch.object(security.redis_client,'eval',AsyncMock()) as redis:
            await security.rate(request(),'ip','192.0.2.10',0);redis.assert_not_called()

class MiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_backend_admin_and_static_guard_both_deny(self):
        import httpx
        from app.main import app
        cfg=SecurityPolicy(admin_access=AccessRule(enabled=True,addresses=['192.0.2.0/24']))
        transport=httpx.ASGITransport(app=app,client=('192.0.2.10',42))
        with patch.object(security,'policy',cfg),patch.object(security,'event',AsyncMock()) as log:
            async with httpx.AsyncClient(transport=transport,base_url='http://gateway') as http:
                for path in ['/api/admin/gateway-security','/api/auth/login','/internal/gateway-security/admin']:
                    response=await http.get(path)
                    self.assertEqual(response.status_code,403)
                    self.assertEqual(response.json()['error']['code'],'BLACKLIST_HIT')
            self.assertEqual(log.await_count,3)
    async def test_default_static_guard_allows_and_admin_still_requires_login(self):
        import httpx
        from app.main import app
        transport=httpx.ASGITransport(app=app,client=('203.0.113.10',42))
        with patch.object(security,'policy',SecurityPolicy()):
            async with httpx.AsyncClient(transport=transport,base_url='http://gateway') as http:
                self.assertEqual((await http.get('/internal/gateway-security/admin')).status_code,200)
                self.assertEqual((await http.get('/api/admin/gateway-security')).status_code,401)
    async def test_api_rate_errors_have_retry_after(self):
        import httpx
        from app.main import app
        transport=httpx.ASGITransport(app=app,client=('192.0.2.10',42))
        with patch.object(security,'policy',SecurityPolicy(ip_rpm=2)),patch.object(security.redis_client,'eval',AsyncMock(return_value=[3,24])),patch.object(security,'event',AsyncMock()):
            async with httpx.AsyncClient(transport=transport,base_url='http://gateway') as http:
                response=await http.get('/v1/models')
                self.assertEqual(response.status_code,429)
                self.assertEqual(response.headers['retry-after'],'24')
    async def test_authenticated_admin_self_lockout_rejected_without_write(self):
        from app.api.admin.gateway_security import save
        db=NS(get=AsyncMock(return_value=None),commit=AsyncMock())
        cfg=SecurityPolicy(admin_access=AccessRule(enabled=True,mode='whitelist',addresses=['203.0.113.0/24']))
        with patch('app.api.admin.model_mappings.config_lock',AsyncMock()):
            with self.assertRaises(APIError) as error:await save(cfg,request(),NS(id=1),db)
            self.assertEqual(error.exception.detail['code'],'ADMIN_IP_LOCKOUT')
            db.commit.assert_not_awaited()

class LoginSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_threshold_records_failure_and_lock(self):
        from app.api.auth.routes import login
        from starlette.responses import Response
        req=request('/api/auth/login')
        db=NS(scalar=AsyncMock(return_value=None),commit=AsyncMock())
        with patch('app.api.auth.routes.redis_client.eval',AsyncMock(side_effect=[1,1])),patch('app.api.auth.routes.verify_password',AsyncMock(return_value=False)),patch('app.api.auth.routes.audit'),patch.object(security,'event',AsyncMock()) as event:
            with self.assertRaises(APIError) as error:await login(NS(username='test-user',password='invalid'),req,Response(),db)
            self.assertEqual(error.exception.status_code,401)
            self.assertEqual([call.args[1] for call in event.await_args_list],['LOGIN_FAILED','ACCOUNT_LOCKED'])
    async def test_locked_account_never_verifies_password(self):
        from app.api.auth.routes import login
        from starlette.responses import Response
        req=request('/api/auth/login')
        db=NS(scalar=AsyncMock())
        with patch('app.api.auth.routes.redis_client.eval',AsyncMock(return_value=0)),patch('app.api.auth.routes.verify_password',AsyncMock()) as verify,patch.object(security,'event',AsyncMock()) as event:
            with self.assertRaises(APIError) as error:await login(NS(username='test-user',password='invalid'),req,Response(),db)
            self.assertEqual(error.exception.status_code,429);verify.assert_not_awaited();db.scalar.assert_not_awaited()
            event.assert_awaited_once_with(req,'ACCOUNT_LOCKED')

class SectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_patch_preserves_other_sections_and_latest_login_settings(self):
        from app.api.admin.gateway_security import save_section
        from app.schemas.gateway_security import SecuritySectionPatch
        from app.core.config import get_settings
        existing=SecurityPolicy(revision=4,ip_rpm=100,login_max_attempts=3)
        db=NS(get=AsyncMock(return_value=NS(value=existing.model_dump(mode='json'))))
        body=SecuritySectionPatch(revision=4,section='admin_access',values={'admin_access':{'enabled':False,'mode':'whitelist','addresses':['192.0.2.1']}})
        with patch('app.api.admin.model_mappings.config_lock',AsyncMock()),patch('app.api.admin.gateway_security.save',AsyncMock(return_value={'data':'saved'})) as write:
            await save_section(body,request(),NS(id=1),db)
            selected=write.await_args.args[0]
            self.assertEqual(selected.ip_rpm,100)
            self.assertEqual(selected.login_max_attempts,get_settings().security.login_max_attempts)
            self.assertEqual(selected.admin_access.addresses,['192.0.2.1/32'])
    async def test_patch_cannot_write_another_tab(self):
        from app.api.admin.gateway_security import save_section
        from app.schemas.gateway_security import SecuritySectionPatch
        db=NS(get=AsyncMock(return_value=None))
        with patch('app.api.admin.model_mappings.config_lock',AsyncMock()),patch('app.api.admin.gateway_security.save',AsyncMock()) as write:
            with self.assertRaises(APIError) as error:await save_section(SecuritySectionPatch(revision=0,section='rate',values={'admin_access':{'enabled':False}}),request(),NS(id=1),db)
            self.assertEqual(error.exception.detail['code'],'SECURITY_SECTION_INVALID');write.assert_not_awaited()
    async def test_patch_rejects_stale_revision(self):
        from app.api.admin.gateway_security import save_section
        from app.schemas.gateway_security import SecuritySectionPatch
        db=NS(get=AsyncMock(return_value=NS(value=SecurityPolicy(revision=2).model_dump(mode='json'))))
        with patch('app.api.admin.model_mappings.config_lock',AsyncMock()):
            with self.assertRaises(APIError) as error:await save_section(SecuritySectionPatch(revision=1,section='rate',values={'ip_rpm':100}),request(),NS(id=1),db)
            self.assertEqual(error.exception.status_code,409)
    async def test_address_validation_normalizes_duplicates(self):
        from app.api.admin.gateway_security import validate_addresses
        from app.schemas.gateway_security import AddressValidation
        result=await validate_addresses(AddressValidation(addresses=['192.0.2.10','192.0.2.10/32','192.0.2.17/24']),request(),NS(id=1))
        self.assertEqual(result['data']['addresses'],['192.0.2.10/32','192.0.2.0/24'])
        self.assertTrue(result['data']['includes_current_ip'])
    async def test_proxy_validation_rejects_full_network(self):
        from app.api.admin.gateway_security import validate_addresses
        from app.schemas.gateway_security import AddressValidation
        with self.assertRaises(APIError):await validate_addresses(AddressValidation(addresses=['::/0'],purpose='proxies'),request(),NS(id=1))
    async def test_log_detail_cannot_read_other_audit_logs(self):
        from app.api.admin.gateway_security import log_detail
        db=NS(get=AsyncMock(return_value=NS(resource_type='user')))
        with self.assertRaises(APIError) as error:await log_detail(1,NS(id=1),db)
        self.assertEqual(error.exception.status_code,404)

class IndependentSaveTests(unittest.IsolatedAsyncioTestCase):
    async def test_unrelated_tab_save_does_not_change_system_settings_revision(self):
        from app.api.admin.gateway_security import save
        cfg=SecurityPolicy()
        row=NS(value=cfg.model_dump(mode='json'))
        stored={'revision':10,'security':{'login_max_attempts':5,'login_lock_seconds':900}}
        operation_row=NS(value=stored)
        db=NS(get=AsyncMock(side_effect=[row,operation_row]),commit=AsyncMock())
        with patch('app.api.admin.model_mappings.config_lock',AsyncMock()),patch('app.api.admin.gateway_security.operations.document',AsyncMock(return_value=stored)),patch('app.api.admin.gateway_security.operations.apply'),patch('app.api.admin.gateway_security.audit'),patch.object(security,'policy',cfg):
            await save(cfg,request(),NS(id=1),db)
            self.assertEqual(operation_row.value['revision'],10)
            self.assertEqual(row.value['revision'],1)
