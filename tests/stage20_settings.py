"""Real isolated settings, privacy, runtime and retention acceptance. No paid API."""
import asyncio,base64,json,struct,zlib,threading,time,uuid
from datetime import timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import httpx,jwt
from sqlalchemy import select,func,update
from app.core.database import session_factory,engine
from app.core.security import hash_password,now
from app.models.user import User,Role,Provider
from app.models.call_log import CallLog
from app.services import operations_settings,operations_jobs
import stage12_nonstream_regression as seed

PASSWORD='Stage20!Isolated84925';PRIVATE='private-84925';gets=[];requests=[]

class Fixture(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        gets.append(self.path);raw=b'{"object":"list","data":[{"id":"private-upstream-model","object":"model"}]}'
        self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
    def do_POST(self):
        value=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(value)
        assert self.headers['Authorization']=='Bearer '+seed.SECRET
        if value['messages'][0]['content']=='slow':time.sleep(2)
        answer={'id':'chatcmpl-settings','object':'chat.completion','created':1791110000,'model':'private-upstream-model',
            'choices':[{'index':0,'message':{'role':'assistant','content':PRIVATE+' sk-privatekey84925 password=topsecret'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':4,'completion_tokens':2,'total_tokens':6}}
        if value.get('stream'):
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Connection','close');self.end_headers()
            answer['object']='chat.completion.chunk';answer['choices']=[{'index':0,'delta':{'content':PRIVATE},'finish_reason':None}]
            raw=(('data: '+json.dumps(answer)+'\n\n')*(1000 if value['messages'][0]['content']=='large-stream' else 1)+'data: [DONE]\n\n').encode()
        else:
            raw=json.dumps(answer).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers()
        try:self.wfile.write(raw);self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError):pass

def png():
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00\x00\x80\xff\xff'))+chunk(b'IEND',b'')
    return 'data:image/png;base64,'+base64.b64encode(raw).decode()

async def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=server.serve_forever,daemon=True).start()
    seed.URL='http://127.0.0.1:'+str(server.server_port);await seed.seed()
    async with session_factory.begin() as db:
        roles=dict((code,ident) for ident,code in (await db.execute(select(Role.id,Role.code))).all())
        for role in ('super_admin','admin','user'):
            db.add(User(username='isolated-final-'+role,role=role,role_id=roles[role],password_hash=await hash_password(PASSWORD),must_change_password=False))
    async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=30) as c:
        headers={}
        for role in ('super_admin','admin','user'):
            r=await c.post('/api/auth/login',json={'username':'isolated-final-'+role,'password':PASSWORD});assert r.status_code==200
            headers[role]={'Authorization':'Bearer '+r.json()['data']['access_token']}
            assert (await c.get('/api/admin/settings',headers=headers[role])).status_code==(200 if role=='super_admin' else 403)
            assert (await c.patch('/api/admin/settings',headers=headers[role],json={'revision':0})).status_code==(200 if role=='super_admin' else 403)
        assert (await c.get('/api/admin/settings')).status_code==401
        public=(await c.get('/api/public/settings')).json()['data'];assert set(public)==set(operations_settings.Basic.model_fields)
        async def settings():return (await c.get('/api/admin/settings',headers=headers['super_admin'])).json()['data']
        original=await settings();current=original
        async def patch(**sections):
            nonlocal current
            r=await c.patch('/api/admin/settings',headers=headers['super_admin'],json={'revision':current['revision'],**sections});assert r.status_code==200,r.text[:100]
            current=r.json()['data'];return current
        for section,value in [('basic',{'system_url':'http://user:password@example.org'}),('basic',{'timezone':'invalid-zone'}),('basic',{'logo':'data:image/svg+xml;base64,AAAA'}),('logging',{'redaction_rules':['[']}),('gateway',{'max_body_bytes':10485761})]:
            r=await c.patch('/api/admin/settings',headers=headers['super_admin'],json={'revision':current['revision'],section:value});assert r.status_code==422
        oldrev=current['revision'];await patch(basic={'system_name':'隔离最终验收','logo':png(),'icon':png(),'public_api_base_url':'https://api.example.org/v1','timezone':'UTC'})
        r=await c.patch('/api/admin/settings',headers=headers['super_admin'],json={'revision':oldrev,'basic':{'system_name':'stale'}});assert r.status_code==409
        public=(await c.get('/api/public/settings')).json()['data'];assert public['system_name']=='隔离最终验收' and public['logo']==png()
        assert current['gateway']==original['gateway'] and 'jwt_secret' not in json.dumps(current) and 'database' not in current
        print('PASS: three-role boundaries, public allowlist, validation, optimistic conflict, partial merge and PNG/database branding',flush=True)
        key={'Authorization':'Bearer '+seed.KEY};body={'model':seed.NAME,'messages':[{'role':'user','content':PRIVATE+' sk-requestkey84925 password=topsecret'}],'password':'topsecret'}
        async def call(payload):
            r=await c.post('/v1/chat/completions',headers=key,json=payload);assert r.status_code==200,r.text[:150]
            rid=r.headers['x-request-id']
            for _ in range(30):
                detail=await c.get('/api/admin/call-logs/'+rid,headers=headers['super_admin'])
                if detail.status_code==200:return detail.json()['data']
                await asyncio.sleep(.1)
            raise AssertionError('durable call log missing')
        record=await call(body);assert record['request_body'] is None and record['response_body'] is None
        await patch(logging={'save_request_body':True,'save_response_body':True,'redaction_rules':[PRIVATE]})
        record=await call(body);raw=json.dumps([record['request_body'],record['response_body']]);assert '[REDACTED]' in raw
        for value in (PRIVATE,'topsecret','sk-requestkey84925','sk-privatekey84925',seed.KEY,seed.SECRET):assert value not in raw
        assert record['request_body']['password']=='[REDACTED]' and len(raw.encode())<32768
        streamed=await call({**body,'stream':True});assert streamed['response_body']['stream'] is True and PRIVATE not in json.dumps(streamed['response_body'])
        large=await call({**body,'messages':[{'role':'user','content':'large-stream'}],'stream':True});assert large['response_body']['truncated'] is True and len(json.dumps(large['response_body'],ensure_ascii=False).encode())<=16384
        listing=(await c.get('/api/admin/call-logs',headers=headers['admin'],params={'request_id':record['request_id']})).json()['data']['items'][0]
        assert 'request_body' not in listing and 'response_body' not in listing
        assert (await c.get('/api/admin/call-logs/'+record['request_id'],headers=headers['user'])).status_code==403
        await patch(logging={'save_request_body':False,'save_response_body':False,'redaction_rules':[]})
        record=await call(body);assert record['request_body'] is None and record['response_body'] is None
        print('PASS: default-disabled actual Chat/SSE body previews; built-in/custom redaction; bounded previews; detail permission; list omission; instant disable',flush=True)
        await patch(gateway={'max_body_bytes':1024,'nonstream_timeout':1,'sticky_timeout':7,'health_check_interval':1})
        r=await c.post('/v1/chat/completions',headers=key,json={**body,'messages':[{'role':'user','content':'x'*1500}]});assert r.status_code==413
        r=await c.post('/v1/chat/completions',headers=key,json={**body,'messages':[{'role':'user','content':'slow'}]});assert r.status_code==504,r.text[:100]
        for _ in range(40):
            if gets:break
            await asyncio.sleep(.1)
        assert gets and all(path.endswith('/models') for path in gets)
        await patch(gateway=original['gateway'],security={'jwt_expire':60})
        r=await c.post('/api/auth/login',json={'username':'isolated-final-user','password':PASSWORD});claims=jwt.decode(r.json()['data']['access_token'],options={'verify_signature':False});assert claims['exp']-claims['iat']==60
        await patch(security=original['security'])
        print('PASS: live ASGI body bound, actual upstream timeout, optional non-generating health poll, access-token lifetime; defaults restored',flush=True)
        async with session_factory.begin() as db:
            await db.execute(update(CallLog).where(CallLog.request_id==record['request_id']).values(created_at=now()-timedelta(days=367)))
            before=await db.scalar(select(func.count()).select_from(CallLog))
        await operations_settings.load();await operations_jobs.retention()
        async with session_factory() as db:
            assert await db.scalar(select(CallLog.id).where(CallLog.request_id==record['request_id'])) is None
            assert await db.scalar(select(func.count()).select_from(CallLog))>=before-1
        # Keep branding/user/provider/call records for host restart and browser validation.
        print('PASS: bounded expired-log retention; current records retained; database-backed fixture left for persistence validation',flush=True)
    server.shutdown();await engine.dispose()

asyncio.run(main())
