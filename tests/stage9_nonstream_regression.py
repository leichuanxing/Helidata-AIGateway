"""Real Nginx/FastAPI/HTTPX roundtrips against disposable HTTP protocol fixtures.
No live paid credentials, no simulated responses in application code.
"""
import asyncio
import json
import secrets
import subprocess
import threading
import time
from unittest.mock import patch
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import timedelta
import httpx
from sqlalchemy import select, delete
from app.core.database import session_factory, engine
from app.core.security import digest, hash_password, now
from app.models.user import User, Role, UserGroup, ModelGroup, UserGroupModelGroup, ModelGroupModel, LogicalModel, Provider, ProviderModelMapping, ApiKey
from app.services.provider_crypto import encrypt_secret

PREFIX='stage9_'+uuid.uuid4().hex[:10]
KEY='sk-hd-'+secrets.token_urlsafe(32)
SECRET='sk-upstream-'+secrets.token_urlsafe(32)
NAME=PREFIX+'-chat'; EMBED=PREFIX+'-embed'
ids={};calls=[];URL=''


class Fixture(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        calls.append((self.path,payload,dict(self.headers)))
        assert self.headers.get('Authorization')=='Bearer '+SECRET
        assert self.headers.get('X-Request-ID','').startswith('req_')
        assert payload['model']=='private-upstream-model' and payload['stream'] is False
        mode=self.path.split('/')[1];status=200
        if mode=='slow': time.sleep(0.3)
        answer={'id':'chatcmpl-fixture','object':'chat.completion','created':1791110000,
            'model':'private-upstream-model','choices':[{'index':0,'message':{'role':'assistant','content':'fixture-response'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':4,'completion_tokens':2,'total_tokens':6},'system_fingerprint':'fixture-fp'}
        if mode=='tools':
            answer['choices'][0]['message']={'role':'assistant','content':None,'tool_calls':[{'id':'call-fixture','type':'function','function':{'name':'lookup','arguments':'{"id":1}'}}]}
            answer['choices'][0]['finish_reason']='tool_calls'
        elif mode in ('bad','limited','auth','fail','redirect'):
            status={'bad':400,'limited':429,'auth':401,'fail':500,'redirect':302}[mode]
            answer={'error':{'message':SECRET+' '+KEY,'model':'private-upstream-model'}}
        elif mode=='schema': answer={'choices':[],'error':SECRET}
        elif mode=='big': answer['choices'][0]['message']['content']='x'*(8*1024*1024)
        raw=b'not-json '+SECRET.encode() if mode=='invalid' else json.dumps(answer).encode()
        self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)))
        if status==302:self.send_header('Location',URL+'/redirect-target')
        self.end_headers()
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_GET(self):
        calls.append(('UNEXPECTED_GET',{},{}));self.send_response(500);self.end_headers()


async def seed():
    async with session_factory.begin() as db:
        ug=UserGroup(name=PREFIX,quota_limit=0);db.add(ug);await db.flush();ids['ug']=ug.id
        rid=await db.scalar(select(Role.id).where(Role.code=='user'))
        u=User(username=PREFIX,role='user',role_id=rid,user_group_id=ug.id,must_change_password=False,password_hash=await hash_password(secrets.token_urlsafe(24)))
        db.add(u);await db.flush();ids['user']=u.id
        key=ApiKey(user_id=u.id,name=PREFIX,key_hash=digest(KEY),prefix=KEY[:12],suffix=KEY[-4:]);db.add(key);await db.flush();ids['key']=key.id
        g=ModelGroup(name=PREFIX);db.add(g);await db.flush();ids['mg']=g.id
        db.add(UserGroupModelGroup(user_group_id=ug.id,model_group_id=g.id))
        for name,kind in [(NAME,'text'),(EMBED,'embedding')]:
            db.add(LogicalModel(name=name,model_type=kind));await db.flush()
            db.add(ModelGroupModel(model_group_id=g.id,logical_model=name,position=0 if name==NAME else 1))
        p=Provider(name=PREFIX,provider_type='custom_openai',protocol='openai',base_url=URL+'/normal/v1',api_key_encrypted=encrypt_secret(SECRET))
        db.add(p);await db.flush();ids['provider']=p.id
        for name,kind in [(NAME,'text'),(EMBED,'embedding')]:
            mapping=ProviderModelMapping(provider_id=p.id,logical_model=name,upstream_model='private-upstream-model',model_type=kind)
            db.add(mapping);await db.flush()
            if name==NAME:ids['mapping']=mapping.id


async def change(model,key,**values):
    async with session_factory.begin() as db:
        row=await db.get(model,ids[key])
        for k,v in values.items():setattr(row,k,v)


def checked(r,status,code=None):
    assert r.status_code==status,f'{r.status_code}: {r.text[:200]}'
    rid=r.headers['X-Request-ID'];assert rid.startswith('req_') and r.headers['Cache-Control']=='no-store'
    assert KEY not in r.text and SECRET not in r.text and 'private-upstream-model' not in r.text
    data=r.json()
    if code:assert data['error']['code']==code and data['error']['type']=='gateway_error' and data['error']['request_id']==rid
    return data,rid


async def main():
    global URL
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);URL='http://127.0.0.1:'+str(server.server_port)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    await seed()
    c=httpx.AsyncClient(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+KEY},timeout=30)
    basic={'model':NAME,'messages':[{'role':'user','content':'你好'}]}
    try:
        models,_=checked(await c.get('/v1/models'),200);assert {m['id'] for m in models['data']}=={NAME,EMBED}
        assert all(isinstance(m['created'],int) and m['created']>0 and m['object']=='model' for m in models['data'])
        data,rid=checked(await c.post('/v1/chat/completions',json=basic,headers={'X-Request-ID':'client-owned-id'}),200)
        assert rid!='client-owned-id'
        assert data['model']==NAME and data['choices'][0]['message']['content']=='fixture-response'
        assert data['usage']=={'prompt_tokens':4,'completion_tokens':2,'total_tokens':6}
        assert calls[-1][0]=='/normal/v1/chat/completions' and calls[-1][2]['X-Request-ID']==rid
        assert calls[-1][1]=={**basic,'model':'private-upstream-model','stream':False}
        # The plan's curl path works against the running container, with a test-only upstream.
        conf='url = "http://127.0.0.1/v1/chat/completions"\nheader = "Content-Type: application/json"\nheader = "Authorization: Bearer '+KEY+'"\n'
        curl=subprocess.run(['curl','-fsS','-K','-','--data-binary',json.dumps(basic)],input=conf,text=True,capture_output=True)
        assert curl.returncode==0 and json.loads(curl.stdout)['model']==NAME
        print('PASS: actual HTTPX and curl Chat Completion path, mapping rewrite, logical response model, Request ID forwarded and real fixture usage preserved')
        await change(Provider,'provider',base_url=URL+'/tools/v1')
        payload={**basic,'messages':[{'role':'developer','content':'Use tools'},{'role':'user','content':[{'type':'text','text':'hello'},{'type':'image_url','image_url':{'url':'data:image/png;base64,AAAA'}}]},
            {'role':'assistant','content':None,'tool_calls':[{'id':'old-call','type':'function','function':{'name':'lookup','arguments':'{}'}}]},
            {'role':'tool','content':'previous result','tool_call_id':'old-call'}],
            'temperature':0.2,'top_p':0.9,'max_tokens':16,'max_completion_tokens':32,'stream':False,
            'tools':[{'type':'function','function':{'name':'lookup','parameters':{'type':'object','properties':{}}}}],
            'tool_choice':{'type':'function','function':{'name':'lookup'}},'response_format':{'type':'json_schema','json_schema':{'name':'result','schema':{'type':'object'}}},
            'reasoning_effort':'low','parallel_tool_calls':False,'n':1,'stop':['END']}
        data,_=checked(await c.post('/v1/chat/completions',json=payload),200)
        assert calls[-1][1]=={**payload,'model':'private-upstream-model'}
        assert data['choices'][0]['message']['content'] is None and data['choices'][0]['message']['tool_calls'][0]['function']['arguments']=='{"id":1}'
        print('PASS: optional fields/extensions, developer/multimodal/tool messages and tool result roundtrip; no function execution in gateway')
        before=len(calls)
        for body in [{**basic,'messages':[]},{**basic,'temperature':3},{**basic,'top_p':2},{**basic,'max_tokens':0},
            {**basic,'messages':[{'role':'tool','content':'x'}]},{**basic,'messages':[{'role':'user','content':None}]},
            {**basic,'messages':[{'role':'user','content':'x'*(2*1024*1024)}]}]:
            checked(await c.post('/v1/chat/completions',json=body),422,'VALIDATION_ERROR')
        checked(await c.post('/v1/chat/completions',json={**basic,'model':'ungranted'}),403,'MODEL_FORBIDDEN')
        checked(await c.post('/v1/chat/completions',json={**basic,'model':EMBED}),400,'MODEL_TYPE_UNSUPPORTED')
        checked(await c.post('/v1/chat/completions',json=basic,headers={'Authorization':'Bearer invalid'}),401,'INVALID_API_KEY')
        assert len(calls)==before
        for mode,status,code in [('bad',400,'UPSTREAM_REQUEST_REJECTED'),('limited',503,'UPSTREAM_RATE_LIMITED'),('auth',502,'UPSTREAM_AUTH_FAILED'),
            ('fail',502,'UPSTREAM_HTTP_ERROR'),('redirect',502,'UPSTREAM_HTTP_ERROR'),('invalid',502,'UPSTREAM_INVALID_RESPONSE'),
            ('schema',502,'UPSTREAM_INVALID_RESPONSE'),('big',502,'UPSTREAM_RESPONSE_TOO_LARGE')]:
            await change(Provider,'provider',base_url=URL+'/'+mode+'/v1')
            before=len(calls);checked(await c.post('/v1/chat/completions',json=basic),status,code);assert len(calls)==before+1
        await change(Provider,'provider',base_url='http://127.0.0.1:1/v1')
        checked(await c.post('/v1/chat/completions',json=basic),502,'UPSTREAM_NETWORK_ERROR')
        await change(Provider,'provider',base_url=URL+'/slow/v1')
        from app.main import app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,raise_app_exceptions=False),base_url='http://test',headers={'Authorization':'Bearer '+KEY}) as local:
            with patch('app.gateway.upstream.CHAT_TIMEOUT_SECONDS',0.05):
                checked(await local.post('/v1/chat/completions',json=basic),504,'UPSTREAM_TIMEOUT')
        print('PASS: validation/authorization/type reject before network; upstream 400/401/429/500/302/schema/JSON/size/network failures sanitized; no redirects/retries')
        await change(Provider,'provider',base_url=URL+'/normal/v1',status='disabled')
        models,_=checked(await c.get('/v1/models'),200);assert models['data']==[]
        checked(await c.post('/v1/chat/completions',json=basic),503,'NO_AVAILABLE_PROVIDER')
        await change(Provider,'provider',status='enabled',health_status='unhealthy')
        models,_=checked(await c.get('/v1/models'),200);assert models['data']==[]
        await change(Provider,'provider',health_status='healthy',cooldown_until=now()+timedelta(minutes=5))
        models,_=checked(await c.get('/v1/models'),200);assert models['data']==[]
        await change(Provider,'provider',cooldown_until=None,protocol='anthropic',provider_type='anthropic')
        before=len(calls);checked(await c.post('/v1/chat/completions',json=basic),503,'NO_COMPATIBLE_PROVIDER');assert len(calls)==before
        await change(Provider,'provider',protocol='openai',provider_type='custom_openai')
        await change(ProviderModelMapping,'mapping',status='disabled')
        models,_=checked(await c.get('/v1/models'),200);assert {m['id'] for m in models['data']}=={EMBED}
        checked(await c.post('/v1/chat/completions',json=basic),503,'NO_AVAILABLE_PROVIDER')
        await change(ProviderModelMapping,'mapping',status='enabled')
        await change(ModelGroup,'mg',status='disabled')
        models,_=checked(await c.get('/v1/models'),200);assert models['data']==[]
        await change(ModelGroup,'mg',status='enabled')
        results=await asyncio.gather(*[c.post('/v1/chat/completions',json=basic) for _ in range(8)])
        assert len({checked(r,200)[1] for r in results})==8
        print('PASS: /v1/models filters enabled authorization and usable mappings; live disable/health/cooldown/type/protocol isolation; concurrent inference Request IDs')
    finally:
        await c.aclose();server.shutdown();server.server_close()
        async with session_factory.begin() as db:
            await db.execute(delete(User).where(User.id==ids['user']))
            await db.execute(delete(UserGroup).where(UserGroup.id==ids['ug']))
            await db.execute(delete(ModelGroup).where(ModelGroup.id==ids['mg']))
            await db.execute(delete(ProviderModelMapping).where(ProviderModelMapping.provider_id==ids['provider']))
            await db.execute(delete(Provider).where(Provider.id==ids['provider']))
            await db.execute(delete(LogicalModel).where(LogicalModel.name.in_([NAME,EMBED])))
        await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())
