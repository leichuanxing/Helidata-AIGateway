"""Image lifecycle through real HTTP/SQL/Redis, using a loopback vendor fixture.

Never targets a real vendor or creates a billable image. Optional 185-second
response verifies configured long image tests across Nginx and application.
"""
import asyncio,json,os,threading,time,unittest
from pathlib import Path
from uuid import uuid4
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import httpx

@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','disposable container only')
class ImagesHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        identity=os.environ.get('AUDIT_CONTAINER_ID','')
        self.assertGreaterEqual(len(identity),12)
        self.assertEqual(os.environ.get('HOSTNAME','')[:12],identity[:12])
        self.calls=[];self.mode='url';owner=self
        class Upstream(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def answer(self,status,body):
                raw=json.dumps(body).encode();self.send_response(status)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
                self.end_headers();self.wfile.write(raw)
            def do_GET(self):
                owner.calls.append(('GET',self.path,None))
                self.answer(200,{'data':[{'id':'qwen-image-3.0-pro'}]})
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.calls.append(('POST',self.path,body))
                if self.headers.get('Authorization')!='Bearer isolated-image-key':return self.answer(401,{'error':{'message':'fixture secret'}})
                if owner.mode=='slow':time.sleep(185)
                if owner.mode=='error':return self.answer(500,{'error':{'message':'fixture secret'}})
                if owner.mode=='invalid':return self.answer(200,{'created':1,'data':[]})
                row={'b64_json':'aGVsbG8='} if owner.mode=='base64' else {'url':'https://fixture.invalid/generated.png'}
                self.answer(200,{'created':1,'data':[row],'usage':{'output_image_count':1,'output_width':1024,'output_height':1024}})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.admin=httpx.AsyncClient(base_url='http://127.0.0.1',timeout=30)
        login=await self.admin.post('/api/auth/login',json={'username':'admin','password':Path('/data/config/audit-password.txt').read_text().strip()})
        self.assertEqual(login.status_code,200)
        self.admin.headers['Authorization']='Bearer '+login.json()['data']['access_token']
        self.prefix='images-'+uuid4().hex[:10]
    async def asyncTearDown(self):
        await self.admin.aclose();self.server.shutdown();self.server.server_close()
    async def api(self,method,path,body=None,status=200):
        r=await self.admin.request(method,'/api/'+path,json=body)
        self.assertEqual(r.status_code,status,r.text[:300]);return r.json().get('data')
    def payload(self,name,kind='image'):
        return {'name':name,'provider_type':'aliyun','protocol':'openai','protocol_type':kind,
            'base_url':f'http://127.0.0.1:{self.server.server_port}/compatible-mode/v1','api_key':'isolated-image-key',
            'protocol_config':{'openai-images' if kind=='image' else 'openai-completions':{}},
            'model_mappings':[{'logical_model':name,'upstream_model':'qwen-image-3.0-pro','model_type':kind}]}
    async def test_deleted_wrong_type_can_be_recreated_but_live_or_group_references_are_protected(self):
        name=self.prefix
        old=await self.api('POST','admin/providers',self.payload(name,'text'),201)
        self.assertEqual(len(self.calls),0,'saving must not generate images')
        conflicting=self.payload(name);conflicting['name']=name+'-other'
        await self.api('POST','admin/providers',conflicting,409)
        await self.api('PATCH','admin/providers/'+str(old['id']),{'status':'disabled'})
        await self.api('POST','admin/providers',conflicting,409)
        await self.api('DELETE','admin/providers/'+str(old['id']))
        new=await self.api('POST','admin/providers',self.payload(name),201)
        model=next(m for m in await self.api('GET','admin/logical-models') if m['name']==name)
        self.assertEqual(model['model_type'],'image')
        self.assertNotIn('isolated-image-key',json.dumps(new))
        self.assertEqual(len(self.calls),0)
        # A reference-only group is meaningful configuration even without nodes.
        grouped=name+'-grouped'
        await self.api('POST','admin/model-groups',{'name':grouped,'protocol_type':'text','logical_models':[grouped]},201)
        await self.api('POST','admin/providers',self.payload(grouped),409)
        self.assertEqual(next(m for m in await self.api('GET','admin/logical-models') if m['name']==grouped)['model_type'],'text')
        # The individual mapping endpoint uses the same canonical repair.
        orphan=name+'-mapping'
        old=await self.api('POST','admin/providers',self.payload(orphan,'text'),201)
        await self.api('DELETE','admin/providers/'+str(old['id']))
        await self.api('POST',f"admin/providers/{new['id']}/model-mappings",{'logical_model':orphan,'upstream_model':'qwen-image-3.0-pro','model_type':'image'},201)
    async def test_discovery_generation_consent_errors_compliance_and_balance(self):
        name=self.prefix;payload=self.payload(name)
        account=await self.api('POST','admin/providers',payload,201);path='admin/providers/'+str(account['id'])
        await self.api('POST','admin/providers/discover-models',{k:v for k,v in payload.items() if k!='model_mappings'})
        self.assertEqual(self.calls[-1][1],'/compatible-mode/v1/models')
        self.assertTrue((await self.api('POST',path+'/test'))['success'])
        self.assertEqual(sum(c[0]=='POST' for c in self.calls),0)
        consent={'models':[name],'consent':True,'expected_config_version':account['config_version']}
        await self.api('POST',path+'/test-models',consent,422)
        tested=await self.api('POST',path+'/test-models',{**consent,'image_consent':True})
        self.assertEqual(tested['success_count'],1)
        self.assertIsNone(tested['results'][0]['total_tokens'],'image counts must not become tokens')
        playable=await self.api('GET','admin/chat-test/models')
        self.assertEqual(next(m for m in playable['models'] if m['logical_model']==name)['model_type'],'image')
        before=len(self.calls)
        await self.api('POST','admin/chat-test/images',{'model':name,'prompt':'test','consent':False},422)
        self.assertEqual(len(self.calls),before)
        generated=await self.admin.post('/api/admin/chat-test/images',json={'model':name,'prompt':'a mountain','consent':True})
        self.assertEqual(generated.status_code,200,generated.text[:200])
        self.assertTrue(generated.headers.get('X-Content-Compliance'))
        self.assertNotIn('consent',self.calls[-1][2]);self.assertNotIn('stream',self.calls[-1][2])
        key=await self.api('POST','portal/api-keys',{'name':name},201);secret=key['secret']
        await self.api('POST','admin/model-groups',{'name':name,'protocol_type':'image','logical_models':[name]},201)
        async with httpx.AsyncClient(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+secret},timeout=30) as client:
            async def image(**kwargs):return await client.post('/v1/images/generations',json={'model':name,'prompt':'A blue circle','n':1,**kwargs})
            self.assertIn(name,[m['id'] for m in (await client.get('/v1/models')).json()['data']])
            portal=await self.api('GET','portal/models')
            shown=[m for g in portal['groups'] for m in g['models'] if m['logical_model']==name]
            self.assertTrue(shown);self.assertTrue(all(m['model_type']=='image' for m in shown))
            for mode in ('url','base64'):
                self.mode=mode;r=await image(size='1024x1024',prompt_extend=False)
                self.assertEqual(r.status_code,200,r.text[:200]);self.assertTrue(r.json()['data'])
                self.assertEqual(self.calls[-1][1],'/compatible-mode/v1/images/generations')
                self.assertFalse(self.calls[-1][2]['prompt_extend'])
                log=await self.api('GET','admin/call-logs/'+r.headers['x-request-id'])
                self.assertEqual(log['operation'],'images');self.assertIsNone(log['total_tokens'])
            self.mode='url';before=len(self.calls)
            for values in ({'prompt':'  '},{'n':0},{'n':True},{'stream':True}):self.assertEqual((await image(**values)).status_code,422)
            self.assertEqual(len(self.calls),before)
            policy=await self.api('POST','admin/compliance/policies',{'name':name,'status':'enabled','action':'block','models':[name]})
            await self.api('POST','admin/compliance/words',{'pattern':'forbidden-image-prompt','policy_id':policy['id']})
            self.assertEqual((await image(prompt='forbidden-image-prompt')).status_code,403);self.assertEqual(len(self.calls),before)
            denied=await self.admin.post('/api/admin/chat-test/images',json={'model':name,'prompt':'forbidden-image-prompt','consent':True})
            self.assertEqual(denied.status_code,403);self.assertEqual(denied.headers.get('X-Content-Compliance'),'block');self.assertEqual(len(self.calls),before)
            # Image routes reuse the same physical mapping and protocol.
            mapping=(await self.api('GET',path+'/model-mappings'))[0]
            route=await self.api('POST','admin/balance-routes',{'name':name,'model_name':name+'-balanced','model_type':'image','nodes':[{'mapping_id':mapping['id']}],'health_interval':3600},201)
            r=await image(model=name+'-balanced');self.assertEqual(r.status_code,200,r.text[:200])
            await self.api('DELETE','admin/balance-routes/'+str(route['id']))
            for mode in ('invalid','error'):
                self.mode=mode;before=len(self.calls);r=await image()
                self.assertEqual(r.status_code,502);self.assertEqual(len(self.calls),before+1)
                self.assertNotIn('fixture secret',r.text)
            before=len(self.calls)
            await self.api('PATCH','portal/api-keys/'+str(key['key']['id']),{'status':'disabled'})
            self.assertEqual((await image()).status_code,401);self.assertEqual(len(self.calls),before)
    @unittest.skipUnless(os.environ.get('IMAGE_SLOW_TEST')=='1','explicit long-response check')
    async def test_image_admin_test_respects_configured_timeout_beyond_180_seconds(self):
        name=self.prefix;account=await self.api('POST','admin/providers',self.payload(name),201)
        original=await self.api('GET','admin/settings?include_assets=false')
        await self.api('PATCH','admin/settings?include_assets=false',{'revision':original['revision'],'gateway':{'nonstream_timeout':200}})
        self.mode='slow'
        try:
            r=await self.admin.post(f"/api/admin/providers/{account['id']}/test-models",json={'models':[name],'consent':True,'image_consent':True,'expected_config_version':account['config_version']},timeout=220)
            self.assertEqual(r.status_code,200,r.text[:200]);self.assertEqual(r.json()['data']['success_count'],1)
        finally:
            current=await self.api('GET','admin/settings?include_assets=false')
            await self.api('PATCH','admin/settings?include_assets=false',{'revision':current['revision'],'gateway':{'nonstream_timeout':original['gateway']['nonstream_timeout']}})
