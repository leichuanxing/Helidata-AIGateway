"""Disposable-only SQL/Redis/ASGI integration with a real loopback System One server.
No vendor is contacted. ASGI exercises the real auth/permission/metered pipeline.
"""
import asyncio,json,os,threading,time,unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from uuid import uuid4
import httpx

@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','disposable container only')
class ModelDecisionHTTPTests(unittest.IsolatedAsyncioTestCase):
 async def test_persistence_modes_choices_fallback_permissions_logs_and_concurrency(self):
  self.assertEqual(os.environ['HOSTNAME'][:12],os.environ['AUDIT_CONTAINER_ID'][:12])
  from app.main import app
  from app.core.database import session_factory,engine
  from app.core.redis import redis_client
  from app.services import model_decision,operations_settings,gateway_security
  from app.models.routing import RouteConfig
  from app.services.provider_crypto import decrypt_secret
  await operations_settings.load();await gateway_security.load()
  self.addAsyncCleanup(engine.dispose);self.addAsyncCleanup(redis_client.aclose)
  from app.providers.pool import pools
  self.addAsyncCleanup(pools.close)
  # Execute the migration against a transaction-local shadow table, never production data.
  from sqlalchemy import text
  async with engine.begin() as connection:
   await connection.execute(text("CREATE TEMP TABLE route_configs (decision_workspace varchar(63), decision_region varchar(30)) ON COMMIT DROP"))
   await connection.execute(text("INSERT INTO route_configs VALUES ('llm-legacy','cn-beijing'),('','cn-beijing')"))
   def migrate(sync):
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec=importlib.util.spec_from_file_location('decision_url_migration','alembic/versions/0036_decision_service_url.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(sync)):module.upgrade()
   await connection.run_sync(migrate)
   migrated=(await connection.execute(text("SELECT decision_workspace,decision_service_url FROM route_configs"))).all()
   self.assertEqual(dict(migrated),{'llm-legacy':'https://llm-legacy.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/systemone','':''})
  calls=[];mode={'choice':'0','confidence':.95,'status':200,'delay':0,'active':0,'max_active':0}
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append((self.path,data,self.headers.get('Authorization')))
    if self.path=='/systemone':
     mode['active']+=1;mode['max_active']=max(mode['max_active'],mode['active']);time.sleep(mode['delay']);mode['active']-=1
     probabilities={str(i):0. for i in range(2)};probabilities['other']=0.;probabilities[mode['choice']]=1.
     value={'model':data['model'],'answers':{'route':{'type':'choice','choice':mode['choice'],'confidence':mode['confidence'],'probabilities':probabilities}},'usage':{'input_tokens':12}}
     if mode.get('wrong_model'):value['model']='unexpected-model'
     code=mode['status']
    else:
     code=200;value={'id':'chat-local','object':'chat.completion','created':1,'model':data['model'],'choices':[{'index':0,'message':{'role':'assistant','content':data['model']},'finish_reason':'stop'}],'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
    raw=json.dumps(value).encode();self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers()
    try:self.wfile.write(raw)
    except (BrokenPipeError,ConnectionResetError):pass
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
  real_transport=model_decision.transport
  async def loopback(payload,key,timeout,url=None,status=None):
   if url and 'decision.example' in url:self.assertEqual(url,'https://decision.example/custom/systemone')
   return await real_transport(payload,key,timeout,f'http://127.0.0.1:{server.server_port}/systemone',status)
  with patch.object(model_decision,'transport',loopback):
   async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1',timeout=30) as client:
    login=await client.post('/api/auth/login',json={'username':'admin','password':Path('/data/config/audit-password.txt').read_text().strip()});self.assertEqual(login.status_code,200,login.text[:100])
    client.headers['Authorization']='Bearer '+login.json()['data']['access_token'];client.headers['X-CSRF-Token']=client.cookies.get('hd_csrf','')
    async def api(method,path,data=None,status=200):
     result=await client.request(method,'/api/'+path,json=data);self.assertEqual(result.status_code,status,(path,result.text[:350]));return result.json().get('data')
    prefix='decision-'+uuid4().hex[:8];groups=[]
    for name in ('code','write'):
     await api('POST','admin/providers',{'name':prefix+name,'provider_type':'custom_openai','protocol':'openai','protocol_type':'text','base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'fixture-only','max_concurrency':10,'model_mappings':[{'logical_model':prefix+name,'upstream_model':name,'model_type':'text'}]},201)
     groups.append(await api('POST','admin/model-groups',{'name':prefix+name,'protocol_type':'text','logical_models':[prefix+name]},201))
    rule={'virtual_model':prefix+'auto','route_mode':'model','decision_provider':'aliyun','decision_workspace':'fixture-workspace','decision_fallback_group':groups[1]['id'],'decision_targets':[{'name':'代码','model_group_id':groups[0]['id'],'description':'代码问题'},{'name':'写作','model_group_id':groups[1]['id'],'description':'写作问题'}],'status':'enabled'}
    await api('POST','admin/smart-route/configs',rule,400)
    rule['decision_api_key']='aliyun-fixture-only';cfg=await api('POST','admin/smart-route/configs',rule,201);rule.pop('decision_api_key');path='admin/smart-route/configs/'+str(cfg['id'])
    self.assertNotIn('key_encrypted',json.dumps(cfg));self.assertTrue(cfg['decision_key_configured'])
    async with session_factory() as db:
     saved=await db.get(RouteConfig,cfg['id']);self.assertNotEqual(saved.aliyun_key_encrypted,'aliyun-fixture-only');self.assertEqual(decrypt_secret(saved.aliyun_key_encrypted),'aliyun-fixture-only')
    test_path='admin/smart-route/test-model'
    draft={'decision_provider':'aliyun','decision_workspace':'fixture-workspace','consent':True}
    await api('POST',test_path,draft,400)
    await api('POST',test_path,{**draft,'consent':False},422)
    tested=await api('POST',test_path,{**draft,'decision_api_key':'draft-fixture'})
    self.assertTrue(tested['available']);self.assertEqual(tested['upstream_status'],200)
    self.assertEqual(calls[-1][2],'Bearer draft-fixture');self.assertEqual(calls[-1][1]['state'],{'request':'你好'})
    tested=await api('POST',test_path,{**draft,'config_id':cfg['id'],'expected_updated_at':cfg['updated_at']})
    self.assertTrue(tested['available']);self.assertEqual(calls[-1][2],'Bearer aliyun-fixture-only')
    mode['status']=403
    tested=await api('POST',test_path,{**draft,'config_id':cfg['id']})
    self.assertFalse(tested['available']);self.assertEqual(tested['upstream_status'],403)
    mode['status']=200
    unchanged=await api('GET','admin/smart-route/configs')
    self.assertEqual(next(c for c in unchanged if c['id']==cfg['id'])['updated_at'],cfg['updated_at'])
    custom_url='https://decision.example/custom/systemone'
    rule['decision_service_url']=custom_url
    cfg=await api('PUT',path,{**rule,'expected_updated_at':cfg['updated_at']})
    self.assertEqual(cfg['decision_service_url'],custom_url)
    tested=await api('POST',test_path,{'config_id':cfg['id'],'decision_provider':'aliyun','decision_service_url':custom_url,'consent':True})
    self.assertTrue(tested['available'])
    stale=cfg['updated_at'];cfg=await api('PUT',path,{**rule,'decision_threshold':.6,'expected_updated_at':stale});await api('PUT',path,{**rule,'expected_updated_at':stale},409)
    await api('DELETE','admin/model-groups/'+str(groups[0]['id']),status=409)
    await api('POST','admin/smart-route/samples',{'config_id':cfg['id'],'samples':[{'prompt':'test','classification':'simple','build_vector':True}]},409)
    preview=await api('POST',path+'/preview',{'prompt':'代码问题'});self.assertEqual(preview['decision_target'],'代码');self.assertEqual(preview['source'],'model');self.assertTrue(preview['decision_request_id'])
    self.assertEqual(calls[-1][2],'Bearer aliyun-fixture-only');self.assertEqual(calls[-1][1]['model'],'decision-model-preview')
    async def chat():return await client.post('/api/admin/chat-test/completions',json={'model':rule['virtual_model'],'messages':[{'role':'user','content':'帮我写代码'}],'max_tokens':8,'stream':False})
    result=await chat();self.assertEqual(result.status_code,200,result.text[:300]);self.assertEqual(result.json()['choices'][0]['message']['content'],'code')
    for target in (rule['virtual_model'],prefix+'code'):
     policy=await api('POST','admin/compliance/policies',{'name':prefix+target[-6:],'status':'enabled','action':'block','models':[target]})
     word=await api('POST','admin/compliance/words',{'pattern':'帮我写代码','policy_id':policy['id']})
     before=len(calls);blocked=await chat();self.assertEqual(blocked.status_code,403,blocked.text[:200])
     if target==rule['virtual_model']:self.assertEqual(len(calls),before)
     else:self.assertEqual(len([c for c in calls[before:] if c[0]!='/systemone']),0)
     await api('DELETE','admin/compliance/words/'+str(word['id']));await api('DELETE','admin/compliance/policies/'+str(policy['id']))
    grant=await api('POST','admin/model-groups',{'name':prefix+'virtual','protocol_type':'text','logical_models':[rule['virtual_model']]},201)
    restricted_group=await api('POST','admin/user-groups',{'name':prefix,'model_access':'selected','model_group_ids':[grant['id'],groups[0]['id']]},201)
    await api('POST','admin/users',{'username':prefix,'password':'Fixture-Initial26!Aa','user_group_id':restricted_group['id']},201)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1') as ordinary:
     signed=await ordinary.post('/api/auth/login',json={'username':prefix,'password':'Fixture-Initial26!Aa'});self.assertEqual(signed.status_code,200)
     ordinary.headers['Authorization']='Bearer '+signed.json()['data']['access_token']
     changed=await ordinary.post('/api/auth/change-password',json={'old_password':'Fixture-Initial26!Aa','new_password':'Fixture-Replaced26!Bb'});self.assertEqual(changed.status_code,200)
     signed=await ordinary.post('/api/auth/login',json={'username':prefix,'password':'Fixture-Replaced26!Bb'});ordinary.headers['Authorization']='Bearer '+signed.json()['data']['access_token']
     self.assertEqual((await ordinary.get('/api/admin/smart-route/configs')).status_code,403)
     self.assertEqual((await ordinary.post('/api/admin/smart-route/test-model',json={'decision_api_key':'fixture','consent':True})).status_code,403)
     own=await ordinary.post('/api/portal/api-keys',json={'name':prefix});self.assertEqual(own.status_code,201)
     async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+own.json()['data']['secret']}) as restricted:
      before=len(calls);blocked=await restricted.post('/v1/chat/completions',json={'model':rule['virtual_model'],'messages':[{'role':'user','content':'代码问题'}],'max_tokens':8})
      self.assertEqual(blocked.status_code,403,blocked.text[:200]);self.assertEqual(len(calls),before)
      await api('PUT','admin/user-groups/'+str(restricted_group['id']),{'name':prefix,'model_access':'selected','model_group_ids':[grant['id'],*[g['id'] for g in groups]]})
      accepted=await restricted.post('/v1/chat/completions',json={'model':rule['virtual_model'],'messages':[{'role':'user','content':'代码问题'}],'max_tokens':8})
      self.assertEqual(accepted.status_code,200,accepted.text[:200])
    mode['choice']='other';preview=await api('POST',path+'/preview',{'prompt':'问候'});self.assertEqual(preview['decision_target'],'兜底');self.assertEqual(preview['reason'],'ROUTE_MODEL_OTHER')
    mode['choice']='0';mode['confidence']=.1;preview=await api('POST',path+'/preview',{'prompt':'代码'});self.assertEqual(preview['reason'],'ROUTE_MODEL_LOW_CONFIDENCE')
    mode['confidence']=.95;mode['status']=503;preview=await api('POST',path+'/preview',{'prompt':'代码'});self.assertEqual(preview['status'],'fallback');mode['status']=200
    mode['choice']='999'
    invalid=await api('POST',path+'/preview',{'prompt':'invalid choice'})
    self.assertEqual(invalid['reason'],'ROUTE_MODEL_INVALID');self.assertEqual(invalid['decision_target'],'兜底')
    mode['choice']='0';mode['wrong_model']=True
    invalid=await api('POST',path+'/preview',{'prompt':'wrong model'})
    self.assertEqual(invalid['reason'],'ROUTE_MODEL_INVALID');mode['wrong_model']=False
    cfg=await api('PUT',path,{**rule,'decision_timeout':1})
    mode['delay']=1.5
    timed=await api('POST',path+'/preview',{'prompt':'timeout test'})
    self.assertIn(timed['reason'],('ROUTE_MODEL_UNAVAILABLE','ROUTE_MODEL_TIMEOUT'))
    self.assertEqual(timed['decision_target'],'兜底');mode['delay']=0
    cfg=await api('PUT',path,rule)
    # A changed rule cannot execute a stale decision even when the provider succeeds.
    mode['delay']=.4;before=len(calls)
    pending=asyncio.create_task(client.post('/api/'+path+'/preview',json={'prompt':'concurrent edit'}))
    for _ in range(100):
     if len(calls)>before:break
     await asyncio.sleep(.01)
    cfg=await api('PUT',path,{**rule,'decision_threshold':.65})
    rejected=await pending;self.assertEqual(rejected.status_code,409,rejected.text[:200])
    cfg=await api('PUT',path,rule);mode['delay']=0
    # Cancellation must release every decision concurrency slot.
    mode['delay']=.5;before=len(calls)
    pending=asyncio.create_task(client.post('/api/'+path+'/preview',json={'prompt':'cancelled preview'}))
    for _ in range(100):
     if len(calls)>before:break
     await asyncio.sleep(.01)
    pending.cancel()
    with self.assertRaises(asyncio.CancelledError):await pending
    self.assertEqual(await redis_client.zcard('gateway:decision:'+str(cfg['id'])),0)
    mode['delay']=0;await asyncio.sleep(.6)
    logs=await api('GET','admin/smart-route/logs?source=model');self.assertTrue(any(x['decision_target']=='代码' for x in logs['items']))
    stats=await api('GET','admin/smart-route/statistics?virtual_model='+rule['virtual_model']);self.assertTrue(stats['distributions']['decision_model'])
    # Provider credentials do not cross providers, and returning to an earlier provider keeps its key.
    await api('PUT',path,{**rule,'decision_provider':'typesafe'},400)
    cfg=await api('PUT',path,{**rule,'decision_provider':'typesafe','status':'disabled'})
    self.assertFalse(cfg['decision_key_configured'])
    cfg=await api('PUT',path,rule);self.assertTrue(cfg['decision_key_configured'])
    await api('POST','admin/providers',{'name':prefix+'embedding','provider_type':'custom_openai','protocol':'openai','protocol_type':'vector','base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'fixture-only','model_mappings':[{'logical_model':prefix+'embedding','upstream_model':'embedding','model_type':'embedding'}]},201)
    vector_fields={'embedding_model':prefix+'embedding','simple_model_group':groups[0]['id'],'complex_model_group':groups[1]['id']}
    cfg=await api('PUT',path,{**rule,**vector_fields,'route_mode':'vector'})
    self.assertEqual(cfg['route_mode'],'vector');self.assertEqual(len(cfg['decision_targets']),2);self.assertTrue(cfg['decision_key_configured'])
    await api('POST','admin/smart-route/samples',{'config_id':cfg['id'],'samples':[{'prompt':'retained vector sample','classification':'simple','build_vector':False}]},201)
    generation=cfg['vector_generation'];cfg=await api('PUT',path,rule)
    self.assertEqual(cfg['embedding_model'],vector_fields['embedding_model']);self.assertEqual(cfg['vector_generation'],generation)
    preserved=await api('GET','admin/smart-route/samples?config_id='+str(cfg['id']));self.assertEqual(preserved['total'],1)
    mode['delay']=.15
    results=await asyncio.gather(*[chat() for _ in range(12)])
    self.assertTrue(all(r.status_code in (200,429) for r in results),[(r.status_code,r.text[:150]) for r in results]);self.assertLessEqual(mode['max_active'],10);mode['delay']=0
    for slot in ('gateway:decision:'+str(cfg['id']),):self.assertEqual(await redis_client.zcard(slot),0)
    print('PASS model decision: real loopback HTTP/SQL/Redis, encrypted provider-isolated keys, preview, chat, fallbacks, logs, statistics, stale edits, group guards and bounded concurrency')
