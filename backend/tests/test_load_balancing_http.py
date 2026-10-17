"""End-to-end HTTP/Redis/PostgreSQL checks using a local protocol server."""
import asyncio,json,os,threading,time,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4
import httpx

@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','disposable container only')
class BalancingHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_protocols_distribution_failover_recovery_and_stream_guard(self):
        ident=os.environ.get('AUDIT_CONTAINER_ID','')
        self.assertGreaterEqual(len(ident),12);self.assertEqual(os.environ.get('HOSTNAME','')[:12],ident[:12])
        calls=[];modes={};active={};peak={};lock=threading.Lock()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def answer(self,status,body):
                data=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(data)));self.end_headers()
                try:self.wfile.write(data)
                except (BrokenPipeError,ConnectionResetError):pass
            def do_GET(self):self.answer(200,{'data':[{'id':'a'},{'id':'b'}]})
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));node=body['model'];mode=modes.get(node,'ok')
                with lock:calls.append((node,self.path,bool(body.get('stream'))))
                if mode=='auth':return self.answer(401,{'error':{'message':'fixture auth'}})
                if mode=='rate':return self.answer(429,{'error':{'message':'fixture rate'}})
                if mode=='error':return self.answer(503,{'error':{'message':'fixture unavailable'}})
                if self.path.endswith('/embeddings'):
                    return self.answer(200,{'object':'list','model':node,'data':[{'object':'embedding','index':0,'embedding':[1.0,0.0]}],'usage':{'prompt_tokens':1,'total_tokens':1}})
                if mode=='stall':time.sleep(1.3)
                if mode=='slow':
                    with lock:active[node]=active.get(node,0)+1;peak[node]=max(peak.get(node,0),active[node])
                    time.sleep(.15)
                    with lock:active[node]-=1
                chat={'id':'chat-'+node,'object':'chat.completion','created':1,'model':node,'choices':[{'index':0,'message':{'role':'assistant','content':node},'finish_reason':'stop'}],'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}
                response={'id':'resp-'+node,'object':'response','model':node,'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':node}]}],'usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2}}
                message={'id':'msg-'+node,'type':'message','role':'assistant','model':node,'content':[{'type':'text','text':node}],'stop_reason':'end_turn','usage':{'input_tokens':1,'output_tokens':1}}
                if not body.get('stream'):return self.answer(200,response if self.path.endswith('/responses') else message if self.path.endswith('/messages') else chat)
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                def frame(kind,data):self.wfile.write(((('event: '+kind+'\n') if kind else '')+'data: '+(data if isinstance(data,str) else json.dumps(data))+'\n\n').encode());self.wfile.flush()
                if self.path.endswith('/responses'):
                    frame('response.created',{'type':'response.created','response':{'object':'response'}})
                    frame('response.output_text.delta',{'type':'response.output_text.delta','delta':node})
                    frame('response.completed',{'type':'response.completed','response':response})
                elif self.path.endswith('/messages'):
                    frame('message_start',{'type':'message_start','message':{**message,'content':[],'stop_reason':None}})
                    frame('content_block_start',{'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}})
                    frame('content_block_delta',{'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':node}})
                    frame('content_block_stop',{'type':'content_block_stop','index':0})
                    frame('message_delta',{'type':'message_delta','delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':1}})
                    frame('message_stop',{'type':'message_stop'})
                else:
                    frame('',{'id':'chunk','object':'chat.completion.chunk','created':1,'model':node,'choices':[{'index':0,'delta':{'content':node},'finish_reason':None}]})
                    if mode!='broken':frame('','[DONE]')
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=30) as admin:
                login=await admin.post('/api/auth/login',json={'username':'admin','password':Path('/data/config/audit-password.txt').read_text().strip()})
                self.assertEqual(login.status_code,200);admin.headers['Authorization']='Bearer '+login.json()['data']['access_token']
                async def management(method,path,body=None,status=200):
                    r=await admin.request(method,'/api/'+path,json=body);self.assertEqual(r.status_code,status,r.text[:300]);return r.json()['data']
                async def terminal_log(request_id):
                    for _ in range(40):
                        r=await admin.get('/api/admin/call-logs/'+request_id)
                        if r.status_code==200:return r.json()['data']
                        self.assertEqual(r.status_code,404);await asyncio.sleep(.05)
                    self.fail('stream terminal log was not persisted')
                model='lb-'+uuid4().hex[:10];providers=[]
                for node in ('a','b'):
                    providers.append(await management('POST','admin/providers',{'name':model+node,'provider_type':'custom_openai','protocol':'openai','protocol_type':'text',
                        'base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'fixture-only','max_concurrency':2,
                        'protocol_config':{p:{'path_prefix':'','auth_type':'x-api-key' if p=='anthropic-messages' else 'bearer'} for p in ('openai-completions','openai-responses','anthropic-messages')},
                        'model_mappings':[{'logical_model':model,'upstream_model':node,'model_type':'text'}]},201))
                group_body={'name':model,'protocol_type':'text','logical_models':[model],'balancing_strategy':'round_robin','max_retries':1}
                group=await management('POST','admin/model-groups',group_body,201);group_path='admin/model-groups/'+str(group['id'])
                secret=(await management('POST','portal/api-keys',{'name':model},201))['secret']
                async with httpx.AsyncClient(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+secret},timeout=30) as client:
                    async def chat(stream=False):
                        return await client.post('/v1/chat/completions',json={'model':model,'messages':[{'role':'user','content':'hello'}],'max_tokens':8,'stream':stream})
                    for _ in range(6):self.assertEqual((await chat()).status_code,200)
                    self.assertEqual([c[0] for c in calls],['a','b']*3)
                    group_body.update(balancing_strategy='weighted_round_robin',node_weights={str(providers[0]['id']):1,str(providers[1]['id']):3})
                    await management('PUT',group_path,group_body);start=len(calls)
                    for _ in range(8):self.assertEqual((await chat()).status_code,200)
                    self.assertEqual([x[0] for x in calls[start:]].count('b'),6)
                    for path,payload,terminal in (
                        ('/v1/chat/completions',{'messages':[{'role':'user','content':'hello'}],'max_tokens':8},'[DONE]'),
                        ('/v1/responses',{'input':'hello','max_output_tokens':8},'response.completed'),
                        ('/v1/messages',{'messages':[{'role':'user','content':'hello'}],'max_tokens':8},'message_stop')):
                        for stream in (False,True):
                            r=await client.post(path,json={'model':model,**payload,'stream':stream});self.assertEqual(r.status_code,200,r.text[:200])
                            if stream:self.assertIn(terminal,r.text)
                    await management('PATCH','admin/providers/'+str(providers[1]['id']),{'priority':10})
                    modes['a']='auth';start=len(calls);r=await chat();self.assertEqual(r.status_code,200)
                    self.assertEqual([x[0] for x in calls[start:]],['a','b'])
                    log=(await terminal_log(r.headers['x-request-id']))['trace']['attempts']
                    self.assertEqual(log[-1]['retry_count'],1);self.assertEqual(log[-1]['switch_reason'],'UPSTREAM_AUTH_FAILED')
                    # Probe success recovers the quarantined account without generation.
                    modes['a']='ok';probe=await management('POST','admin/providers/'+str(providers[0]['id'])+'/test')
                    self.assertTrue(probe['success']);start=len(calls);self.assertEqual((await chat()).status_code,200);self.assertEqual(calls[start][0],'a')
                    await management('PATCH','admin/providers/'+str(providers[0]['id']),{'base_url':'http://127.0.0.1:1/v1'})
                    start=len(calls);r=await chat();self.assertEqual(r.status_code,200);self.assertEqual([x[0] for x in calls[start:]],['b'])
                    attempts=(await terminal_log(r.headers['x-request-id']))['trace']['attempts']
                    self.assertEqual(attempts[0]['code'],'UPSTREAM_NETWORK_ERROR');self.assertEqual(len(attempts),2)
                    await management('PATCH','admin/providers/'+str(providers[0]['id']),{'base_url':f'http://127.0.0.1:{server.server_port}/v1'})
                    # An upstream 503 is uncertain by default: never silently replay.
                    modes['a']='error';start=len(calls);r=await chat();self.assertEqual(r.status_code,502);self.assertEqual(len(calls)-start,1)
                    modes['a']='ok';await management('POST','admin/providers/'+str(providers[0]['id'])+'/test')
                    group_body['retry_uncertain']=True;await management('PUT',group_path,group_body)
                    modes['a']='error';start=len(calls);r=await chat();self.assertEqual(r.status_code,200);self.assertEqual([x[0] for x in calls[start:]],['a','b'])
                    modes['a']='ok';await management('POST','admin/providers/'+str(providers[0]['id'])+'/test')
                    group_body['attempt_timeout']=1;await management('PUT',group_path,group_body)
                    modes['a']='stall';r=await chat();self.assertEqual(r.status_code,200)
                    timed=(await terminal_log(r.headers['x-request-id']))['trace']['attempts']
                    self.assertEqual(timed[0]['code'],'UPSTREAM_TIMEOUT');self.assertEqual(len(timed),2)
                    modes['a']='ok';group_body['attempt_timeout']=120
                    group_body['max_retries']=0;await management('PUT',group_path,group_body)
                    modes['a']='error';start=len(calls);self.assertEqual((await chat()).status_code,502);self.assertEqual(len(calls)-start,1)
                    modes['a']='ok';await management('POST','admin/providers/'+str(providers[0]['id'])+'/test')
                    group_body.update(max_retries=1,retry_uncertain=False);await management('PUT',group_path,group_body)
                    # A broken stream must produce one failed attempt, not a second answer.
                    modes['a']='broken';start=len(calls);r=await chat(True);self.assertEqual(r.status_code,200);self.assertEqual(len(calls)-start,1)
                    trace=(await terminal_log(r.headers['x-request-id']))['trace'];self.assertEqual(len(trace['attempts']),1)
                    modes.update(a='slow',b='slow');await management('PATCH','admin/providers/'+str(providers[1]['id']),{'priority':0})
                    group_body.update(balancing_strategy='least_concurrency');await management('PUT',group_path,group_body)
                    results=await asyncio.gather(*(chat() for _ in range(8)))
                    self.assertTrue(all(r.status_code==200 for r in results));self.assertLessEqual(max(peak.values()),2)
                    metrics=await management('GET',group_path+'/nodes');self.assertEqual(len(metrics['items']),2)
                    self.assertTrue(all(n['current_concurrency']==0 for n in metrics['items']))
                    self.assertTrue(all(n['requests']>0 and n['average_latency_ms'] is not None for n in metrics['items']))
                    self.assertEqual((await management('GET',group_path))['balancing_strategy'],'least_concurrency')
                    embedding=model+'-embed'
                    await management('POST','admin/providers',{'name':embedding,'provider_type':'custom_openai','protocol':'openai','protocol_type':'vector',
                        'base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'fixture-only',
                        'protocol_config':{'openai-embeddings':{'path_prefix':''}},
                        'model_mappings':[{'logical_model':embedding,'upstream_model':'vector','model_type':'embedding'}]},201)
                    complex_group=await management('POST','admin/model-groups',{**group_body,'name':model+'-complex','balancing_strategy':'weighted_round_robin'},201)
                    virtual=model+'-virtual'
                    await management('POST','admin/smart-route/configs',{'virtual_model':virtual,'embedding_model':embedding,
                        'simple_model_group':group['id'],'complex_model_group':complex_group['id'],'status':'enabled'},201)
                    routed=await client.post('/v1/chat/completions',json={'model':virtual,'messages':[{'role':'user','content':'hello'}],'max_tokens':8})
                    self.assertEqual(routed.status_code,200,routed.text[:200])
                    routed_log=await terminal_log(routed.headers['x-request-id'])
                    self.assertEqual(routed_log['trace']['attempts'][-1]['balancing_strategy'],'least_concurrency')
                    self.assertEqual(routed_log['trace']['attempts'][-1]['model_group_id'],group['id'])
                    self.assertTrue(routed_log['trace']['smart_routing']['embedding_request_id'])
                    fallback=model+'-fallback'
                    await management('POST','admin/providers',{'name':fallback,'provider_type':'custom_openai','protocol':'openai','protocol_type':'text',
                        'base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'fixture-only',
                        'protocol_config':{'openai-completions':{'path_prefix':''}},
                        'model_mappings':[{'logical_model':fallback,'upstream_model':'c','model_type':'text'}]},201)
                    group_body.update(logical_models=[model,fallback],max_retries=2);await management('PUT',group_path,group_body)
                    policy=await management('POST','admin/compliance/policies',{'name':fallback,'status':'enabled','action':'block','models':[fallback]})
                    await management('POST','admin/compliance/words',{'pattern':'hello','policy_id':policy['id']})
                    modes.update(a='auth',b='auth');start=len(calls);blocked=await chat()
                    self.assertEqual(blocked.status_code,403);self.assertEqual(blocked.json()['error']['code'],'CONTENT_BLOCKED')
                    self.assertEqual(len(calls)-start,2);self.assertNotIn('c',[x[0] for x in calls[start:]])
                    metrics=await management('GET',group_path+'/nodes');self.assertTrue(all(n['current_concurrency']==0 for n in metrics['items']))
                    print('PASS load balancing HTTP: RR/1:3 WRR, 3 protocols JSON+SSE, auth failover, probe recovery, uncertain-error guard, broken-stream guard, 8 concurrent requests, metrics persistence')
        finally:
            server.shutdown();server.server_close()
