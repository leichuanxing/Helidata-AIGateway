"""Zhipu provider CRUD and OpenAI wire regression, isolated loopback mock only."""
import asyncio,json,threading
from contextlib import AsyncExitStack
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import httpx
from app.providers.registry import PROVIDER_TYPES,build_adapter
from app.providers.operations import compatible

seen=[]
class Upstream(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def reply(self,status,body,content_type='application/json'):
        self.send_response(status);self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        seen.append(('GET',self.path))
        if self.headers.get('Authorization')!='Bearer fixture-zhipu-key':
            return self.reply(401,b'{"error":{"message":"unauthorized"}}')
        # No fabricated model-list success; discovery may be absent upstream.
        self.reply(404,b'{"error":{"message":"models unavailable"}}')
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        seen.append(('POST',self.path))
        assert self.path in ('/api/paas/v4/chat/completions','/api/coding/paas/v4/chat/completions')
        assert self.headers.get('Authorization')=='Bearer fixture-zhipu-key'
        assert payload['model']=='fixture-glm' and payload['messages'][0]['content']=='hello'
        if payload.get('stream'):
            return self.reply(200,b'data: {"choices":[{"index":0,"delta":{"content":"fixture"}}]}\n\ndata: [DONE]\n\n','text/event-stream')
        self.reply(200,json.dumps({'id':'fixture','object':'chat.completion','created':1,'model':'fixture-glm',
            'choices':[{'index':0,'message':{'role':'assistant','content':'fixture'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}}).encode())

async def main(port):
    assert Path('/data/.reproduction-ui-isolated').read_text().strip()=='reproduction-ui-isolated'
    prefix='zhipu-'+uuid4().hex[:10]
    async with httpx.AsyncClient(base_url='http://127.0.0.1',trust_env=False,timeout=20) as client:
        login=await client.post('/api/auth/login',json={'username':'replica-manager','password':'Reproduction!Fixture2026'})
        assert login.status_code==200
        headers={'Authorization':'Bearer '+login.json()['data']['access_token']}
        types=(await client.get('/api/admin/providers/types',headers=headers)).json()['data']
        catalog={t['code']:t for t in types}
        for code,path in (('zhipu','/api/paas/v4'),('zhipu_coding_plan','/api/coding/paas/v4')):
            assert catalog[code]['base_url']=='https://open.bigmodel.cn'+path and catalog[code]['key_required']
            body={'name':prefix+'-'+code,'provider_type':code,'protocol':'openai','base_url':f'http://127.0.0.1:{port}'+path,
                'model_mappings':[{'logical_model':prefix+'-'+code,'upstream_model':'fixture-glm','model_type':'text'}]}
            assert (await client.post('/api/admin/providers',headers=headers,json=body)).status_code==422
            assert (await client.post('/api/admin/providers',headers=headers,json={**body,'api_key':'fixture-zhipu-key','protocol':'anthropic'})).status_code==422
            r=await client.post('/api/admin/providers',headers=headers,json={**body,'api_key':'fixture-zhipu-key'})
            assert r.status_code==201,r.text
            account=r.json()['data'];ident=account['id']
            assert account['has_api_key'] and 'api_key' not in account and account['health_status']=='unknown'
            maps=(await client.get(f'/api/admin/providers/{ident}/model-mappings',headers=headers)).json()['data']
            assert len(maps)==1 and maps[0]['upstream_model']=='fixture-glm'
            rows=(await client.get('/api/admin/providers',params={'provider_type':code},headers=headers)).json()['data']['items']
            assert any(p['id']==ident and p['provider_type']==code for p in rows)
            provider=SimpleNamespace(provider_type=code,protocol='openai',base_url=body['base_url'],proxy=None)
            assert compatible('chat',provider) and compatible('messages',provider)
            if code=='zhipu_coding_plan':
                assert all(not compatible(op,provider) for op in ('responses','embeddings','images','rerank'))
            adapter=build_adapter(provider,'fixture-zhipu-key')
            payload={'model':'fixture-glm','messages':[{'role':'user','content':'hello'}]}
            result=await adapter.chat_completion(payload);assert result['choices'][0]['message']['content']=='fixture'
            async with AsyncExitStack() as resources:
                response=await adapter.open_chat_stream({**payload,'stream':True},resources,10)
                stream=''.join([part async for part in response.aiter_text()]);assert 'fixture' in stream and '[DONE]' in stream
            post_count=sum(method=='POST' for method,_ in seen)
            test=(await client.post(f'/api/admin/providers/{ident}/test',headers=headers)).json()['data']
            assert not test['success'] and test['http_status']==404 and test['authentication']=='unknown'
            assert sum(method=='POST' for method,_ in seen)==post_count
            edited=await client.patch(f'/api/admin/providers/{ident}',headers=headers,json={'remark':'saved key retained'})
            assert edited.status_code==200 and edited.json()['data']['has_api_key']
            assert (await client.delete(f'/api/admin/providers/{ident}',headers=headers)).status_code==200
        assert {path for method,path in seen if method=='POST'}=={'/api/paas/v4/chat/completions','/api/coding/paas/v4/chat/completions'}
    print('PASS: both provider types/defaults; required key/protocol validation; encrypted key CRUD/filter/mapping; Bearer and separate Chat/SSE paths; coding operation restriction; model404 never claims authentication or sends inference. Loopback mocks only; zero paid calls.',flush=True)

server=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
threading.Thread(target=server.serve_forever,daemon=True).start()
try:asyncio.run(main(server.server_port))
finally:server.shutdown();server.server_close()
