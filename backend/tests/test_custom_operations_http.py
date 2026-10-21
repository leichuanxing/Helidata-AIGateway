"""Real HTTP/SQL matrix for explicitly configured OpenAI-compatible backends."""
import json,os,threading,unittest
from pathlib import Path
from uuid import uuid4
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import httpx
@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','disposable container only')
class CustomOperationHTTPTests(unittest.IsolatedAsyncioTestCase):
 async def test_five_backends_two_operations_and_balanced_routes(self):
  ident=os.environ.get('AUDIT_CONTAINER_ID','');self.assertGreaterEqual(len(ident),12);self.assertEqual(os.environ.get('HOSTNAME','')[:12],ident[:12])
  calls=[]
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append((self.path,body))
    data={'created':1,'data':[{'url':'https://fixture.invalid/image.png'}]} if self.path=='/v1/images/generations' else {'results':[{'index':0,'relevance_score':.98}]}
    raw=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=30) as admin:
    r=await admin.post('/api/auth/login',json={'username':'admin','password':Path('/data/config/audit-password.txt').read_text().strip()});self.assertEqual(r.status_code,200);admin.headers['Authorization']='Bearer '+r.json()['data']['access_token']
    async def api(method,path,body=None,status=200):
     r=await admin.request(method,'/api/'+path,json=body);self.assertEqual(r.status_code,status,r.text[:250]);return r.json().get('data')
    types={x['code']:x for x in await api('GET','admin/providers/types')}
    key=await api('POST','portal/api-keys',{'name':'custom-matrix-'+uuid4().hex[:8]},201)
    async with httpx.AsyncClient(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+key['secret']},timeout=30) as client:
     for code in ('openai','vllm','sglang','ollama','custom_openai'):
      for kind,operation,wire in [('image','images','openai-images'),('rerank','rerank','openai-rerank')]:
       with self.subTest(provider=code,kind=kind):
        self.assertIn(wire,types[code]['supported_protocols'])
        name='custom-'+code+'-'+kind+'-'+uuid4().hex[:6]
        body={'name':name,'provider_type':code,'protocol':'openai','protocol_type':kind,'base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'fixture-only','protocol_config':{wire:{}},'model_mappings':[{'logical_model':name,'upstream_model':name+'-upstream','model_type':kind}]}
        before=len(calls);account=await api('POST','admin/providers',body,201);self.assertEqual(len(calls),before,'save must not infer')
        await api('POST','admin/model-groups',{'name':name,'protocol_type':'vector' if kind=='rerank' else kind,'logical_models':[name]},201)
        payload={'model':name,'prompt':'blue circle','n':1} if kind=='image' else {'model':name,'query':'blue','documents':['blue circle'],'top_n':1}
        path='/v1/images/generations' if kind=='image' else '/v1/rerank'
        r=await client.post(path,json=payload);self.assertEqual(r.status_code,200,r.text[:250]);self.assertEqual(calls[-1][0],path);self.assertEqual(calls[-1][1]['model'],name+'-upstream')
        log=await api('GET','admin/call-logs/'+r.headers['x-request-id']);self.assertEqual(log['provider_id'],account['id']);self.assertEqual(log['operation'],operation)
        mapping=(await api('GET',f"admin/providers/{account['id']}/model-mappings"))[0]
        route=await api('POST','admin/balance-routes',{'name':name,'model_name':name+'-balanced','model_type':kind,'nodes':[{'mapping_id':mapping['id']}],'health_interval':3600},201)
        r=await client.post(path,json={**payload,'model':name+'-balanced'});self.assertEqual(r.status_code,200,r.text[:250])
        await api('DELETE','admin/balance-routes/'+str(route['id']))
     for kind in ('image','rerank'):
      await api('POST','admin/providers',{'name':'native-'+kind,'provider_type':'ollama','protocol':'ollama','protocol_type':kind,'base_url':f'http://127.0.0.1:{server.server_port}','protocol_config':{'ollama':{}}},422)
  finally:server.shutdown();server.server_close();thread.join(timeout=2)
