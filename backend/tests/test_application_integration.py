"""Real HTTP management flow, strictly for a disposable offline container.

Requires AUDIT_DISPOSABLE=1; creates records and changes test administrator
credentials. Never enable against production. No external model calls.
"""
import os
import asyncio
import secrets
import unittest
from pathlib import Path
from uuid import uuid4
import httpx


@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','disposable container only')
class ApplicationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_management_security_and_compliance_flow(self):
        self.assertGreaterEqual(len(os.environ.get('AUDIT_CONTAINER_ID','')),12)
        self.assertEqual(os.environ.get('HOSTNAME','')[:12],os.environ.get('AUDIT_CONTAINER_ID','')[:12],
                         'must explicitly identify disposable container')
        name='audit-'+uuid4().hex[:10]
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8000',timeout=20) as c:
            async def call(method,path,status=200,**kwargs):
                response=await c.request(method,path,**kwargs)
                self.assertEqual(response.status_code,status,f'{method} {path}: {response.status_code}')
                return response.json().get('data')
            password_file=Path('/data/config/audit-password.txt')
            password=password_file.read_text().strip() if password_file.exists() else Path('/data/config/initial-admin-password.txt').read_text().strip()
            data=await call('POST','/api/auth/login',json={'username':'admin','password':password})
            c.headers['Authorization']='Bearer '+data['access_token']
            if data['user']['must_change_password']:
                new=secrets.token_urlsafe(24)+'Aa1!'
                await call('POST','/api/auth/change-password',json={'old_password':password,'new_password':new})
                password_file.write_text(new);password_file.chmod(0o600)
                data=await call('POST','/api/auth/login',json={'username':'admin','password':new})
                c.headers['Authorization']='Bearer '+data['access_token']
            endpoints=['dashboard','chat-test/models','providers','model-groups','users','user-groups',
                       'call-logs','call-logs/options','usage','usage/options','settings?include_assets=false',
                       'settings/system-status','gateway-security','gateway-security/logs','smart-route/configs',
                       'smart-route/logs','smart-route/statistics',
                       'compliance/words','compliance/samples','compliance/policies','compliance/logs','backups']
            for path in endpoints:await call('GET','/api/admin/'+path)
            await call('GET','/api/portal/api-keys')
            async with httpx.AsyncClient(base_url=str(c.base_url)) as guest:
                for path in ('users','settings','gateway-security','providers'):
                    self.assertEqual((await guest.get('/api/admin/'+path)).status_code,401)
            provider={'name':name,'provider_type':'openai','protocol':'openai','base_url':'http://127.0.0.1:1/v1',
                      'api_key':'audit-private-key','model_mappings':[{'logical_model':name,'upstream_model':'fixture','model_type':'text'}]}
            created=await call('POST','/api/admin/providers',201,json=provider)
            self.assertNotIn('audit-private-key',str(created))
            await call('DELETE',f"/api/admin/providers/{created['id']}")
            recreated=await call('POST','/api/admin/providers',201,json=provider)
            changed={**provider,'protocol_type':'multimodal','model_mappings':[{'logical_model':name,'upstream_model':'fixture','model_type':'multimodal'}]}
            changed.pop('provider_type');changed.pop('protocol')
            await call('PATCH',f"/api/admin/providers/{recreated['id']}",json=changed)
            group={'name':name,'protocol_type':'multimodal','logical_models':[name]}
            simple=await call('POST','/api/admin/model-groups',201,json=group)
            complex_group=await call('POST','/api/admin/model-groups',201,json={**group,'name':name+'-complex'})
            embedding={**provider,'name':name+'-embed','protocol_type':'vector','protocol_config':{'openai-embeddings':{}},
                       'model_mappings':[{'logical_model':name+'-embed','upstream_model':'embed','model_type':'embedding'}]}
            await call('POST','/api/admin/providers',201,json=embedding)
            route=await call('POST','/api/admin/smart-route/configs',201,json={
                'virtual_model':name+'-virtual','embedding_model':name+'-embed',
                'simple_model_group':simple['id'],'complex_model_group':complex_group['id'],'status':'enabled'})
            await call('GET',f"/api/admin/smart-route/samples?config_id={route['id']}")
            await call('PUT',f"/api/admin/model-groups/{simple['id']}",json={**group,'description':'rename-neutral update'})
            await call('PUT',f"/api/admin/model-groups/{simple['id']}",400,json={**group,'logical_models':[]})
            await call('PUT',f"/api/admin/model-groups/{simple['id']}",400,json={**group,'status':'disabled'})
            policy=await call('POST','/api/admin/compliance/policies',json={'name':name,'status':'enabled','action':'block','models':[name,name+'-virtual']})
            blocked_text='审计阻断词'+name
            await call('POST','/api/admin/compliance/words',json={'pattern':blocked_text,'policy_id':policy['id']})
            for model in (name,name+'-virtual'):
                await call('POST','/api/admin/chat-test/completions',403,json={
                    'model':model,'messages':[{'role':'user','content':blocked_text}],'stream':False,'max_tokens':8})
            response=await c.post('/api/admin/chat-test/completions',json={
                'model':name,'messages':[{'role':'user','content':[{'type':'text','text':blocked_text},
                {'type':'image_url','image_url':{'url':'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='}}]}],
                'stream':False,'max_tokens':8})
            self.assertEqual(response.status_code,403)
            self.assertEqual(response.json()['error']['code'],'CONTENT_BLOCKED')
            key=await call('POST','/api/portal/api-keys',201,json={'name':name})
            listing=await call('GET','/api/portal/api-keys')
            self.assertNotIn(key['secret'],str(listing))
            security=await call('GET','/api/admin/gateway-security')
            # Proposed whitelist excludes the actual administrator; save must fail.
            await call('PATCH','/api/admin/gateway-security',400,json={'revision':security['policy']['revision'],
                       'section':'admin_access','values':{'admin_access':{'enabled':True,'mode':'whitelist','addresses':['192.0.2.1']}}})
            settings=await call('GET','/api/admin/settings?include_assets=false')
            await call('PATCH','/api/admin/settings',json={'revision':settings['revision'],'basic':{'timezone':'UTC'}})
            await call('PATCH','/api/admin/settings',409,json={'revision':settings['revision'],'basic':{'timezone':'UTC'}})
            self.assertEqual((await c.post('/api/auth/refresh')).status_code,403)
            user_group=await call('POST','/api/admin/user-groups',201,json={'name':name,'model_access':'selected','model_group_ids':[simple['id']]})
            user_password=secrets.token_urlsafe(20)+'Aa1!'
            user=await call('POST','/api/admin/users',201,json={'username':name,'password':user_password,'user_group_id':user_group['id']})
            async with httpx.AsyncClient(base_url=str(c.base_url)) as ordinary:
                login=await ordinary.post('/api/auth/login',json={'username':name,'password':user_password})
                self.assertEqual(login.status_code,200)
                ordinary.headers['Authorization']='Bearer '+login.json()['data']['access_token']
                replacement=secrets.token_urlsafe(20)+'Aa1!'
                changed=await ordinary.post('/api/auth/change-password',json={'old_password':user_password,'new_password':replacement})
                self.assertEqual(changed.status_code,200)
                login=await ordinary.post('/api/auth/login',json={'username':name,'password':replacement})
                ordinary.headers['Authorization']='Bearer '+login.json()['data']['access_token']
                for path in ('users','providers','settings','gateway-security','chat-test/models'):
                    self.assertEqual((await ordinary.get('/api/admin/'+path)).status_code,403)
                self.assertEqual((await ordinary.get('/api/portal/api-keys/'+str(key['key']['id']))).status_code,404)
                own=await ordinary.post('/api/portal/api-keys',json={'name':name})
                self.assertEqual(own.status_code,201)
                self.assertEqual((await ordinary.get('/api/portal/usage')).status_code,200)
            security=await call('GET','/api/admin/gateway-security')
            bound=await call('PATCH','/api/admin/gateway-security',json={'revision':security['policy']['revision'],'section':'api_access',
                'values':{'key_bindings':[{'key_id':key['key']['id'],'addresses':['192.0.2.1']}]}})
            async with httpx.AsyncClient(base_url=str(c.base_url),headers={'Authorization':'Bearer '+key['secret'],'X-Forwarded-For':'192.0.2.1','X-Real-IP':'192.0.2.1'}) as api_client:
                mismatch=await api_client.get('/v1/models')
                self.assertEqual(mismatch.status_code,403)
                self.assertEqual(mismatch.json()['error']['code'],'API_KEY_IP_MISMATCH')
            await call('PATCH','/api/admin/gateway-security',json={'revision':bound['policy']['revision'],'section':'api_access','values':{'key_bindings':[]}})
            security=await call('GET','/api/admin/gateway-security')
            limited=await call('PATCH','/api/admin/gateway-security',json={'revision':security['policy']['revision'],'section':'rate','values':{'key_rpm':2}})
            async with httpx.AsyncClient(base_url=str(c.base_url),headers={'Authorization':'Bearer '+key['secret']}) as api_client:
                self.assertEqual((await api_client.get('/v1/models')).status_code,200)
                self.assertEqual((await api_client.get('/v1/models')).status_code,200)
                throttled=await api_client.get('/v1/models')
                self.assertEqual(throttled.status_code,429)
                self.assertIn('Retry-After',throttled.headers)
            await call('PATCH','/api/admin/gateway-security',json={'revision':limited['policy']['revision'],'section':'rate','values':{'key_rpm':0}})
            async with httpx.AsyncClient(base_url=str(c.base_url)) as locked_user:
                for _ in range(5):
                    failure=await locked_user.post('/api/auth/login',json={'username':name,'password':'incorrect'})
                    self.assertEqual(failure.status_code,401)
                self.assertEqual((await locked_user.post('/api/auth/login',json={'username':name,'password':replacement})).status_code,429)
                await call('POST',f"/api/admin/users/{user['user']['id']}/unlock")
                self.assertEqual((await locked_user.post('/api/auth/login',json={'username':name,'password':replacement})).status_code,200)
            backup=await call('POST','/api/admin/backups',202)
            for _ in range(30):
                rows=await call('GET','/api/admin/backups')
                saved=next(row for row in rows['items'] if row['id']==backup['id'])
                if saved['status'] in ('ready','failed'):break
                await asyncio.sleep(1)
            self.assertEqual(saved['status'],'ready')
            download=await c.get('/api/admin/backups/'+backup['id']+'/download')
            self.assertEqual(download.status_code,200)
            import hashlib,io,tarfile,json
            self.assertEqual(hashlib.sha256(download.content).hexdigest(),saved['sha256'])
            with tarfile.open(fileobj=io.BytesIO(download.content)) as archive:
                self.assertIn('database.dump',archive.getnames())
                self.assertIn('config/provider-encryption.key',archive.getnames())
                self.assertTrue(json.load(archive.extractfile('manifest.json'))['contains_secrets'])
            print('PASS real HTTP: 23 module reads, auth boundaries, provider delete/recreate/type change, model groups/route link, real compliance block, settings revision, whitelist lockout guard, CSRF')
            print('PASS real HTTP: ordinary user authorization, API Key ownership/IP binding, spoofed proxy headers, API rate/Retry-After, login lock/unlock, queued backup download and SHA256')
