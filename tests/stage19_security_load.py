"""Real HTTP/DB/Redis acceptance in a disposable container, never production."""
import asyncio, json, threading, time, subprocess, uuid
from datetime import timedelta
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import httpx, jwt
from sqlalchemy import select, func, text
import stage12_nonstream_regression as seed
from app.core.database import session_factory, engine
from app.core.config import get_settings
from app.core.security import decode_token, now, access_token, digest
from app.core.exceptions import APIError
from app.models.user import UserGroup, Provider, User, Role, RefreshSession
from app.models.call_log import CallLog
from app.providers.base import OpenAIProvider
from app.providers.pool import pools, ProviderPools, PoolCapacityError

ports=set(); cookies=[]


class Fixture(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass
    def do_POST(self):
        ports.add(self.client_address[1]); cookies.append(self.headers.get('Cookie'))
        payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert self.headers.get('Authorization')=='Bearer '+seed.SECRET
        assert self.headers.get('X-Request-ID','').startswith('req_')
        assert payload['model']=='private-upstream-model'
        if payload.get('stream'):
            self.send_response(200);self.send_header('Content-Type','text/event-stream')
            self.send_header('Connection','close');self.end_headers();self.close_connection=True
            try:
                for index in range(45):
                    value={'id':'chatcmpl-stage19','object':'chat.completion.chunk','created':1791110000,
                        'model':'private-upstream-model','choices':[{'index':0,'delta':{'content':'x'},'finish_reason':None}]}
                    self.wfile.write(('data: '+json.dumps(value)+'\n\n').encode());self.wfile.flush();time.sleep(1)
                value['choices']=[];value['usage']={'prompt_tokens':4,'completion_tokens':2,'total_tokens':6}
                self.wfile.write(('data: '+json.dumps(value)+'\n\ndata: [DONE]\n\n').encode());self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError):pass
            return
        seed.calls.append((self.path,payload,{}))
        answer={'id':'chatcmpl-stage19','object':'chat.completion','created':1791110000,'model':'private-upstream-model',
            'choices':[{'index':0,'message':{'role':'assistant','content':'isolated-response'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':4,'completion_tokens':2,'total_tokens':6}}
        raw=json.dumps(answer).encode()
        self.send_response(200);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(raw)));self.send_header('Set-Cookie','private_auth=must-not-forward; Path=/')
        self.end_headers();self.wfile.write(raw)


class Server(ThreadingHTTPServer):
    request_queue_size=2048
    daemon_threads=True


def usage():
    pid=int(subprocess.check_output(['supervisorctl','pid','uvicorn'],text=True))
    fields=Path(f'/proc/{pid}/status').read_text().splitlines()
    rss=int(next(line.split()[1] for line in fields if line.startswith('VmRSS:')))
    return {'rss_kib':rss,'fds':len(list(Path(f'/proc/{pid}/fd').iterdir()))}


async def main():
    server=Server(('127.0.0.1',0),Fixture)
    seed.URL=f'http://127.0.0.1:{server.server_port}'
    threading.Thread(target=server.serve_forever,daemon=True).start()
    await seed.seed()
    await seed.change(UserGroup,'ug',max_concurrency=2000,key_max_concurrency=2000)
    await seed.change(Provider,'provider',max_concurrency=2000)
    async with session_factory.begin() as db:
        role_id=await db.scalar(select(Role.id).where(Role.code=='super_admin'))
        user=await db.get(User,seed.ids['user']);user.role='super_admin';user.role_id=role_id
        sid=str(uuid.uuid4())
        db.add(RefreshSession(id=sid,user_id=user.id,auth_version=user.auth_version,
            token_hash=digest(uuid.uuid4().hex),csrf_hash=digest(uuid.uuid4().hex),expires_at=now()+timedelta(hours=1)))
        admin_token=access_token(user,sid)
    basic={'model':seed.NAME,'messages':[{'role':'user','content':'isolated-load'}],'max_tokens':16}
    async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=180,
            headers={'Authorization':'Bearer '+seed.KEY},
            limits=httpx.Limits(max_connections=1200,max_keepalive_connections=64)) as c:
        # Independently signed malformed claims must reject before a database cast.
        claims={'sub':'1','sid':str(uuid.uuid4()),'ver':0,'type':'access','iss':'helidata-gateway','aud':'helidata-web','iat':int(now().timestamp()),'exp':int(now().timestamp())+60}
        decode_token(jwt.encode(claims,get_settings().security.jwt_secret.get_secret_value(),algorithm='HS256'))
        for field,value in [('sub','0'),('sub','1 OR 1=1'),('sid','not-a-uuid'),('ver',True),('ver','0'),('iat',True)]:
            token=jwt.encode({**claims,field:value},get_settings().security.jwt_secret.get_secret_value(),algorithm='HS256')
            try:decode_token(token)
            except APIError as error:assert error.status_code==401
            else:raise AssertionError('malformed JWT accepted')
        for origin in ['https://127.0.0.1','null','http://127.0.0.1.evil','http://127.0.0.1/path','http://user@127.0.0.1']:
            r=await c.post('/api/auth/login',headers={'Origin':origin},json={'username':'unknown','password':'invalid'})
            assert r.status_code==403 and r.json()['error']['code']=='CSRF_REJECTED'
        page=await c.get('/')
        assert "script-src 'self'" in page.headers['content-security-policy'] and "object-src 'none'" in page.headers['content-security-policy']
        assert (await c.get('/api/admin/runtime')).status_code==401
        # Direct backend bypass of Nginx and chunked body both remain bounded.
        async with httpx.AsyncClient(base_url='http://127.0.0.1:8000',timeout=30) as direct:
            r=await direct.post('/v1/chat/completions',content=b'x'*(10485760+1))
            assert r.status_code==413 and r.json()['error']['code']=='REQUEST_TOO_LARGE'
            async def chunks():
                for _ in range(11):yield b'x'*1048576
            r=await direct.post('/api/auth/login',content=chunks())
            assert r.status_code==413
        adapter=OpenAIProvider(seed.URL+'/normal/v1',seed.SECRET)
        adapter.request_id='req_stage19_direct'
        payload={**basic,'model':'private-upstream-model','stream':False}
        for _ in range(20):await adapter.chat_completion(payload)
        assert len(ports)==1 and not any(cookies) and pools.snapshot()['active_leases']==0
        # Bound proxy cache, and do not evict a live client/SSE lease.
        testpool=ProviderPools(); cfg=get_settings().gateway; previous=cfg.http_proxy_pools;cfg.http_proxy_pools=1
        try:
            async with testpool.acquire():
                try:
                    async with testpool.acquire('http://127.0.0.1:12345'):pass
                except PoolCapacityError:pass
                else:raise AssertionError('active pool evicted')
            async with testpool.acquire('http://127.0.0.1:12345'):pass
            assert testpool.snapshot()['evicted']==1 and testpool.snapshot()['rejected']==1
        finally:cfg.http_proxy_pools=previous;await testpool.close()
        print('PASS security: JWT claims, exact Origin, CSP, direct/chunked body limit, runtime authorization; 20 HTTP/1.1 requests reuse one TCP connection without Cookie forwarding; bounded proxy lease eviction',flush=True)
        ports.clear(); seed.calls.clear(); cookies.clear()
        all_ids=[]; measurements=[]
        before=usage()
        for concurrency in (100,500,1000,100):
            start=time.monotonic()
            results=await asyncio.gather(*(c.post('/v1/chat/completions',json=basic) for _ in range(concurrency)))
            statuses={s:sum(r.status_code==s for r in results) for s in {r.status_code for r in results}}
            assert set(statuses)<={200,429} and statuses.get(200,0)>0,str(statuses)+' '+next((r.text[:200] for r in results if r.status_code not in (200,429)),'')
            assert all(r.status_code==200 or r.json()['error']['code'] in ('QUEUE_FULL','QUEUE_TIMEOUT','PREPARATION_TIMEOUT','PREPARATION_QUEUE_FULL') for r in results)
            rids=[r.headers['X-Request-ID'] for r in results];assert len(set(rids))==concurrency
            all_ids.extend(rids)
            measurement={'client_concurrency':concurrency,'status_counts':statuses,'seconds':round(time.monotonic()-start,3),**usage()}
            measurements.append(measurement);print('LOAD '+json.dumps(measurement),flush=True)
        assert not any(cookies) and len(seed.calls)==sum(m['status_counts'].get(200,0) for m in measurements)
        for _ in range(30):
            async with session_factory() as db:
                count=await db.scalar(select(func.count()).select_from(CallLog).where(CallLog.request_id.in_(all_ids)))
            if count==1700:break
            await asyncio.sleep(2)
        assert count==1700,f'durable logs {count}/1700'
        start=time.monotonic();events=[]
        async with c.stream('POST','/v1/chat/completions',json={**basic,'stream':True}) as response:
            assert response.status_code==200
            async for line in response.aiter_lines():
                if line.startswith('data:'):events.append(line)
        assert time.monotonic()-start>=45 and events[-1]=='data: [DONE]' and len(events)>=46
        for _ in range(3):
            async with c.stream('POST','/v1/chat/completions',json={**basic,'stream':True}) as response:
                assert response.status_code==200
                async for line in response.aiter_lines():
                    if line.startswith('data:'):break
        await asyncio.sleep(3)
        runtime=await c.get('/api/admin/runtime',headers={'Authorization':'Bearer '+admin_token})
        assert runtime.status_code==200
        metrics=runtime.json()['data'];assert metrics['http']['active_leases']==0,metrics
        from app.core.redis import redis_client
        assert await redis_client.zcard('gateway:concurrency')==0
        assert await redis_client.zcard(f'provider:{seed.ids["provider"]}:concurrency')==0
        print('PASS stability: 45-second real gateway SSE across two lease renewals, DONE, three client disconnects, shared HTTP and admission leases return to zero; '+json.dumps(metrics),flush=True)
        # Real service outages: controlled supervisor stop/start within this fixture.
        for service in ('redis','postgresql'):
            subprocess.check_call(['supervisorctl','stop',service],stdout=subprocess.DEVNULL)
            try:
                r=await c.post('/v1/chat/completions',json=basic)
                assert r.status_code>=500 and seed.SECRET not in r.text and seed.KEY not in r.text
            finally:subprocess.check_call(['supervisorctl','start',service],stdout=subprocess.DEVNULL)
            for _ in range(30):
                r=await c.get('/health')
                if r.status_code==200:break
                await asyncio.sleep(1)
            assert r.status_code==200
            await seed.change(Provider,'provider',health_status='healthy',failure_count=0,cooldown_until=None)
            r=await c.post('/v1/chat/completions',json=basic);assert r.status_code==200,r.text[:200]
        await asyncio.sleep(35)
        settled=usage()
        assert settled['fds'] < before['fds']+200, (before,settled)
        assert settled['rss_kib'] < max(m['rss_kib'] for m in measurements)+65536
        async with session_factory() as db:
            indexes=(await db.execute(text("SELECT indexname FROM pg_indexes WHERE tablename='call_logs'"))).scalars().all()
            assert all('ix_call_logs_'+f+'_created_id' in indexes for f in ('provider_id','api_key_id','user_group_id','request_model','logical_model'))
        print('PASS durability: 1700 unique request logs; Redis/Postgres outage and actual request recovery; indexes present; resources '+json.dumps({'before':before,'settled':settled,'upstream_tcp_ports':len(ports)}),flush=True)
    await pools.close(); await engine.dispose()
    # Keep HTTP/1.1 daemon request handlers from holding interpreter shutdown.
    server.shutdown();server.server_close()


if __name__=='__main__':asyncio.run(main())
