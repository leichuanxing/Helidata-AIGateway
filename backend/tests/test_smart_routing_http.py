"""Real routing flows against Nginx/SQL/Redis and a local non-billable upstream."""
import asyncio,json,os,threading,time,unittest
from pathlib import Path
from uuid import uuid4
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import httpx

@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','disposable container only')
class SmartRouteHTTPTests(unittest.IsolatedAsyncioTestCase):
 async def test_rules_samples_jobs_protocols_compliance_and_statistics(self):
  ident=os.environ.get('AUDIT_CONTAINER_ID','');self.assertGreaterEqual(len(ident),12);self.assertEqual(os.environ.get('HOSTNAME','')[:12],ident[:12])
  from sqlalchemy import text
  from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
  from sqlalchemy.pool import NullPool
  from app.core.database import connect_database,settings
  engine=create_async_engine(settings.url(),poolclass=NullPool,async_creator=lambda:connect_database(settings));self.addAsyncCleanup(engine.dispose)
  factory=async_sessionmaker(engine,expire_on_commit=False)
  calls=[];modes={'embedding':'ok'}
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    raw=json.dumps({'data':[{'id':name} for name in ('embedding','simple','complex')]}).encode()
    self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
   def do_POST(self):
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append((self.path,body))
    def answer(status,result):
     raw=json.dumps(result).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers()
     try:self.wfile.write(raw)
     except (BrokenPipeError,ConnectionResetError):pass
    if self.path.endswith('/embeddings'):
     if modes['embedding']=='error':return answer(503,{'error':{'message':'local failure'}})
     value=body['input'];value=value[0] if isinstance(value,list) else value
     return answer(200,{'object':'list','data':[{'object':'embedding','index':0,'embedding':[0.,1.] if 'complex' in value else [1.,0.]}],'usage':{'prompt_tokens':1,'total_tokens':1}})
    model=body['model']
    chat={'id':'chat-local','object':'chat.completion','created':1,'model':model,'choices':[{'index':0,'message':{'role':'assistant','content':model},'finish_reason':'stop'}],'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
    response={'id':'resp-local','object':'response','status':'completed','model':model,'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':model}]}],'usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2}}
    message={'id':'msg-local','type':'message','role':'assistant','model':model,'content':[{'type':'text','text':model}],'stop_reason':'end_turn','usage':{'input_tokens':1,'output_tokens':1}}
    if not body.get('stream'):return answer(200,response if self.path.endswith('/responses') else message if self.path.endswith('/messages') else chat)
    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
    def frame(kind,data):
     try:self.wfile.write(((('event: '+kind+'\n') if kind else '')+'data: '+(data if isinstance(data,str) else json.dumps(data))+'\n\n').encode());self.wfile.flush()
     except (BrokenPipeError,ConnectionResetError):pass
    if self.path.endswith('/responses'):
     frame('response.created',{'type':'response.created','response':{'object':'response'}})
     frame('response.output_text.delta',{'type':'response.output_text.delta','delta':model})
     frame('response.completed',{'type':'response.completed','response':response})
    elif self.path.endswith('/messages'):
     frame('message_start',{'type':'message_start','message':{**message,'content':[],'stop_reason':None}})
     frame('content_block_start',{'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}})
     frame('content_block_delta',{'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':model}})
     frame('content_block_stop',{'type':'content_block_stop','index':0})
     frame('message_delta',{'type':'message_delta','delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':1}})
     frame('message_stop',{'type':'message_stop'})
    else:
     frame('',{'id':'chunk','object':'chat.completion.chunk','created':1,'model':model,'choices':[{'index':0,'delta':{'content':model},'finish_reason':None}]})
     if 'cancel' in str(body):time.sleep(1)
     frame('','[DONE]')
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
  async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=30) as admin:
   r=await admin.post('/api/auth/login',json={'username':'admin','password':Path('/data/config/audit-password.txt').read_text().strip()});self.assertEqual(r.status_code,200)
   admin.headers['Authorization']='Bearer '+r.json()['data']['access_token']
   admin.headers['X-CSRF-Token']=admin.cookies.get('hd_csrf','')
   async def api(method,path,body=None,status=200,params=None):
    r=await admin.request(method,'/api/'+path,json=body,params=params);self.assertEqual(r.status_code,status,(path,r.text[:300]));return r.json().get('data')
   prefix='smart-'+uuid4().hex[:9];providers=[];groups=[]
   for label in ('simple','complex','embedding'):
    provider=await api('POST','admin/providers',{'name':prefix+label,'provider_type':'custom_openai','protocol':'openai','protocol_type':'vector' if label=='embedding' else 'text',
     'base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'fixture-only','max_concurrency':3,
     'protocol_config':{p:{'path_prefix':'','auth_type':'x-api-key' if p=='anthropic-messages' else 'bearer'} for p in (('openai-embeddings',) if label=='embedding' else ('openai-completions','openai-responses','anthropic-messages'))},
     'model_mappings':[{'logical_model':prefix+label,'upstream_model':label,'model_type':'embedding' if label=='embedding' else 'text'}]},201)
    providers.append(provider)
    if label!='embedding':groups.append(await api('POST','admin/model-groups',{'name':prefix+label,'protocol_type':'text','logical_models':[prefix+label]},201))
   options=await api('GET','admin/model-group-options')
   for group in groups:
    option=next(item for item in options if item['id']==group['id'])
    self.assertEqual(option['protocol_type'],'text');self.assertEqual(option['status'],'enabled')
   body={'virtual_model':prefix+'virtual','embedding_model':prefix+'embedding','simple_model_group':groups[0]['id'],'complex_model_group':groups[1]['id'],'status':'enabled','fallback':'error'}
   cfg=await api('POST','admin/smart-route/configs',body,201);path='admin/smart-route/configs/'+str(cfg['id'])
   async def save(**changes):
    nonlocal cfg
    body.update(changes);cfg=await api('PUT',path,{**body,'expected_updated_at':cfg['updated_at']});return cfg
   stale=cfg['updated_at'];await save(top_k=6)
   await api('PUT',path,{**body,'expected_updated_at':stale},409)
   results=await asyncio.gather(*[admin.put('/api/'+path,json={**body,'expected_updated_at':cfg['updated_at'],'top_k':k}) for k in (7,8)])
   self.assertEqual(sorted(r.status_code for r in results),[200,409]);cfg=next(r.json()['data'] for r in results if r.status_code==200);body['top_k']=cfg['top_k']
   await api('POST','admin/smart-route/configs',body,409)
   await api('DELETE','admin/model-groups/'+str(groups[0]['id']),status=409)
   added=await api('POST','admin/smart-route/samples',{'config_id':cfg['id'],'samples':[{'prompt':'simple sample','classification':'simple','build_vector':False},{'prompt':'complex sample','classification':'complex','build_vector':False}]},201)
   ids=added['ids'];self.assertEqual(added['queued'],0)
   empty_ready=next(c for c in await api('GET','admin/smart-route/configs') if c['id']==cfg['id'])
   self.assertEqual(empty_ready['sample_summary'],{'total':2,'ready':0})
   first=(await api('GET','admin/smart-route/samples',params={'config_id':cfg['id']}))['items'][-1]
   sample_edit={'prompt':first['prompt'],'classification':first['classification'],'build_vector':False,'expected_revision':first['revision'],'remark':'current edit'}
   await api('PUT','admin/smart-route/samples/'+str(first['id']),sample_edit)
   await api('PUT','admin/smart-route/samples/'+str(first['id']),{**sample_edit,'remark':'stale overwrite'},409)

   await api('POST','admin/smart-route/samples',{'config_id':cfg['id'],'samples':[{'prompt':' simple sample ','classification':'complex'}]},409)
   await api('POST','admin/smart-route/samples/import',{'config_id':cfg['id'],'content':'prompt,classification\nnew,simple\ninvalid,wrong','build_vector':False},400)
   listed=await api('GET','admin/smart-route/samples',params={'config_id':cfg['id'],'vector_status':'not_built'});self.assertEqual(listed['total'],2)
   await api('POST','admin/smart-route/samples/vectorize',{'config_id':cfg['id'],'sample_ids':[ids[0],999999]},400)
   # Inject a running-job state only in this guarded disposable database.
   async with factory.begin() as db:
    await db.execute(text("UPDATE route_samples SET vector_status='processing',vector_requested=true,job_started_at=now() WHERE id=ANY(CAST(:ids AS bigint[]))"),{'ids':ids})
   busy=(await api('GET','admin/smart-route/samples',params={'config_id':cfg['id']}))['items']
   self.assertEqual((await api('POST','admin/smart-route/samples/vectorize',{'config_id':cfg['id'],'all_samples':True}))['queued'],0)
   await api('POST','admin/smart-route/samples/'+str(ids[0])+'/vectorize',{},409)
   after=(await api('GET','admin/smart-route/samples',params={'config_id':cfg['id']}))['items']
   self.assertEqual([(r['id'],r['revision']) for r in busy],[(r['id'],r['revision']) for r in after])
   async with factory.begin() as db:
    await db.execute(text("UPDATE route_samples SET vector_status='pending',vector_requested=false,job_started_at=NULL WHERE id=ANY(CAST(:ids AS bigint[]))"),{'ids':ids})
   await api('POST','admin/smart-route/samples/vectorize',{'config_id':cfg['id'],'all_samples':True})
   for _ in range(100):
    listed=await api('GET','admin/smart-route/samples',params={'config_id':cfg['id']})
    if all(s['vector_status']=='ready' for s in listed['items']):break
    await asyncio.sleep(.2)
   self.assertTrue(all(s['vector_status']=='ready' for s in listed['items']),listed)
   self.assertEqual(next(c for c in await api('GET','admin/smart-route/configs') if c['id']==cfg['id'])['sample_summary'],{'total':2,'ready':2})
   before=len(calls);preview=await api('POST',path+'/preview',{'prompt':'simple sample'})
   self.assertEqual(preview['source'],'local_rule');self.assertEqual(len(calls),before)
   preview=await api('POST',path+'/preview',{'prompt':'complex unseen'})
   self.assertEqual(preview['classification'],'complex');self.assertEqual(preview['selected_model'],prefix+'complex')
   secret=(await api('POST','portal/api-keys',{'name':prefix},201))['secret']
   async with httpx.AsyncClient(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+secret},timeout=30) as client:
    async def chat(text='simple sample',stream=False):return await client.post('/v1/chat/completions',json={'model':body['virtual_model'],'messages':[{'role':'user','content':text}],'max_tokens':8,'stream':stream})
    for protocol,payload,terminal in [('chat/completions',{'messages':[{'role':'user','content':'simple sample'}],'max_tokens':8},'[DONE]'),('responses',{'input':'complex sample','max_output_tokens':8},'response.completed'),('messages',{'messages':[{'role':'user','content':'simple sample'}],'max_tokens':8},'message_stop')]:
     for stream in (False,True):
      r=await client.post('/v1/'+protocol,json={'model':body['virtual_model'],**payload,'stream':stream});self.assertEqual(r.status_code,200,r.text[:300])
      if stream:self.assertIn(terminal,r.text)
      else:self.assertEqual(r.json()['model'],body['virtual_model'])
    results=await asyncio.gather(*[chat() for _ in range(6)]);self.assertTrue(all(r.status_code==200 for r in results))
    async with client.stream('POST','/v1/chat/completions',json={'model':body['virtual_model'],'messages':[{'role':'user','content':'cancel simple'}],'max_tokens':8,'stream':True}) as r:
     self.assertEqual(r.status_code,200);cancelled_id=r.headers['x-request-id']
     async for line in r.aiter_lines():
      if 'choices' in line:break
    for _ in range(40):
     log=await admin.get('/api/admin/call-logs/'+cancelled_id)
     if log.status_code==200:break
     await asyncio.sleep(.1)
    self.assertEqual(log.json()['data']['status'],'client_cancelled')
    decisions=await api('GET','admin/smart-route/logs',params={'virtual_model':body['virtual_model'],'request_kind':'real'})
    self.assertGreaterEqual(decisions['total'],13)
    detail=await api('GET','admin/smart-route/logs/'+str(decisions['items'][0]['id']));self.assertTrue(detail['evidence']);self.assertIsNotNone(detail['embedding_request_id'])
    stats=await api('GET','admin/smart-route/statistics',params={'virtual_model':body['virtual_model']});self.assertGreaterEqual(stats['summary']['failures'],1);self.assertEqual(stats['summary']['previews'],2)
    await api('GET','admin/smart-route/logs',params={'start':'2026-10-22T00:00:00'},status=422)
    # Literal policies on both virtual and actual targets must block before generation.
    for target in (body['virtual_model'],prefix+'simple'):
     policy=await api('POST','admin/compliance/policies',{'name':prefix+target[-6:],'status':'enabled','action':'block','models':[target]})
     word=await api('POST','admin/compliance/words',{'pattern':'forbidden-'+prefix,'policy_id':policy['id']})
     r=await chat('forbidden-'+prefix);self.assertEqual(r.status_code,403,r.text)
     await api('DELETE','admin/compliance/words/'+str(word['id']));await api('DELETE','admin/compliance/policies/'+str(policy['id']))
    grants=[]
    for label,category in [('virtual','text'),('embedding','vector')]:
     grants.append(await api('POST','admin/model-groups',{'name':prefix+label,'protocol_type':category,'logical_models':[prefix+label]},201))
    grant_ids=[g['id'] for g in groups+grants]
    user_group=await api('POST','admin/user-groups',{'name':prefix,'model_access':'selected','model_group_ids':grant_ids},201)
    await api('POST','admin/users',{'username':prefix,'password':'Fixture-Initial26!Aa','user_group_id':user_group['id']},201)
    async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=30) as ordinary:
     signed=await ordinary.post('/api/auth/login',json={'username':prefix,'password':'Fixture-Initial26!Aa'});self.assertEqual(signed.status_code,200)
     ordinary.headers['Authorization']='Bearer '+signed.json()['data']['access_token']
     changed=await ordinary.post('/api/auth/change-password',json={'old_password':'Fixture-Initial26!Aa','new_password':'Fixture-Replaced26!Bb'});self.assertEqual(changed.status_code,200)
     signed=await ordinary.post('/api/auth/login',json={'username':prefix,'password':'Fixture-Replaced26!Bb'});ordinary.headers['Authorization']='Bearer '+signed.json()['data']['access_token']
     for endpoint in ('configs','logs','statistics'):
      self.assertEqual((await ordinary.get('/api/admin/smart-route/'+endpoint)).status_code,403)
     own=await ordinary.post('/api/portal/api-keys',json={'name':prefix});self.assertEqual(own.status_code,201)
     async with httpx.AsyncClient(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+own.json()['data']['secret']},timeout=30) as restricted:
      payload={'model':body['virtual_model'],'messages':[{'role':'user','content':'simple sample'}],'max_tokens':8}
      self.assertEqual((await restricted.post('/v1/chat/completions',json=payload)).status_code,200)
      await api('PUT','admin/user-groups/'+str(user_group['id']),{'name':prefix,'model_access':'selected','model_group_ids':[groups[0]['id']]+[g['id'] for g in grants]})
      self.assertEqual((await restricted.post('/v1/chat/completions',json=payload)).status_code,403)
    await api('DELETE',path,status=409)
    await api('PUT','admin/user-groups/'+str(user_group['id']),{'name':prefix,'model_access':'selected','model_group_ids':[]})
    for grant in grants:await api('DELETE','admin/model-groups/'+str(grant['id']))
    await save(status='disabled');self.assertEqual((await chat()).status_code,503);await save(status='enabled',fallback='complex')
    modes['embedding']='error';r=await chat('new failure text');self.assertEqual(r.status_code,200,r.text);self.assertIn('complex',r.text)
    await save(fallback='error');r=await chat('new failure text');self.assertGreaterEqual(r.status_code,500)
    modes['embedding']='ok'
    recovered=await api('POST','admin/providers/'+str(providers[-1]['id'])+'/test',{});self.assertTrue(recovered['success'])
    await api('PUT','admin/smart-route/samples/'+str(ids[0]),{'prompt':'edited simple sample','classification':'simple','build_vector':False})
    listed=await api('GET','admin/smart-route/samples',params={'config_id':cfg['id'],'vector_status':'not_built'});self.assertEqual(listed['total'],1)
    await api('POST','admin/smart-route/samples/'+str(ids[0])+'/vectorize',{})
    for _ in range(80):
     listed=await api('GET','admin/smart-route/samples',params={'config_id':cfg['id'],'vector_status':'ready'})
     if listed['total']==2:break
     await asyncio.sleep(.2)
    self.assertEqual(listed['total'],2)
   for sample_id in ids:await api('DELETE','admin/smart-route/samples/'+str(sample_id))
   await api('DELETE',path)
   self.assertGreater((await api('GET','admin/smart-route/logs',params={'virtual_model':body['virtual_model']}))['total'],0)
   for group in groups:await api('DELETE','admin/model-groups/'+str(group['id']))
   for provider in providers:await api('DELETE','admin/providers/'+str(provider['id']))
   await api('POST','auth/logout',{})
  print('PASS routing real HTTP/SQL/Redis: CRUD, concurrent edit, vectors, preview, three protocols/SSE, cancellation, compliance, fallback and statistics')
