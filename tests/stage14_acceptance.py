"""Actual HTTP/Redis/DB operational dashboard and lease lifecycle acceptance."""
import asyncio,json,secrets,socket,select as socket_select,threading,time,uuid
from datetime import timedelta,datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
import httpx
from redis.exceptions import ConnectionError
from sqlalchemy import select,delete,text,func
import stage12_nonstream_regression as seed
from app.models.call_log import CallLog
from app.gateway import call_log
from app.services import dashboard_live
from app.core.redis import redis_client
from app.gateway.admission import QUEUE,STREAMS

gate=threading.Event();active=set();owned=set()
class Fixture(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));rid=self.headers['X-Request-ID'];active.add(rid)
        assert self.headers['Authorization']=='Bearer '+seed.SECRET
        def hold():
            while not gate.is_set():
                ready,_,_=socket_select.select([self.connection],[],[],.03)
                if ready and self.connection.recv(1)==b'':return False
            return True
        try:
            if '/bad/' in self.path:self.send_response(400);self.end_headers();self.wfile.write(b'{"error":"fixture"}');return
            stream=body.get('stream')
            if not stream and not hold():return
            self.send_response(200);self.send_header('Content-Type','text/event-stream' if stream else 'application/json');self.end_headers()
            choice={'index':0,'delta':{'content':'test content'},'finish_reason':None}
            answer={'id':'fixture','object':'chat.completion.chunk' if stream else 'chat.completion','created':1791110000,'model':'private-upstream-model','choices':[choice] if stream else [{'index':0,'message':{'role':'assistant','content':'test'},'finish_reason':'stop'}]}
            if stream:
                self.wfile.write(('data: '+json.dumps(answer)+'\n\n').encode());self.wfile.flush()
                if not hold():return
                answer['choices']=[];answer['usage']={'prompt_tokens':4,'completion_tokens':2,'total_tokens':6}
                self.wfile.write(('data: '+json.dumps(answer)+'\n\ndata: [DONE]\n\n').encode())
            else:
                answer['usage']={'prompt_tokens':4,'completion_tokens':2,'total_tokens':6};self.wfile.write(json.dumps(answer).encode())
        except (BrokenPipeError,ConnectionResetError):pass
        finally:active.discard(rid)

async def until(check,timeout=8):
    start=time.monotonic()
    while True:
        result=check();result=await result if asyncio.iscoroutine(result) else result
        if result:return
        assert time.monotonic()-start<timeout,'fixture condition timeout'
        await asyncio.sleep(.05)

async def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);server.daemon_threads=True
    seed.URL='http://127.0.0.1:'+str(server.server_port);threading.Thread(target=server.serve_forever,daemon=True).start();await seed.seed()
    password=secrets.token_urlsafe(24)+'aA1!'
    async with seed.session_factory.begin() as db:
        role=await db.scalar(select(seed.Role.id).where(seed.Role.code=='admin'));user=await db.get(seed.User,seed.ids['user']);user.role='admin';user.role_id=role;user.password_hash=await seed.hash_password(password)
        group=await db.get(seed.UserGroup,seed.ids['ug']);group.max_concurrency=2
    tasks=[];stream=None
    async def capture(response):
        if response.headers.get('X-Request-ID'):owned.add(response.headers['X-Request-ID'])
    async with httpx.AsyncClient(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+seed.KEY},timeout=40,event_hooks={'response':[capture]}) as client:
      try:
        r=await client.post('/api/auth/login',json={'username':seed.PREFIX,'password':password});assert r.status_code==200
        admin={'Authorization':'Bearer '+r.json()['data']['access_token']}
        body={'model':seed.NAME,'messages':[{'role':'user','content':'fixture'}]}
        stream_context=client.stream('POST','/v1/chat/completions',json={**body,'stream':True});stream=await stream_context.__aenter__();assert stream.status_code==200
        lines=stream.aiter_lines()
        async for line in lines:
            if line.startswith('data:'):break
        nonstream=asyncio.create_task(client.post('/v1/chat/completions',json=body));tasks.append(nonstream)
        await until(lambda:len(active)==2)
        queued=asyncio.create_task(client.post('/v1/chat/completions',json=body));tasks.append(queued)
        async def queued_one():return await redis_client.zcard(QUEUE)==1
        await until(queued_one)
        r=await client.get('/api/admin/dashboard',headers=admin);assert r.status_code==200,r.text;data=r.json()['data']
        assert data['live']['active']==2 and data['live']['streaming']==1 and data['live']['queued']==1,data['live']
        assert next(x for x in data['providers'] if x['id']==seed.ids['provider'])['current_concurrency']==2
        assert next(x for x in data['groups'] if x['id']==seed.ids['ug'])['current_concurrency']==2
        raw=json.dumps(data);assert seed.SECRET not in raw and seed.KEY not in raw and seed.URL not in raw and 'api_key_encrypted' not in raw
        score=await redis_client.zscore(STREAMS,stream.headers['X-Request-ID'])
        await asyncio.sleep(21)
        renewed=await redis_client.zscore(STREAMS,stream.headers['X-Request-ID']);assert renewed>score+10,(score,renewed)
        await dashboard_live.sample_once()
        hist=await dashboard_live.history(datetime.now(timezone.utc)-timedelta(hours=1),datetime.now(timezone.utc),'hour')
        assert hist and hist[-1]['active']>=2 and hist[-1]['streaming']>=1 and hist[-1]['queued']>=1
        print('PASS: real long SSE+nonstream+queued request -> active2 stream1 queue1, per-Provider/group2; streaming TTL renews and real minute peaks sampled; no credentials/URLs')
        queued.cancel();await asyncio.gather(queued,return_exceptions=True);tasks.remove(queued)
        await stream.aclose();stream=None;await stream_context.__aexit__(None,None,None)
        gate.set();r=await nonstream;assert r.status_code==200;tasks=[]
        async def released():return not active and await redis_client.zcard('gateway:concurrency')==0 and await redis_client.zcard(STREAMS)==0 and await redis_client.zcard(QUEUE)==0
        await until(released)
        # Expired and orphaned streaming leases never inflate counts.
        token='stage14-expired-'+uuid.uuid4().hex
        await redis_client.zadd(STREAMS,{token:time.time()+90,token+'expired':time.time()-1})
        assert (await dashboard_live.snapshot())['streaming']==0
        assert await redis_client.zscore(STREAMS,token) is None
        print('PASS: queued cancel/SSE disconnect/success release all four levels and stream count; stale/orphan leases removed')
        gate.set()
        r=await client.post('/v1/chat/completions',json={**body,'stream':True});assert r.status_code==200
        await seed.change(seed.Provider,'provider',base_url=seed.URL+'/bad/v1');r=await client.post('/v1/chat/completions',json=body);assert r.status_code==400
        await until(released)
        await asyncio.sleep(.2)
        # Add fixture historical dimensions through the production idempotent writer; ranking Top10+other preserves totals.
        async with seed.session_factory() as db:
            normal=await db.scalar(select(CallLog).where(CallLog.request_model==seed.NAME,CallLog.status=='success').limit(1))
            base={c.name:getattr(normal,c.name) for c in CallLog.__table__.columns if c.name!='id'}
        historical=[]
        for index in range(12):
            record={**base,'request_id':'req_'+uuid.uuid4().hex,'created_at':datetime.now(timezone.utc)-timedelta(days=2,hours=index),
                'provider_id':seed.ids['provider']+100000+index,'logical_model':seed.NAME+'-rank-'+str(index),'total_tokens':index+1}
            historical.append(record);owned.add(record['request_id']);await call_log.persist(record)
        for period in ('1h','24h','7d','30d'):
            r=await client.get('/api/admin/dashboard',headers=admin,params={'period':period});assert r.status_code==200,r.text;data=r.json()['data']
            start=datetime.fromisoformat(data['start']);end=datetime.fromisoformat(data['end']);today=datetime.fromisoformat(data['today_start'])
            async with seed.session_factory() as db:
                records=(await db.scalars(select(CallLog).where(CallLog.operation=='chat',CallLog.created_at>=start,CallLog.created_at<end))).all()
            assert data['summary']['requests']==len(records)
            assert data['summary']['failure']==sum(x.status!='success' for x in records)
            assert data['summary']['total_tokens']==sum(x.total_tokens or 0 for x in records)
            assert data['summary']['active_users']==len({x.user_id for x in records if x.user_id})
            assert data['today']['requests']==sum(x.created_at>=today for x in records) if period!='1h' else data['today']['requests']>=len(records)
            for dimension in ('provider','model'):
                rank=data['rankings'][dimension]
                assert sum(x['requests'] for x in rank)==len(records)
                assert sum(x['total_tokens'] or 0 for x in rank)==sum(x.total_tokens or 0 for x in records)
                if period in ('7d','30d'):assert len(rank)==11 and rank[-1]['other']
            assert data['timezone']=='Asia/Shanghai' and len(data['providers'])<=100
        assert (await client.get('/api/admin/dashboard',headers=admin,params={'period':'bad'})).status_code==422
        assert (await client.get('/api/admin/dashboard',headers={'Authorization':''})).status_code==401
        async with seed.session_factory.begin() as db:
            role=await db.scalar(select(seed.Role.id).where(seed.Role.code=='user'));user=await db.get(seed.User,seed.ids['user']);user.role='user';user.role_id=role
        assert (await client.get('/api/admin/dashboard',headers=admin)).status_code==403
        async with seed.session_factory.begin() as db:
            role=await db.scalar(select(seed.Role.id).where(seed.Role.code=='admin'));user=await db.get(seed.User,seed.ids['user']);user.role='admin';user.role_id=role
        # Fault isolation through the actual route: usage survives unavailable Redis, live counters are null.
        from app.main import app
        async def unavailable(*args,**kwargs):raise ConnectionError('injected unavailable')
        with patch.object(dashboard_live,'snapshot',unavailable),patch.object(dashboard_live,'history',unavailable):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as local:
                r=await local.get('/api/admin/dashboard',headers=admin);assert r.status_code==200,r.text
                data=r.json()['data'];assert data['live']['active'] is None and not data['live']['available'] and not data['history_available']
                assert all(x['current_concurrency'] is None for x in data['providers'])
        print('PASS: all four ranges match actual logs/today/timezone/weighted stats, Top10+other preserves totals/deleted identity; admin/user/anonymous/invalid-period gates and Redis failure -> unknown, usage intact')
      finally:
        gate.set()
        if stream:await stream.aclose()
        for task in tasks:
            if not task.done():task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True);await until(lambda:not active)
        server.shutdown();server.server_close();await asyncio.sleep(.3)
        async with seed.session_factory.begin() as db:
            await db.execute(delete(CallLog).where(CallLog.request_model.in_([seed.NAME,seed.EMBED])))
            for table in ('usage_hourly','usage_daily'):await db.execute(text(f'DELETE FROM {table} WHERE request_model IN (:name,:embed)'),{'name':seed.NAME,'embed':seed.EMBED})
            await db.execute(delete(seed.User).where(seed.User.id==seed.ids['user']))
            await db.execute(delete(seed.UserGroup).where(seed.UserGroup.id==seed.ids['ug']))
            await db.execute(delete(seed.ModelGroup).where(seed.ModelGroup.id==seed.ids['mg']))
            await db.execute(delete(seed.ProviderModelMapping).where(seed.ProviderModelMapping.provider_id==seed.ids['provider']))
            await db.execute(delete(seed.Provider).where(seed.Provider.id==seed.ids['provider']))
            await db.execute(delete(seed.LogicalModel).where(seed.LogicalModel.name.in_([seed.NAME,seed.EMBED])))
        keys=[k async for k in redis_client.scan_iter(match=f'sticky:{seed.ids["key"]}:*')]
        if keys:await redis_client.delete(*keys)
        await redis_client.aclose();await seed.engine.dispose()
        print('PASS: test identities, terminal facts/aggregates cleaned; actual concurrency samples intentionally retained as operational history')

if __name__=='__main__':asyncio.run(main())
