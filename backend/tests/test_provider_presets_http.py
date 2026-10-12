"""Real CRUD of every catalog plan; disposable container only, no upstream calls."""
import os
import unittest
from pathlib import Path
from uuid import uuid4
import httpx


@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','disposable container only')
class ProviderCatalogHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_catalog_plans_save_and_read_back(self):
        identity=os.environ.get('AUDIT_CONTAINER_ID','')
        self.assertGreaterEqual(len(identity),12)
        self.assertEqual(os.environ.get('HOSTNAME','')[:12],identity[:12])
        password=Path('/data/config/audit-password.txt').read_text().strip()
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8000',timeout=20) as client:
            login=await client.post('/api/auth/login',json={'username':'admin','password':password})
            self.assertEqual(login.status_code,200)
            client.headers['Authorization']='Bearer '+login.json()['data']['access_token']
            catalog=(await client.get('/api/admin/providers/types')).json()['data']
            self.assertEqual(len(catalog),20)
            count=0
            for entry in catalog:
                for plan_name,plan in entry['account_types'].items():
                    name='preset-'+uuid4().hex[:16]
                    protocols=[p for p in plan.get('supported_protocols',entry['supported_protocols']) if p in ('openai-completions','openai-responses','anthropic-messages')]
                    route=protocols[0]
                    urls={**entry['protocol_urls'],**plan.get('protocol_urls',{})}
                    separate=any(urls.get(p,plan['base_url'])!=plan['base_url'] for p in protocols)
                    configs={p:{'path_prefix':'','auth_type':'x-api-key' if p=='anthropic-messages' else 'bearer',**({'api_url':urls.get(p,plan['base_url'])} if separate else {})} for p in protocols}
                    model=name+'-model'
                    payload={'name':name,'provider_type':entry['code'],'account_type':plan_name,
                        'protocol':'anthropic' if route=='anthropic-messages' else 'openai',
                        'protocol_type':'text','protocol_config':configs,
                        'base_url':plan['base_url'],'api_key':'audit-private-key',
                        'priority':0,'max_concurrency':10,'status':'disabled','remark':'isolated catalog regression',
                        'model_mappings':[{'logical_model':model,'upstream_model':'fixture','model_type':'text','status':'enabled'}],
                        'default_test_model':model}
                    response=await client.post('/api/admin/providers',json=payload)
                    self.assertEqual(response.status_code,201,entry['code']+' / '+plan_name)
                    ident=response.json()['data']['id']
                    saved=(await client.get(f'/api/admin/providers/{ident}')).json()['data']
                    for field in ('base_url','priority','max_concurrency','account_type','status','default_test_model','remark'):
                        self.assertEqual(saved[field],payload[field])
                    self.assertTrue(saved['has_api_key']);self.assertNotIn('audit-private-key',str(saved))
                    self.assertEqual(saved['protocol_config'],configs)
                    stale=await client.patch(f'/api/admin/providers/{ident}',json={'status':'enabled','expected_config_version':saved['config_version']+1})
                    self.assertEqual(stale.status_code,409)
                    enabled=await client.patch(f'/api/admin/providers/{ident}',json={'status':'enabled','expected_config_version':saved['config_version']})
                    self.assertEqual(enabled.status_code,200)
                    for field,value in [('max_concurrency',0),('priority',-1),('proxy','http://proxy.example/path'),('default_test_model','missing-model')]:
                        invalid=await client.patch(f'/api/admin/providers/{ident}',json={field:value})
                        self.assertEqual(invalid.status_code,422)
                    self.assertEqual((await client.delete(f'/api/admin/providers/{ident}')).status_code,200)
                    count+=1
            print('PASS real HTTP catalog: 20 providers,',count,'plans created/read/deleted; invalid fields rejected; no upstream requests')
