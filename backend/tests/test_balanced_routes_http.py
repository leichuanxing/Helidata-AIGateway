"""Real isolated HTTP/SQL/Redis flows with a local, non-billable upstream."""
import asyncio,json,os,threading,time,unittest
from pathlib import Path
from uuid import uuid4
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import httpx

@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','disposable container only')
class BalancedHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_crud_protocols_nodes_failover_authorization_and_monitoring(self):
        ident=os.environ.get('AUDIT_CONTAINER_ID','');self.assertGreaterEqual(len(ident),12);self.assertEqual(os.environ.get('HOSTNAME','')[:12],ident[:12])
        calls=[];modes={};active={};peaks={};seen_content={};lock=threading.Lock()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def answer(self,status,body):
                data=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers()
                try:self.wfile.write(data)
                except (BrokenPipeError,ConnectionResetError):pass
            def do_GET(self):self.answer(200,{'data':[{'id':'a'},{'id':'b'}]})
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));node=body['model'];mode=modes.get(node,'ok')
                with lock:calls.append((node,self.path,bool(body.get('stream'))));seen_content[node]=body.get('messages')
                if mode=='rate':return self.answer(429,{'error':{'message':'fixture rate'}})
                if mode=='error':return self.answer(503,{'error':{'message':'fixture unavailable'}})
                if mode=='stall':time.sleep(1.3)
                if mode=='slow':
                    with lock:active[node]=active.get(node,0)+1;peaks[node]=max(peaks.get(node,0),active[node])
                    time.sleep(.15)
                    with lock:active[node]-=1
                if self.path.endswith('/embeddings'):return self.answer(200,{'object':'list','data':[{'object':'embedding','index':0,'embedding':[1.0,0.0]}],'usage':{'prompt_tokens':1,'total_tokens':1}})
                if self.path.endswith('/rerank'):return self.answer(200,{'results':[{'index':0,'relevance_score':.9}],'usage':{'total_tokens':1}})
                if self.path.endswith('/images/generations'):return self.answer(200,{'created':1,'data':[{'b64_json':'aGVsbG8='}]})
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
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=30) as admin:
                login=await admin.post('/api/auth/login',json={'username':'admin','password':Path('/data/config/audit-password.txt').read_text().strip()});self.assertEqual(login.status_code,200)
                admin.headers['Authorization']='Bearer '+login.json()['data']['access_token']
                async def api(method,path,body=None,status=200):
                    r=await admin.request(method,'/api/'+path,json=body);self.assertEqual(r.status_code,status,r.text[:300]);return r.json().get('data')
                async def log(request_id):
                    for _ in range(40):
                        r=await admin.get('/api/admin/call-logs/'+request_id)
                        if r.status_code==200:return r.json()['data']
                        self.assertEqual(r.status_code,404);await asyncio.sleep(.05)
                    self.fail('terminal log not persisted')
                prefix='independent-'+uuid4().hex[:10];providers=[];mapping_ids=[]
                for node in ('a','b'):
                    provider=await api('POST','admin/providers',{'name':prefix+node,'provider_type':'custom_openai','protocol':'openai','protocol_type':'text',
                        'base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'fixture-only','max_concurrency':2,
                        'protocol_config':{p:{'path_prefix':'','auth_type':'x-api-key' if p=='anthropic-messages' else 'bearer'} for p in ('openai-completions','openai-responses','anthropic-messages')},
                        'model_mappings':[{'logical_model':prefix+node,'upstream_model':node,'model_type':'text'}]},201)
                    providers.append(provider);mapping_ids.append((await api('GET',f"admin/providers/{provider['id']}/model-mappings"))[0]['id'])
                body={'name':prefix,'model_name':prefix+'-unified','model_type':'text','strategy':'round_robin','health_interval':3600,'cooldown_seconds':1,'failure_threshold':1,
                    'max_retries':1,'timeout_seconds':5,'nodes':[{'mapping_id':m,'max_concurrency':1} for m in mapping_ids]}
                created=await api('POST','admin/balance-routes',body,201);route_path='admin/balance-routes/'+str(created['id'])
                async def save():
                    current=await api('GET',route_path);body['expected_config_version']=current['config_version'];await api('PUT',route_path,body)
                secret=(await api('POST','portal/api-keys',{'name':prefix},201))['secret']
                async with httpx.AsyncClient(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+secret},timeout=30) as client:
                    async def chat(stream=False,text='hello'):
                        return await client.post('/v1/chat/completions',json={'model':body['model_name'],'messages':[{'role':'user','content':text}],'max_tokens':8,'stream':stream})
                    for _ in range(6):
                        r=await chat();self.assertEqual(r.status_code,200,r.text[:200]);self.assertEqual(r.json()['model'],body['model_name'])
                    self.assertEqual([c[0] for c in calls],['a','b']*3)
                    body['strategy']='weighted_round_robin';body['nodes'][1]['weight']=3;await save();start=len(calls)
                    for _ in range(8):self.assertEqual((await chat()).status_code,200)
                    self.assertEqual([c[0] for c in calls[start:]].count('b'),6)
                    for path,payload,terminal in (('/v1/chat/completions',{'messages':[{'role':'user','content':'hello'}],'max_tokens':8},'[DONE]'),('/v1/responses',{'input':'hello','max_output_tokens':8},'response.completed'),('/v1/messages',{'messages':[{'role':'user','content':'hello'}],'max_tokens':8},'message_stop')):
                        for stream in (False,True):
                            r=await client.post(path,json={'model':body['model_name'],**payload,'stream':stream});self.assertEqual(r.status_code,200,r.text[:200])
                            if stream:self.assertIn(terminal,r.text)
                    body['strategy']='priority';body['nodes'][1]['priority']=10;await save()
                    modes['a']='rate';start=len(calls);r=await chat();self.assertEqual(r.status_code,200);self.assertEqual([c[0] for c in calls[start:]],['a','b'])
                    attempts=(await log(r.headers['x-request-id']))['trace']['attempts'];self.assertEqual(attempts[-1]['retry_count'],1);self.assertEqual(attempts[-1]['switch_reason'],'UPSTREAM_RATE_LIMITED')
                    self.assertEqual(attempts[-1]['balance_route_id'],created['id'])
                    modes['a']='ok';await asyncio.sleep(1.1);start=len(calls);self.assertEqual((await chat()).status_code,200);self.assertEqual(calls[start][0],'a')
                    modes['a']='error';start=len(calls);self.assertEqual((await chat()).status_code,502);self.assertEqual(len(calls)-start,1)
                    detail=await api('GET',route_path);node_a=detail['nodes'][0]
                    modes['a']='ok';checked=await api('POST',route_path+f"/nodes/{node_a['id']}/check",{});self.assertTrue(checked['success']);self.assertFalse(checked['generation_tested'])
                    body.update(retry_uncertain=True,timeout_seconds=1);await save();modes['a']='stall';r=await chat();self.assertEqual(r.status_code,200)
                    self.assertEqual((await log(r.headers['x-request-id']))['trace']['attempts'][0]['code'],'UPSTREAM_TIMEOUT')
                    modes['a']='ok';await api('POST',route_path+f"/nodes/{node_a['id']}/check",{})
                    body.update(retry_uncertain=False,timeout_seconds=5);await save();modes['a']='broken';start=len(calls);r=await chat(True);self.assertEqual(r.status_code,200);await log(r.headers['x-request-id']);self.assertEqual(len(calls)-start,1)
                    modes['a']='ok';await api('POST',route_path+f"/nodes/{node_a['id']}/check",{})
                    body['strategy']='least_concurrency';body['max_concurrency']=2;await save();modes.update(a='slow',b='slow')
                    parallel=await asyncio.gather(*(chat() for _ in range(8)));self.assertTrue(all(r.status_code==200 for r in parallel));self.assertLessEqual(max(peaks.values()),1)
                    detail=await api('GET',route_path);self.assertEqual(detail['current_concurrency'],0);self.assertTrue(all(n['current_concurrency']==0 and n['requests']>0 for n in detail['nodes']))
                    body['nodes'][0]['status']='disabled';await save();start=len(calls);self.assertEqual((await chat()).status_code,200);self.assertEqual(calls[start][0],'b')
                    self.assertEqual((await api('GET',f"admin/providers/{providers[0]['id']}"))['status'],'enabled')
                    body['nodes'][0]['status']='enabled';body['strategy']='random';await save();self.assertEqual((await chat()).status_code,200)
                    body.update(strategy='priority',health_interval=10);await save();modes['a']='error'
                    self.assertEqual((await chat()).status_code,502);modes['a']='ok'
                    for _ in range(30):
                        recovered=(await api('GET',route_path))['nodes'][0]
                        if recovered['health_status']=='healthy' and recovered['last_checked_at']:break
                        await asyncio.sleep(.5)
                    self.assertEqual(recovered['health_status'],'healthy');self.assertIsNotNone(recovered['last_checked_at'])
                    stale=await admin.put('/api/'+route_path,json={**body,'expected_config_version':0});self.assertEqual(stale.status_code,409)
                    names=[m['id'] for m in (await client.get('/v1/models')).json()['data']];self.assertIn(body['model_name'],names)
                    forbidden=await client.get('/api/admin/balance-routes');self.assertEqual(forbidden.status_code,401)
                    authorized_group=await api('POST','admin/model-groups',{'name':prefix,'protocol_type':'text','logical_models':[body['model_name']]},201)
                    user_group=await api('POST','admin/user-groups',{'name':prefix,'model_access':'selected','model_group_ids':[authorized_group['id']]},201)
                    await api('POST','admin/users',{'username':prefix,'password':'Fixture-Initial26!Aa','user_group_id':user_group['id']},201)
                    async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=30) as ordinary:
                        signed=await ordinary.post('/api/auth/login',json={'username':prefix,'password':'Fixture-Initial26!Aa'});self.assertEqual(signed.status_code,200)
                        ordinary.headers['Authorization']='Bearer '+signed.json()['data']['access_token']
                        changed=await ordinary.post('/api/auth/change-password',json={'old_password':'Fixture-Initial26!Aa','new_password':'Fixture-Replaced26!Bb'});self.assertEqual(changed.status_code,200)
                        signed=await ordinary.post('/api/auth/login',json={'username':prefix,'password':'Fixture-Replaced26!Bb'});ordinary.headers['Authorization']='Bearer '+signed.json()['data']['access_token']
                        self.assertEqual((await ordinary.get('/api/admin/balance-routes')).status_code,403)
                        own=await ordinary.post('/api/portal/api-keys',json={'name':prefix});self.assertEqual(own.status_code,201)
                        async with httpx.AsyncClient(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+own.json()['data']['secret']},timeout=30) as restricted:
                            payload={'model':body['model_name'],'messages':[{'role':'user','content':'hello'}],'max_tokens':8}
                            self.assertEqual((await restricted.post('/v1/chat/completions',json=payload)).status_code,200)
                            denied=await restricted.post('/v1/chat/completions',json={**payload,'model':prefix+'a'});self.assertEqual(denied.status_code,403)
                            await api('PUT',f"admin/user-groups/{user_group['id']}",{'name':prefix,'model_access':'selected','model_group_ids':[]})
                            self.assertEqual((await restricted.post('/v1/chat/completions',json=payload)).status_code,403)
                    await api('DELETE',f"admin/model-groups/{authorized_group['id']}")
                    for kind,category,protocol,path,payload in (
                        ('multimodal','multimodal','openai-completions','/v1/chat/completions',{'messages':[{'role':'user','content':[{'type':'text','text':'describe'},{'type':'image_url','image_url':{'url':'https://fixture.invalid/image.png'}}]}],'max_tokens':8}),
                        ('embedding','vector','openai-embeddings','/v1/embeddings',{'input':'hello'}),
                        ('rerank','rerank','openai-rerank','/v1/rerank',{'query':'q','documents':['doc']}),
                        ('image','image','openai-images','/v1/images/generations',{'prompt':'a mountain'})):
                        p=await api('POST','admin/providers',{'name':prefix+kind,'provider_type':'custom_openai','protocol':'openai','protocol_type':category,
                            'base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'fixture-only','protocol_config':{protocol:{}},
                            'model_mappings':[{'logical_model':prefix+kind,'upstream_model':kind,'model_type':kind}]},201)
                        if kind=='rerank':
                            self.assertEqual(p['protocol_type'],'rerank')
                            saved=await api('PATCH',f"admin/providers/{p['id']}",{'remark':'rerank category regression','expected_config_version':p['config_version']})
                            self.assertEqual(saved['protocol_type'],'rerank')
                            found=await api('GET','admin/providers?protocol_type=rerank&q='+prefix)
                            self.assertIn(p['id'],[item['id'] for item in found['items']])
                        mid=(await api('GET',f"admin/providers/{p['id']}/model-mappings"))[0]['id']
                        other=await api('POST','admin/balance-routes',{'name':prefix+kind,'model_name':prefix+'-route-'+kind,'model_type':kind,'nodes':[{'mapping_id':mid}],'health_interval':3600},201)
                        result=await client.post(path,json={'model':other['model_name'],**payload});self.assertEqual(result.status_code,200,result.text[:200])
                        if kind=='multimodal':self.assertEqual(seen_content[kind][0]['content'][1]['type'],'image_url')
                        self.assertEqual((await log(result.headers['x-request-id']))['trace']['attempts'][-1]['balance_route_id'],other['id'])
                        await api('DELETE','admin/balance-routes/'+str(other['id']))
                    policy=await api('POST','admin/compliance/policies',{'name':prefix,'status':'enabled','action':'block','models':[prefix+'a',prefix+'b']})
                    await api('POST','admin/compliance/words',{'pattern':'blocked','policy_id':policy['id']});start=len(calls);r=await chat(text='blocked')
                    self.assertEqual(r.status_code,403);self.assertEqual(len(calls),start)
                    group=await api('POST','admin/model-groups',{'name':prefix,'protocol_type':'text','logical_models':[body['model_name']]},201)
                    await api('DELETE',route_path,status=409);await api('DELETE',f"admin/model-groups/{group['id']}")
                    await api('DELETE',route_path);self.assertNotIn(body['model_name'],[m['id'] for m in (await client.get('/v1/models')).json()['data']])
                    self.assertEqual((await api('GET',f"admin/providers/{providers[0]['id']}"))['status'],'enabled')
                    print('PASS independent route real HTTP: CRUD, 5 strategies, 3 native protocols JSON/SSE, timeout/rate failover, cooldown recovery, probe, node isolation, concurrency, target compliance, version guard, catalog and delete guard')
        finally:server.shutdown();server.server_close()
