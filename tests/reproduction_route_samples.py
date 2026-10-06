"""Sample lifecycle with real local HTTP embedding and durable workers; no paid calls."""
import asyncio,json,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4
import httpx
from app.services.route_vectors import classify
calls=[]


class Fixture(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        assert self.path=='/v1/embeddings'
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert self.headers.get('Authorization')=='Bearer fixture-vector-only'
        assert isinstance(body['input'],str)
        calls.append(body['model'])
        data=json.dumps({'object':'list','model':body['model'],'data':[{'object':'embedding','index':0,'embedding':[1,0,0]}],
                         'usage':{'prompt_tokens':2,'total_tokens':2}}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)


async def main(url):
    assert Path('/data/.reproduction-ui-isolated').read_text().strip()=='reproduction-ui-isolated'
    prefix='samples-'+uuid4().hex[:10]
    legacy=[{'classification':'simple','similarity':.8},{'classification':'complex','similarity':.7}]
    assert classify(legacy,.75,.15).reason=='ROUTE_AMBIGUOUS'
    assert classify([{**legacy[0],'similarity_threshold':.9},{**legacy[1],'similarity_threshold':.6}],.75,.1).classification=='complex'
    assert classify([{**legacy[0],'similarity_threshold':.9}],.75,.1).reason=='ROUTE_LOW_SIMILARITY'
    assert classify([{**legacy[1],'similarity_threshold':0}],.75,.1).classification=='complex'
    async with httpx.AsyncClient(base_url='http://127.0.0.1',trust_env=False,timeout=20) as c:
        login=await c.post('/api/auth/login',json={'username':'replica-manager','password':'Reproduction!Fixture2026'});assert login.status_code==200
        h={'Authorization':'Bearer '+login.json()['data']['access_token']}
        r=await c.post('/api/admin/providers',json={'name':prefix,'provider_type':'custom_openai','protocol':'openai','base_url':url,'api_key':'fixture-vector-only',
            'model_mappings':[{'logical_model':prefix+'-embedding','upstream_model':'local-vector','model_type':'embedding'}]},headers=h);assert r.status_code==201
        groups=[]
        for suffix in ('simple','complex'):
            r=await c.post('/api/admin/model-groups',json={'name':prefix+'-'+suffix,'protocol_type':'text','logical_models':['deepseek-flash']},headers=h)
            assert r.status_code==201;groups.append(r.json()['data']['id'])
        r=await c.post('/api/admin/smart-route/configs',json={'virtual_model':prefix+'-auto','embedding_model':prefix+'-embedding','simple_model_group':groups[0],'complex_model_group':groups[1],'status':'disabled'},headers=h)
        assert r.status_code==201;config=r.json()['data']['id']
        async def samples():
            return (await c.get('/api/admin/smart-route/samples',params={'config_id':config},headers=h)).json()['data']['items']
        async def wait_ready(ids):
            for _ in range(40):
                rows=await samples()
                if all(any(row['id']==i and row['vector_status']=='ready' for row in rows) for i in ids):return rows
                assert not any(row['id'] in ids and row['vector_status']=='failed' for row in rows),'local vector build failed'
                await asyncio.sleep(.5)
            raise AssertionError('Vector worker did not complete')
        item={'prompt':'😀'*65536,'classification':'simple','similarity_threshold':.6,'remark':'长样本','build_vector':False}
        r=await c.post('/api/admin/smart-route/samples',json={'config_id':config,'samples':[item,{**item,'prompt':'second','classification':'complex'}]},headers=h)
        assert r.status_code==201 and r.json()['data']['queued']==0;ids=r.json()['data']['ids']
        await asyncio.sleep(1.2);assert not calls
        rows=await samples();assert len(rows)==2 and all(not row['vector_requested'] and row['vector_status']=='pending' for row in rows)
        r=await c.get('/api/admin/smart-route/samples',params={'config_id':config,'vector_status':'not_built'},headers=h);assert r.json()['data']['total']==2
        r=await c.post('/api/admin/smart-route/samples',json={'config_id':config,'samples':[{**item,'prompt':'x'*65537}]},headers=h);assert r.status_code==422
        r=await c.post('/api/admin/smart-route/samples',json={'config_id':config,'samples':[{**item,'prompt':'invalid','similarity_threshold':1.1}]},headers=h);assert r.status_code==422
        r=await c.post('/api/admin/smart-route/samples',json={'config_id':config,'samples':[{**item,'prompt':'rollback'},item]},headers=h);assert r.status_code==409
        assert len(await samples())==2
        endpoint='/api/admin/smart-route/samples/vectorize'
        r=await c.post(endpoint,json={'config_id':config,'sample_ids':[ids[0],999999999]},headers=h);assert r.status_code==400
        assert not calls and all(row['revision']==1 for row in await samples())
        assert (await c.post(endpoint,json={'config_id':config,'sample_ids':[True]},headers=h)).status_code==422
        r=await c.post(endpoint,json={'config_id':config,'sample_ids':[ids[0]]},headers=h);assert r.status_code==200 and r.json()['data']['queued']==1
        await wait_ready([ids[0]]);assert len(calls)==1
        assert not next(row for row in await samples() if row['id']==ids[1])['vector_requested']
        r=await c.post(endpoint,json={'config_id':config,'all_samples':True},headers=h);assert r.status_code==200 and r.json()['data']['queued']==2
        await wait_ready(ids);assert len(calls)==3
        row=next(row for row in await samples() if row['id']==ids[0]);revision=row['revision']
        r=await c.put('/api/admin/smart-route/samples/'+str(ids[0]),json={**item,'prompt':'edited'},headers=h);assert r.status_code==200
        assert r.json()['data']['revision']==revision+1 and not r.json()['data']['vector_requested']
        await asyncio.sleep(1.2);assert len(calls)==3
        r=await c.post('/api/admin/smart-route/samples/import',json={'config_id':config,'content':'prompt,classification\nimported,simple','build_vector':False},headers=h)
        assert r.status_code==201 and r.json()['data']['queued']==0
        before=await samples();preview_endpoint=f'/api/admin/smart-route/configs/{config}/preview'
        r=await c.post(preview_endpoint,json={'prompt':'preview complex request'},headers=h);assert r.status_code==200,r.text
        result=r.json()['data'];assert result['preview'] and result['classification']=='complex' and result['selected_model_group']==groups[1]
        assert result['evidence'] and result['embedding_request_id'] and result['candidate_models']==['deepseek-flash']
        assert len(calls)==4 and before==await samples()
        r=await c.get('/api/admin/call-logs',params={'request_id':result['embedding_request_id']},headers=h)
        assert r.status_code==200 and any(row['request_id']==result['embedding_request_id'] for row in r.json()['data']['items']),r.text
        assert (await c.post(preview_endpoint,json={'prompt':'x'*16001},headers=h)).status_code==422
        assert (await c.post(preview_endpoint,json={'prompt':'  '},headers=h)).status_code==422
        assert len(calls)==4
        viewer=await c.post('/api/auth/login',json={'username':'replica-viewer','password':'Reproduction!Fixture2026'});assert viewer.status_code==200
        assert (await c.post(endpoint,json={'config_id':config,'all_samples':True},headers={'Authorization':'Bearer '+viewer.json()['data']['access_token']})).status_code==403
        assert (await c.post(preview_endpoint,json={'prompt':'forbidden'},headers={'Authorization':'Bearer '+viewer.json()['data']['access_token']})).status_code==403
        assert len(calls)==4
    print('PASS: 65536 Unicode characters; threshold override with legacy confidence behavior; remarks; save without upstream; selected/all builds via real local HTTP and pgvector workers; atomic invalid selection/import; stale-vector invalidation; metered decision preview without sample mutation; preview limits; ordinary-user403; zero paid inference.')


server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=server.serve_forever,daemon=True).start()
try:asyncio.run(main(f'http://127.0.0.1:{server.server_port}/v1'))
finally:server.shutdown();server.server_close()
