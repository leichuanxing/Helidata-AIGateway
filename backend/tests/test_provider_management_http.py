"""Real gateway HTTP/SQL flow with a loopback upstream fixture, not a vendor test."""
import os,json,threading,unittest,time
from pathlib import Path
from uuid import uuid4
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import httpx


@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','disposable container only')
class ProviderManagementHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_connection_test_batch_test_and_failure(self):
        ident=os.environ.get('AUDIT_CONTAINER_ID','')
        self.assertGreaterEqual(len(ident),12)
        self.assertEqual(os.environ.get('HOSTNAME','')[:12],ident[:12])
        calls=[]
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def answer(self,status,body):
                data=json.dumps(body).encode();self.send_response(status)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
                self.end_headers();self.wfile.write(data)
            def do_GET(self):
                calls.append(('GET',self.path))
                if self.headers.get('Authorization')!='Bearer fixture-key':return self.answer(401,{'error':{'message':'invalid'}})
                if self.path.startswith('/api/v1/models'):
                    return self.answer(200,{'success':True,'output':{'models':[{'model':'fixture-rerank'}],'total':1}})
                return self.answer(200,{'object':'list','data':[{'id':'fixture','object':'model'}]})
            def do_POST(self):
                calls.append(('POST',self.path))
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if body['model']=='slow-fixture':time.sleep(61)
                return self.answer(200,{'id':'chatcmpl-fixture','object':'chat.completion','created':1,'model':body['model'],
                    'choices':[{'index':0,'message':{'role':'assistant','content':'OK'},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
        server=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=25) as c:
                login=await c.post('/api/auth/login',json={'username':'admin','password':Path('/data/config/audit-password.txt').read_text().strip()})
                self.assertEqual(login.status_code,200);c.headers['Authorization']='Bearer '+login.json()['data']['access_token']
                name='management-'+uuid4().hex[:12]
                payload={'name':name,'provider_type':'custom_openai','protocol':'openai','protocol_type':'text',
                    'base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'fixture-key',
                    'protocol_config':{'openai-completions':{'path_prefix':'','auth_type':'bearer'}},
                    'model_mappings':[{'logical_model':name+str(i),'upstream_model':'fixture','model_type':'text','status':'enabled'} for i in range(2)],
                    'default_test_model':name+'0'}
                created=await c.post('/api/admin/providers',json=payload);self.assertEqual(created.status_code,201)
                provider=created.json()['data'];route=f"/api/admin/providers/{provider['id']}"
                draft={k:v for k,v in payload.items() if k not in ('model_mappings','default_test_model')}
                discovered=await c.post('/api/admin/providers/discover-models',json=draft)
                self.assertEqual(discovered.status_code,200);self.assertEqual(discovered.json()['data']['models'],[{'id':'fixture'}])
                native_draft={**draft,'provider_type':'aliyun','protocol_type':'rerank','base_url':f'http://127.0.0.1:{server.server_port}/api/v1',
                    'protocol_config':{'openai-rerank':{}}}
                native_found=await c.post('/api/admin/providers/discover-models',json=native_draft)
                self.assertEqual(native_found.status_code,200,native_found.text[:200])
                self.assertEqual(native_found.json()['data']['models'],[{'id':'fixture-rerank'}])
                self.assertEqual(calls[-1],('GET','/api/v1/models?page_no=1&page_size=100'))
                connected=await c.post(route+'/test');self.assertEqual(connected.status_code,200)
                self.assertTrue(connected.json()['data']['success'])
                transferred=await c.patch(route,json={'provider_type':'vllm'})
                self.assertEqual(transferred.status_code,422)
                unsafe_draft={**draft,'provider_type':'vllm','provider_id':provider['id']};unsafe_draft.pop('api_key')
                previous_calls=len(calls)
                self.assertEqual((await c.post('/api/admin/providers/discover-models',json=unsafe_draft)).status_code,422)
                self.assertEqual(len(calls),previous_calls,'old credentials must not be sent after vendor change')
                consent={'models':[name+'0',name+'1'],'consent':True,'expected_config_version':provider['config_version']}
                invalid=await c.post(route+'/test-models',json={**consent,'consent':False});self.assertEqual(invalid.status_code,422)
                tested=await c.post(route+'/test-models',json=consent);self.assertEqual(tested.status_code,200)
                result=tested.json()['data'];self.assertEqual(result['success_count'],2);self.assertEqual(result['failure_count'],0)
                for row in result['results']:
                    self.assertEqual(row['total_tokens'],2)
                    self.assertEqual((await c.get('/api/admin/call-logs/'+row['request_id'])).status_code,200)
                self.assertEqual(sum(method=='POST' for method,path in calls),2)
                if os.environ.get('PROVIDER_SLOW_PROXY_TEST')=='1':
                    slow_payload={'model_mappings':[{**payload['model_mappings'][0],'upstream_model':'slow-fixture'}],'expected_config_version':provider['config_version']}
                    slow_saved=await c.patch(route,json=slow_payload);self.assertEqual(slow_saved.status_code,200)
                    provider=slow_saved.json()['data']
                    slow=await c.post(route+'/test-models',json={**consent,'models':[name+'0'],'expected_config_version':provider['config_version']},timeout=80)
                    self.assertEqual(slow.status_code,200);self.assertEqual(slow.json()['data']['success_count'],1)
                    print('PASS real Nginx/app loopback test: 61-second response succeeds beyond former 60-second idle timeout')
                edited=await c.patch(route,json={'api_key':'wrong-fixture-key','expected_config_version':provider['config_version']})
                self.assertEqual(edited.status_code,200)
                rejected=await c.post(route+'/test');self.assertEqual(rejected.status_code,200)
                self.assertFalse(rejected.json()['data']['success']);self.assertEqual(rejected.json()['data']['error_code'],'UPSTREAM_AUTH_FAILED')
                self.assertEqual((await c.delete(route)).status_code,200)
                print('PASS real HTTP management with loopback fixture: discovery, connection, consent, batch generation/logs, auth failure, delete; NOT real supplier verification')
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)
