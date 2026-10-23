"""Dedicated disposable HTTP regression for independent per-rule smart-route modes."""
import os,json,unittest
from pathlib import Path
from uuid import uuid4
import httpx

@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1' and os.environ.get('INDEPENDENT_MODE_TEST')=='1','dedicated disposable mode test only')
class IndependentRouteModeTests(unittest.IsolatedAsyncioTestCase):
 async def test_rule_modes_are_independent_and_global_switch_is_removed(self):
  self.assertEqual(os.environ['HOSTNAME'][:12],os.environ['AUDIT_CONTAINER_ID'][:12])
  from app.main import app
  from app.core.database import engine
  from app.core.redis import redis_client
  from app.services import operations_settings,gateway_security
  await operations_settings.load();await gateway_security.load()
  self.addAsyncCleanup(engine.dispose);self.addAsyncCleanup(redis_client.aclose)
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as client:
   login=await client.post('/api/auth/login',json={'username':'admin','password':Path('/data/config/audit-password.txt').read_text().strip()})
   self.assertEqual(login.status_code,200);client.headers['Authorization']='Bearer '+login.json()['data']['access_token'];client.headers['X-CSRF-Token']=client.cookies.get('hd_csrf','')
   async def api(method,path,data=None,status=200):
    r=await client.request(method,'/api/'+path,json=data);self.assertEqual(r.status_code,status,r.text[:500]);return r.json()
   prefix='unified-'+uuid4().hex[:8]
   names=[prefix+'simple',prefix+'complex',prefix+'embedding'];groups=[]
   for i,name in enumerate(names):
    await api('POST','admin/providers',{'name':name,'provider_type':'custom_openai','protocol':'openai','protocol_type':'vector' if i==2 else 'text','base_url':'http://127.0.0.1:1/v1','api_key':'fixture','model_mappings':[{'logical_model':name,'upstream_model':name,'model_type':'embedding' if i==2 else 'text'}]},201)
    if i<2:groups.append((await api('POST','admin/model-groups',{'name':name,'protocol_type':'text','logical_models':[name]},201))['data']['id'])
   vector={'embedding_model':names[2],'simple_model_group':groups[0],'complex_model_group':groups[1]}
   decision={'decision_provider':'aliyun','decision_service_url':'https://decision.example/systemone','decision_api_key':'fixture','decision_fallback_group':groups[0],'decision_targets':[{'name':'simple','description':'simple tasks','model_group_id':groups[0]},{'name':'complex','description':'complex tasks','model_group_id':groups[1]}]}
   model={'virtual_model':prefix+'one','route_mode':'model','status':'enabled',**vector,**decision}
   local={'virtual_model':prefix+'two','route_mode':'vector','status':'enabled',**vector}
   one=(await api('POST','admin/smart-route/configs',model,201))['data'];two=(await api('POST','admin/smart-route/configs',local,201))['data']
   async def modes():
    return {c['id']:c for c in (await api('GET','admin/smart-route/configs'))['data']}
   initial=await modes();self.assertEqual(initial[one['id']]['route_mode'],'model');self.assertEqual(initial[two['id']]['route_mode'],'vector')
   from app.core.database import session_factory
   from app.models.user import SystemSetting
   async with session_factory.begin() as db:db.add(SystemSetting(key='smart_route_mode',value='vector'))
   await api('PUT','admin/smart-route/configs/'+str(two['id']),{**local,**decision,'route_mode':'model','expected_updated_at':two['updated_at']})
   after=await modes();self.assertEqual(after[one['id']],initial[one['id']]);self.assertEqual(after[two['id']]['route_mode'],'model')
   await api('PUT','admin/smart-route/configs/'+str(one['id']),{**model,'route_mode':'vector','expected_updated_at':one['updated_at']})
   final=await modes();self.assertEqual(final[one['id']]['route_mode'],'vector');self.assertEqual(final[two['id']],after[two['id']]);self.assertEqual(final[one['id']]['decision_targets'],initial[one['id']]['decision_targets'])
   await api('PUT','admin/smart-route/configs/'+str(one['id']),{**model,'expected_updated_at':one['updated_at']},409)
   await api('POST','admin/smart-route/configs',{**model,'virtual_model':prefix+'three'},201)
   await api('POST','admin/smart-route/mode',{'mode':'vector'},404)
   await api('POST','admin/smart-route/configs',{'virtual_model':prefix+'invalid','route_mode':'model'},422)
