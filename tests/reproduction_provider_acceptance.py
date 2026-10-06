"""Atomic provider/mapping and draft discovery regression; local mock only."""
import asyncio,json,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4
import httpx

class Upstream(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        assert self.path=='/v1/models'
        ok=self.headers.get('Authorization')=='Bearer fixture-only-secret'
        body=json.dumps({'data':[{'id':'fixture-upstream'}]} if ok else {'error':{'message':'unauthorized'}}).encode()
        self.send_response(200 if ok else 401);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)

async def main(url):
    assert Path('/data/.reproduction-ui-isolated').read_text().strip()=='reproduction-ui-isolated'
    prefix='atomic-'+uuid4().hex[:12]
    async with httpx.AsyncClient(base_url='http://127.0.0.1',trust_env=False,timeout=20) as client:
        r=await client.post('/api/auth/login',json={'username':'replica-manager','password':'Reproduction!Fixture2026'})
        assert r.status_code==200
        headers={'Authorization':'Bearer '+r.json()['data']['access_token']}
        connection={'provider_type':'custom_openai','protocol':'openai','base_url':url,'api_key':'fixture-only-secret'}
        r=await client.post('/api/admin/providers/discover-models',json=connection,headers=headers)
        assert r.status_code==200 and r.json()['data']['models']==[{'id':'fixture-upstream'}]
        assert (await client.get('/api/admin/providers',params={'q':'discovery'},headers=headers)).json()['data']['total']==0
        mapping={'logical_model':prefix+'-one','upstream_model':'fixture-upstream','model_type':'text'}
        body={**connection,'name':prefix,'model_mappings':[mapping]}
        r=await client.post('/api/admin/providers',json={**body,'model_mappings':[]},headers=headers);assert r.status_code==422
        r=await client.post('/api/admin/providers',json={**body,'model_mappings':[mapping,mapping]},headers=headers);assert r.status_code==422
        r=await client.post('/api/admin/providers',json={**body,'model_mappings':[mapping]*101},headers=headers);assert r.status_code==422
        r=await client.post('/api/admin/providers',json=body,headers=headers)
        assert r.status_code==201
        account=r.json()['data'];ident=account['id'];assert 'api_key' not in account
        maps=(await client.get(f'/api/admin/providers/{ident}/model-mappings',headers=headers)).json()['data'];assert len(maps)==1
        first_id=maps[0]['id']
        second={**mapping,'logical_model':prefix+'-two'}
        r=await client.patch(f'/api/admin/providers/{ident}',json={'model_mappings':[mapping,second],'expected_config_version':account['config_version']},headers=headers)
        assert r.status_code==200;rversion=r.json()['data']['config_version']
        maps=(await client.get(f'/api/admin/providers/{ident}/model-mappings',headers=headers)).json()['data']
        assert len(maps)==2 and next(m['id'] for m in maps if m['logical_model']==mapping['logical_model'])==first_id
        r=await client.post('/api/admin/providers/discover-models',json={k:v for k,v in {**connection,'provider_id':ident}.items() if k!='api_key'},headers=headers)
        assert r.status_code==200
        third={**mapping,'logical_model':prefix+'-three'}
        r=await client.post(f'/api/admin/providers/{ident}/model-mappings',json=third,headers=headers);assert r.status_code==201
        r=await client.patch(f'/api/admin/providers/{ident}',json={'name':prefix+'-overwritten','model_mappings':[mapping],'expected_config_version':rversion},headers=headers)
        assert r.status_code==409 and r.json()['error']['code']=='PROVIDER_CHANGED'
        assert (await client.get(f'/api/admin/providers/{ident}',headers=headers)).json()['data']['name']==prefix
        failed={**body,'name':prefix+'-failed','model_mappings':[{**mapping,'logical_model':prefix+'-rollback'},
            {**mapping,'logical_model':'semantic-vector','model_type':'text'}]}
        r=await client.post('/api/admin/providers',json=failed,headers=headers);assert r.status_code==409
        assert (await client.get('/api/admin/providers',params={'q':prefix+'-failed'},headers=headers)).json()['data']['total']==0
        names={m['name'] for m in (await client.get('/api/admin/logical-models',headers=headers)).json()['data']}
        assert prefix+'-rollback' not in names
        current=(await client.get(f'/api/admin/providers/{ident}',headers=headers)).json()['data']
        r=await client.patch(f'/api/admin/providers/{ident}',json={'model_mappings':[second],'expected_config_version':current['config_version']},headers=headers);assert r.status_code==200
        maps=(await client.get(f'/api/admin/providers/{ident}/model-mappings',headers=headers)).json()['data']
        assert len(maps)==1 and maps[0]['logical_model']==second['logical_model']
        r=await client.post('/api/admin/providers',json={**connection,'name':prefix+'-legacy'},headers=headers);assert r.status_code==201
        viewer=await client.post('/api/auth/login',json={'username':'replica-viewer','password':'Reproduction!Fixture2026'})
        r=await client.post('/api/admin/providers/discover-models',json=connection,headers={'Authorization':'Bearer '+viewer.json()['data']['access_token']});assert r.status_code==403
        print('PASS: draft discovery leaves no provider; 1..100 unique mappings; atomic create/update; preserve mapping IDs and saved key; concurrent mapping edits return409; full rollback on type conflict; soft removal; legacy API compatibility; ordinary-user403; zero paid inference.',flush=True)

server=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
threading.Thread(target=server.serve_forever,daemon=True).start()
try:asyncio.run(main(f'http://127.0.0.1:{server.server_port}/v1'))
finally:server.shutdown();server.server_close()
