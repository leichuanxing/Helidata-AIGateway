"""Real HTTP fixtures for all new protocols, accounting, conversion and stream cleanup."""
import asyncio,json,threading,time,socket,select as sockets
from datetime import timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from sqlalchemy import select,delete,text,func
import httpx
import stage12_nonstream_regression as seed
from app.models.call_log import CallLog
from app.models.quota import QuotaReservation
from app.gateway import call_log
from app.gateway.context import GatewayContext
from app.core.security import now,hash_password

calls=[];seen=set();BASE='';PASSWORD='Stage15Check!Temporary9842';MODE='normal'
class Fixture(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));op=self.path.rsplit('/',1)[-1];mode=self.path.split('/')[1]
  assert body['model']=='private-upstream-model'
  if op=='messages':assert self.headers['x-api-key']==seed.SECRET and self.headers['anthropic-version']=='2023-06-01'
  else:assert self.headers['Authorization']=='Bearer '+seed.SECRET
  assert self.headers['X-Request-ID'].startswith('req_');calls.append((op,body))
  try:
   if mode=='bad':self.send_json({'error':seed.SECRET+' '+seed.KEY},400);return
   if mode=='fail':self.send_json({'error':seed.SECRET},500);return
   if body.get('stream'):
    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
    def emit(kind,data):
     raw=((('event: '+kind+'\r\n') if kind else '')+'data: '+(data if isinstance(data,str) else json.dumps(data,ensure_ascii=False))+'\r\n\r\n').encode()
     # Deliberately fragment UTF8 and CRLF across real writes.
     for start in range(0,len(raw),7):self.wfile.write(raw[start:start+7]);self.wfile.flush()
    if op=='responses':
     response={'id':'resp_fixture','object':'response','status':'in_progress','model':body['model'],'output':[]}
     emit('response.created',{'type':'response.created','response':response,'sequence_number':0});time.sleep(.07)
     if mode=='cancel':
      ready,_,_=sockets.select([self.connection],[],[],5);assert ready and self.connection.recv(1)==b'';return
     emit('response.output_text.delta',{'type':'response.output_text.delta','delta':'你好','output_index':0,'content_index':0,'sequence_number':1})
     if mode=='failed':emit('response.failed',{'type':'response.failed','response':{**response,'status':'failed','usage':{'input_tokens':4,'output_tokens':1,'total_tokens':5},'error':{'message':seed.SECRET}}});return
     if mode=='eof':return
     if mode=='error':emit('error',{'type':'error','message':seed.SECRET});return
     emit('response.completed',{'type':'response.completed','sequence_number':2,'response':{**response,'status':'completed','usage':{'input_tokens':4,'output_tokens':2,'total_tokens':6,'input_tokens_details':{'cached_tokens':1}}}})
    elif op=='messages':
     emit('message_start',{'type':'message_start','message':{'id':'msg_fixture','type':'message','role':'assistant','model':body['model'],'content':[],'usage':{'input_tokens':4,'output_tokens':0,'cache_read_input_tokens':1,'cache_creation_input_tokens':2}}});time.sleep(.07)
     if mode=='cancel':
      ready,_,_=sockets.select([self.connection],[],[],5);assert ready and self.connection.recv(1)==b'';return
     emit('content_block_start',{'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}})
     emit('content_block_delta',{'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':'你好'}})
     emit('content_block_stop',{'type':'content_block_stop','index':0})
     if mode=='eof':return
     if mode=='error':emit('error',{'type':'error','error':{'message':seed.SECRET}});return
     emit('message_delta',{'type':'message_delta','delta':{'stop_reason':'end_turn','stop_sequence':None},'usage':{'output_tokens':2}})
     emit('message_stop',{'type':'message_stop'})
    else:
     chunk={'id':'chat_fixture','object':'chat.completion.chunk','created':1791110000,'model':body['model']}
     emit('',{**chunk,'choices':[{'index':0,'delta':{'role':'assistant'},'finish_reason':None}]});time.sleep(.07)
     emit('',{**chunk,'choices':[{'index':0,'delta':{'content':'你好'},'finish_reason':None}]})
     emit('',{**chunk,'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]})
     emit('',{**chunk,'choices':[],'usage':{'prompt_tokens':4,'completion_tokens':2,'total_tokens':6}});emit('','[DONE]')
    return
   if op=='responses':result={'id':'resp_fixture','object':'response','model':body['model'],'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':'你好'}]}],'usage':{'input_tokens':4,'output_tokens':2,'total_tokens':6}}
   elif op=='messages':result={'id':'msg_fixture','type':'message','role':'assistant','model':body['model'],'content':[{'type':'text','text':'你好'}],'stop_reason':'end_turn','stop_sequence':None,'usage':{'input_tokens':4,'output_tokens':2,'cache_read_input_tokens':1,'cache_creation_input_tokens':2}}
   elif op=='embeddings':
    count=len(body['input']) if isinstance(body['input'],list) and isinstance(body['input'][0],str) else 1
    result={'object':'list','model':body['model'],'data':[{'object':'embedding','index':i,'embedding':[.1,.2]} for i in range(count)],'usage':{'prompt_tokens':4,'total_tokens':4}}
   elif op=='rerank':result={'results':[{'index':1,'relevance_score':.9},{'index':0,'relevance_score':.1}][:body.get('top_n',2)]}
   elif op=='generations':result={'created':1791110000,'data':[{'b64_json':'aW1hZ2U='}],'usage':{'input_tokens':4,'output_tokens':2,'total_tokens':6}}
   else:result={'id':'chat_fixture','object':'chat.completion','created':1791110000,'model':body['model'],'choices':[{'index':0,'message':{'role':'assistant','content':'你好'},'finish_reason':'stop'}],'usage':{'prompt_tokens':4,'completion_tokens':2,'total_tokens':6}}
   if op=='responses' and mode=='failed':result={**result,'status':'failed','usage':{'input_tokens':4,'output_tokens':1,'total_tokens':5},'error':{'message':seed.SECRET}}
   if mode=='invalid':result={**result,'data':[],'content':None,'output':None,'results':[{'index':999,'relevance_score':.9}],'choices':[]}
   self.send_json(result)
  except (BrokenPipeError,ConnectionResetError):pass
 def send_json(self,data,status=200):
  raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

async def configure(protocol='openai',mode='normal'):
 await seed.change(seed.Provider,'provider',protocol=protocol,provider_type='anthropic' if protocol=='anthropic' else 'custom_openai',base_url=BASE+'/'+mode+'/v1',failure_count=0,cooldown_until=None,health_status='unknown')

async def capture(r):
 rid=r.headers.get('X-Request-ID')
 if rid:seen.add(rid)

async def record(rid):
 for _ in range(100):
  async with seed.session_factory() as db:r=await db.scalar(select(CallLog).where(CallLog.request_id==rid))
  if r:return r
  await asyncio.sleep(.04)
 raise AssertionError('missing terminal log')

async def cleanup():
 async with seed.session_factory.begin() as db:
  await db.execute(delete(CallLog).where((CallLog.request_id.in_(seen)) | (CallLog.request_model.in_([seed.NAME,seed.EMBED,seed.PREFIX+'-rerank',seed.PREFIX+'-image']))))
  for table in ('usage_hourly','usage_daily'):await db.execute(text(f'DELETE FROM {table} WHERE request_model LIKE :p'),{'p':seed.PREFIX+'%'})
 async with seed.session_factory.begin() as db:
  await db.execute(delete(seed.User).where(seed.User.id==seed.ids['user']))
  await db.execute(delete(seed.UserGroup).where(seed.UserGroup.id==seed.ids['ug']))
  await db.execute(delete(seed.ModelGroup).where(seed.ModelGroup.id==seed.ids['mg']))
  await db.execute(delete(seed.ProviderModelMapping).where(seed.ProviderModelMapping.provider_id==seed.ids['provider']))
  await db.execute(delete(seed.Provider).where(seed.Provider.id==seed.ids['provider']))
  await db.execute(delete(seed.LogicalModel).where(seed.LogicalModel.name.in_([seed.NAME,seed.EMBED])))
 from app.core.redis import redis_client
 keys=[k async for k in redis_client.scan_iter(match=f'sticky:{seed.ids["key"]}:*')]
 if keys:await redis_client.delete(*keys)
 await redis_client.aclose()
 # seed cleanup only knows original models; extra models have already lost group membership.
 async with seed.session_factory.begin() as db:
  await db.execute(delete(seed.LogicalModel).where(seed.LogicalModel.name.in_([seed.PREFIX+'-rerank',seed.PREFIX+'-image'])))

async def main():
 global BASE
 async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=2) as ready:
  for _ in range(60):
   try:
    response=await ready.get('/health/detail')
    if response.status_code==200:break
   except httpx.HTTPError:pass
   await asyncio.sleep(.5)
  else:raise AssertionError('application not ready')
 server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);server.daemon_threads=True;BASE='http://127.0.0.1:'+str(server.server_port);seed.URL=BASE;threading.Thread(target=server.serve_forever,daemon=True).start()
 await seed.seed()
 async with seed.session_factory.begin() as db:
  role=await db.scalar(select(seed.Role.id).where(seed.Role.code=='admin'));u=await db.get(seed.User,seed.ids['user']);u.role='admin';u.role_id=role;u.password_hash=await hash_password(PASSWORD)
  for position,kind in [(3,'rerank'),(4,'image')]:
   name=seed.PREFIX+'-'+kind;db.add(seed.LogicalModel(name=name,model_type=kind));await db.flush();db.add(seed.ProviderModelMapping(provider_id=seed.ids['provider'],logical_model=name,upstream_model='private-upstream-model',model_type=kind));db.add(seed.ModelGroupModel(model_group_id=seed.ids['mg'],logical_model=name,position=position))
 async with httpx.AsyncClient(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+seed.KEY},timeout=20,event_hooks={'response':[capture]}) as client:
  try:
   login=await client.post('/api/auth/login',json={'username':seed.PREFIX,'password':PASSWORD});assert login.status_code==200;admin={'Authorization':'Bearer '+login.json()['data']['access_token']}
   cases=[('responses',{'model':seed.NAME,'input':'你好','max_output_tokens':16},6),('messages',{'model':seed.NAME,'messages':[{'role':'user','content':'你好'}],'max_tokens':16},9),('embeddings',{'model':seed.EMBED,'input':['你好','hello']},4),('rerank',{'model':seed.PREFIX+'-rerank','query':'你好','documents':['hello','你好'],'top_n':2},None),('images/generations',{'model':seed.PREFIX+'-image','prompt':'hello','size':'1024x1024'},6)]
   for op,payload,tokens in cases:
    await configure('anthropic' if op=='messages' else 'openai');r=await client.post('/v1/'+op,json=payload,headers={'x-api-key':seed.KEY} if op=='messages' else {})
    assert r.status_code==200,(op,r.status_code,r.text[:250]);data=r.json();assert data.get('model',payload['model'])==payload['model']
    row=await record(r.headers['X-Request-ID']);assert row.total_tokens==tokens,(op,row.total_tokens);assert row.operation==('images' if op.startswith('images') else op)
   print('PASS1: five native HTTP protocols, proper auth/upstream model rewrite, reported usage/cache and missing rerank usage')
   for op,payload,_ in cases[:2]:
    await configure('anthropic' if op=='messages' else 'openai')
    async with client.stream('POST','/v1/'+op,json={**payload,'stream':True}) as r:
     assert r.status_code==200;begin=time.monotonic();lines=r.aiter_lines();first=await anext(lines);assert time.monotonic()-begin<.05
     tail='\n'.join([line async for line in lines]);assert '你好' in tail and ('response.completed' if op=='responses' else 'message_stop') in tail
    row=await record(r.headers['X-Request-ID']);assert row.status=='success' and row.ttft_ms>=50 and row.total_tokens==(9 if op=='messages' else 6)
   print('PASS2: incremental native Responses/Messages SSE, fragmented UTF8/CRLF, usage/TTFT/terminal records')
   chat={'model':seed.NAME,'messages':[{'role':'system','content':'system'},{'role':'user','content':'你好'}],'max_tokens':16}
   message=cases[1][1]
   for op,payload,protocol in [('chat/completions',chat,'anthropic'),('messages',message,'openai')]:
    await configure(protocol);r=await client.post('/v1/'+op,json=payload);assert r.status_code==200,(op,r.text[:250]);assert r.json().get('object')=='chat.completion' if op.startswith('chat') else r.json()['type']=='message'
    async with client.stream('POST','/v1/'+op,json={**payload,'stream':True}) as r:
     assert r.status_code==200;raw=(await r.aread()).decode();assert '你好' in raw and ('[DONE]' if op.startswith('chat') else 'message_stop') in raw and 'private-upstream-model' not in raw
    row=await record(r.headers['X-Request-ID']);assert row.status=='success',row.error_code
    # Unsafe semantics must fail before network/Token reservation.
    before=len(calls);r=await client.post('/v1/'+op,json={**payload,**({'response_format':{'type':'json_object'}} if op.startswith('chat') else {'thinking':{'type':'enabled','budget_tokens':8}})})
    assert r.status_code==400 and r.json()['error']['code']=='PROTOCOL_ERROR' and len(calls)==before
   print('PASS3: bidirectional nonstream/incremental conversion, model hiding and PROTOCOL_ERROR before upstream')
   for op,payload,_ in cases[:2]:
    protocol='anthropic' if op=='messages' else 'openai'
    for mode,code in [('eof','UPSTREAM_STREAM_INTERRUPTED'),('error','UPSTREAM_STREAM_ERROR')]+([('failed','UPSTREAM_STREAM_ERROR')] if op=='responses' else []):
     await configure(protocol,mode);r=await client.post('/v1/'+op,json={**payload,'stream':True});raw=r.text;assert code in raw and seed.KEY not in raw and seed.SECRET not in raw
     row=await record(r.headers['X-Request-ID']);assert row.status=='failure' and row.error_code==code
     if mode=='failed':assert row.total_tokens==5
    await configure(protocol,'cancel')
    async with client.stream('POST','/v1/'+op,json={**payload,'stream':True}) as r:
     lines=r.aiter_lines();await anext(lines)
    row=await record(r.headers['X-Request-ID']);assert row.status=='client_cancelled',(row.status,row.error_code)
   await configure('openai','failed');r=await client.post('/v1/responses',json=cases[0][1]);assert r.status_code==502 and r.json()['error']['code']=='UPSTREAM_RESPONSE_FAILED'
   row=await record(r.headers['X-Request-ID']);assert row.total_tokens==5 and row.status=='failure'
   from app.core.redis import redis_client
   await asyncio.sleep(.1)
   for key in ('gateway:concurrency','gateway:streaming','gateway:queue'):assert await redis_client.zcard(key)==0,key
   print('PASS4: EOF/error/cancellation safety, sanitized native errors and resource/stream lease release')
   await configure()
   for op,payload,_ in cases:
    before=len(calls);r=await client.post('/v1/'+op,json={**payload,'model':seed.EMBED if op!='embeddings' else seed.NAME});assert r.status_code==400 and r.json()['error']['code']=='MODEL_TYPE_UNSUPPORTED' and len(calls)==before
   async with httpx.AsyncClient(base_url='http://127.0.0.1',event_hooks={'response':[capture]}) as anon:
    r=await anon.post('/v1/messages',json=message,headers={'x-api-key':seed.KEY});assert r.status_code==200
    r=await anon.post('/v1/messages',json=message,headers={'x-api-key':seed.KEY,'Authorization':'Bearer sk-hd-wrong'});assert r.status_code==401 and r.json()['type']=='error'
    r=await anon.post('/v1/responses',json=cases[0][1]);assert r.status_code==401
    r=await anon.post('/v1/messages',json={'model':seed.NAME});assert r.status_code==422 and r.json()['type']=='error'
   for op,payload,_ in cases:
    await configure('anthropic' if op=='messages' else 'openai','invalid');r=await client.post('/v1/'+op,json=payload);assert r.status_code==502,(op,r.status_code,r.text)
   print('PASS5: model-type gate, missing/conflicting auth, native error envelope and malformed upstream rejection')
   # Place one actual terminal fact in a completed hour to exercise operation-specific aggregate reads.
   historical=GatewayContext('req_stage15_historic_'+seed.PREFIX,'responses',seed.NAME,{'input':'never persisted'});historical.user=u;historical.group=await get_group();historical.received_at=now()-timedelta(hours=2);historical.usage_snapshot={'prompt_tokens':4,'completion_tokens':2,'total_tokens':6};seen.add(historical.request_id);await call_log.write(historical,'success')
   query={'model':seed.NAME,'operation':'responses','start':(now()-timedelta(days=2)).isoformat(),'end':now().isoformat(),'grain':'hour'}
   data=(await client.get('/api/admin/usage',params=query,headers=admin)).json()['data']
   async with seed.session_factory() as db:
    rows=(await db.scalars(select(CallLog).where(CallLog.request_model==seed.NAME,CallLog.operation=='responses',CallLog.request_id.in_(seen)))).all()
   assert data['summary']['requests']==len(rows),(data['summary']['requests'],len(rows));assert data['summary']['total_tokens']==sum(x.total_tokens or 0 for x in rows)
   listing=await client.get('/api/admin/call-logs',params={'operation':'responses','model':seed.NAME},headers=admin);assert listing.status_code==200 and all(x['operation']=='responses' for x in listing.json()['data']['items'])
   async with seed.session_factory() as db:
    raw=json.dumps([call_log.snapshot(historical,'success',None)],default=str)
    assert seed.KEY not in raw and seed.SECRET not in raw and 'never persisted' not in raw
   print('PASS6: operation-filtered hourly aggregates and bounded-edge facts match real terminal records')
   await seed.change(seed.UserGroup,'ug',max_concurrency=1,quota_limit=100000)
   await configure('openai','cancel')
   payload={**cases[0][1],'stream':True}
   async with client.stream('POST','/v1/responses',json=payload) as hold:
    lines=hold.aiter_lines();await anext(lines)
    queued=asyncio.create_task(client.post('/v1/responses',json=payload))
    for _ in range(60):
     live=(await client.get('/api/admin/dashboard',headers=admin)).json()['data']['live']
     if live['queued']==1:break
     await asyncio.sleep(.03)
    assert (live['active'],live['streaming'],live['queued'])==(1,1,1),live
    async with seed.session_factory() as db:
     assert await db.scalar(select(func.count()).select_from(QuotaReservation).where(QuotaReservation.group_id==seed.ids['ug'],QuotaReservation.state=='active'))==1
    queued.cancel()
    try:await queued
    except asyncio.CancelledError:pass
   await record(hold.headers['X-Request-ID'])
   for _ in range(60):
    if all([await redis_client.zcard(key)==0 for key in ('gateway:concurrency','gateway:streaming','gateway:queue')]):break
    await asyncio.sleep(.05)
   assert await redis_client.zcard('gateway:queue')==0
   print('PASS7: Responses participates in global/group/key/Provider admission, real queue, streaming Dashboard and finite quota reservations')

  finally:
   await cleanup();await seed.engine.dispose();server.shutdown();server.server_close()
async def get_group():
 async with seed.session_factory() as db:return await db.get(seed.UserGroup,seed.ids['ug'])
if __name__=='__main__':asyncio.run(main())

