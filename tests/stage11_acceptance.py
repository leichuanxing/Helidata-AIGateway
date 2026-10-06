"""Real four-level admission/queue and durable quota acceptance; temporary identities."""
import asyncio
from datetime import datetime,timedelta,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import select as socket_select
import secrets
import subprocess
import threading
import time
from unittest.mock import patch
import httpx
from sqlalchemy import select,delete
import yaml
import stage11_nonstream_regression as seed
from app.core.redis import redis_client
from app.core.security import now,hash_password,digest
from app.gateway import quota,provider_concurrency
from app.gateway.admission import QUEUE
from app.models.quota import QuotaBucket,QuotaReservation

gate=threading.Event();mode='normal';active=0;peak=0;calls=[];lock=threading.Lock()
KEY2='sk-hd-'+secrets.token_urlsafe(32)
CONFIG=Path('/data/config/config.yaml');original_config=CONFIG.read_text()

class Fixture(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        global active,peak
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert self.headers.get('Authorization')=='Bearer '+seed.SECRET and body['model']=='private-upstream-model'
        current=mode;calls.append(self.headers['X-Request-ID'])
        with lock:active+=1;peak=max(peak,active)
        usage={'prompt_tokens':1,'completion_tokens':4,'total_tokens':5}
        def hold():
            until=time.monotonic()+8
            while not gate.is_set() and time.monotonic()<until:
                ready,_,_=socket_select.select([self.connection],[],[],.02)
                if ready and self.connection.recv(1)==b'':return False
            return True
        try:
            streaming=body.get('stream',False)
            if current=='hold' and not streaming and not hold():return
            status=500 if current=='fail' else 400 if current=='bad' else 200
            self.send_response(status);self.send_header('Content-Type','text/event-stream' if streaming and status==200 else 'application/json');self.end_headers()
            if status!=200:self.wfile.write(b'{"error":"fixture failure"}');return
            if streaming:
                chunk={'id':'fixture','object':'chat.completion.chunk','created':1791110000,'model':body['model'],
                    'choices':[{'index':0,'delta':{'content':'fixture'},'finish_reason':None}]}
                self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode());self.wfile.flush()
                if current=='usage_hold':
                    chunk['choices']=[];chunk['usage']=usage
                    self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode());self.wfile.flush()
                if current in ('hold','usage_hold') and not hold():return
                if current!='usage_hold':
                    chunk['choices']=[];chunk['usage']=usage
                    self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
                self.wfile.write(b'data: [DONE]\n\n')
            else:
                response={'id':'fixture','object':'chat.completion','created':1791110000,'model':body['model'],
                    'choices':[{'index':0,'message':{'role':'assistant','content':'fixture'},'finish_reason':'stop'}],'usage':usage}
                self.wfile.write(json.dumps(response).encode())
        except (BrokenPipeError,ConnectionResetError):pass
        finally:
            with lock:active-=1

async def wait_until(predicate,timeout=5):
    start=time.monotonic()
    while True:
        value=predicate()
        if asyncio.iscoroutine(value):value=await value
        if value:return
        assert time.monotonic()-start<timeout,'timed out waiting for fixture/admission cleanup'
        await asyncio.sleep(.03)

async def counts():
    slots=['gateway:concurrency',f'group:{seed.ids["ug"]}:concurrency',f'apikey:{seed.ids["key"]}:concurrency',f'provider:{seed.ids["provider"]}:concurrency']
    return [await redis_client.zcard(slot) for slot in slots]

async def clean():return not active and not any(await counts()) and not await redis_client.zcard(QUEUE)

async def group(**values):
    async with seed.session_factory.begin() as db:
        row=await db.get(seed.UserGroup,seed.ids['ug'],with_for_update=True)
        for k,v in values.items():setattr(row,k,v)

async def provider(**values):
    async with seed.session_factory.begin() as db:
        row=await db.get(seed.Provider,seed.ids['provider'],with_for_update=True)
        for k,v in values.items():setattr(row,k,v)

async def clear_quota():
    async with seed.session_factory.begin() as db:
        await db.execute(delete(QuotaReservation).where(QuotaReservation.group_id==seed.ids['ug']))
        await db.execute(delete(QuotaBucket).where(QuotaBucket.group_id==seed.ids['ug']))

async def configure(client,**values):
    config=yaml.safe_load(original_config);config['gateway'].update(values)
    CONFIG.write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False))
    subprocess.run(['supervisorctl','restart','uvicorn'],check=True,stdout=subprocess.DEVNULL)
    for _ in range(50):
        try:
            if (await client.get('/health')).status_code==200:return
        except httpx.HTTPError:pass
        await asyncio.sleep(.1)
    raise AssertionError('gateway failed to restart')

async def main():
    global mode,peak
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);server.daemon_threads=True
    seed.URL='http://127.0.0.1:'+str(server.server_port);threading.Thread(target=server.serve_forever,daemon=True).start()
    await seed.seed()
    password=secrets.token_urlsafe(32)+'aA1!'
    async with seed.session_factory.begin() as db:
        role_id=await db.scalar(select(seed.Role.id).where(seed.Role.code=='admin'))
        user=await db.get(seed.User,seed.ids['user']);user.role='admin';user.role_id=role_id;user.password_hash=await hash_password(password)
        second=seed.ApiKey(user_id=user.id,name=seed.PREFIX+'-second',key_hash=digest(KEY2),prefix=KEY2[:12],suffix=KEY2[-4:]);db.add(second);await db.flush();seed.ids['key2']=second.id
    await group(max_concurrency=10,key_max_concurrency=10);await provider(max_concurrency=20)
    body={'model':seed.NAME,'messages':[{'role':'user','content':'fixture'}],'stream':False,'max_completion_tokens':4}
    tasks=[]
    async with httpx.AsyncClient(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+seed.KEY},timeout=15) as client:
      try:
        await configure(client,max_concurrency=2,queue_size=1,queue_timeout=2)
        login=await client.post('/api/auth/login',json={'username':seed.PREFIX,'password':password});assert login.status_code==200
        admin={'Authorization':'Bearer '+login.json()['data']['access_token']}
        async def request(headers=None):return await client.post('/v1/chat/completions',json=body,headers=headers)
        async def status():return (await client.get('/api/admin/resource-status',headers=admin)).json()['data']
        async def queued(n):return await redis_client.zcard(QUEUE)==n
        async def snapshot():
            async with seed.session_factory() as db:return await quota.snapshot(await db.get(seed.UserGroup,seed.ids['ug']))

        mode='hold';gate.clear();tasks=[asyncio.create_task(request()) for _ in range(2)]
        await wait_until(lambda:active==2);third=asyncio.create_task(request());tasks.append(third);await wait_until(lambda:queued(1))
        fourth=await request();assert fourth.status_code==429 and fourth.json()['error']['code']=='QUEUE_FULL'
        assert await counts()==[2,2,2,2] and (await status())['queued_requests']==1
        before=len(calls);await asyncio.sleep(.15);assert len(calls)==before
        gate.set();assert all(response.status_code==200 for response in await asyncio.gather(*tasks));tasks=[]
        await wait_until(clean);assert (await snapshot())['reported_tokens']==15
        print('PASS: real Gateway Max=2/Queue=1: two execute, one waits without partial slots/upstream call, fourth429; FIFO promotion and actual usage settlement')

        gate.clear();tasks=[asyncio.create_task(request()) for _ in range(2)];await wait_until(lambda:active==2)
        response=await request();assert response.status_code==429 and response.json()['error']['code']=='QUEUE_TIMEOUT'
        queued_task=asyncio.create_task(request());tasks.append(queued_task);await wait_until(lambda:queued(1));queued_task.cancel()
        try:await queued_task
        except asyncio.CancelledError:pass
        tasks.remove(queued_task);await wait_until(lambda:queued(0));assert await counts()==[2,2,2,2]
        gate.set();await asyncio.gather(*tasks);tasks=[];await wait_until(clean)
        print('PASS: QUEUE_TIMEOUT, queued client cancellation removes entry and never owns execution slots')
        gate.clear();tasks=[asyncio.create_task(request()) for _ in range(2)];await wait_until(lambda:active==2)
        pending=asyncio.create_task(request({'Authorization':'Bearer '+KEY2}));tasks.append(pending);await wait_until(lambda:queued(1))
        async with seed.session_factory.begin() as db:
            key=await db.get(seed.ApiKey,seed.ids['key2'],with_for_update=True);key.status='disabled'
        revoked=await pending;assert revoked.status_code==401 and revoked.json()['error']['code']=='INVALID_API_KEY'
        tasks.remove(pending);await wait_until(lambda:queued(0))
        async with seed.session_factory.begin() as db:
            key=await db.get(seed.ApiKey,seed.ids['key2'],with_for_update=True);key.status='enabled'
        gate.set();await asyncio.gather(*tasks);tasks=[];await wait_until(clean)
        print('PASS: queued Key revocation revalidated before execution, waiter removed without upstream call')

        await group(max_concurrency=1);gate.clear();first=asyncio.create_task(request());tasks=[first];await wait_until(lambda:active==1)
        second=asyncio.create_task(request({'Authorization':'Bearer '+KEY2}));tasks.append(second);await wait_until(lambda:queued(1))
        assert await counts()==[1,1,1,1]
        await group(max_concurrency=2);await wait_until(lambda:active==2);gate.set();await asyncio.gather(*tasks);tasks=[];await wait_until(clean)
        await group(max_concurrency=10,key_max_concurrency=1);gate.clear()
        first=asyncio.create_task(request());second=asyncio.create_task(request({'Authorization':'Bearer '+KEY2}));tasks=[first,second]
        await wait_until(lambda:active==2);third=asyncio.create_task(request());tasks.append(third);await wait_until(lambda:queued(1))
        assert await redis_client.zcard(f'apikey:{seed.ids["key"]}:concurrency')==1
        gate.set();await asyncio.gather(*tasks);tasks=[];await wait_until(clean)
        print('PASS: shared group cap across Keys, live raised group cap promotes waiter, each Key has independent active cap')

        await group(key_max_concurrency=10);await provider(max_concurrency=1);gate.clear();peak=0
        first=asyncio.create_task(request());tasks=[first];await wait_until(lambda:active==1)
        second=asyncio.create_task(request());tasks.append(second);await wait_until(lambda:queued(1))
        assert await counts()==[1,1,1,1]
        gate.set();await asyncio.gather(*tasks);tasks=[];await wait_until(clean);assert peak==1
        print('PASS: Provider-only saturation queues without holding Gateway/Group/Key partial leases; inherited provider slot never double-counted')

        await provider(max_concurrency=20);gate.clear();first=asyncio.create_task(request());tasks=[first];await wait_until(lambda:active==1)
        first.cancel()
        try:await first
        except asyncio.CancelledError:pass
        tasks=[];await wait_until(clean)
        print('PASS: actual nonstream client disconnect cancels upstream and releases all four levels')

        mode='normal';gate.set();await clear_quota()
        for period in ('daily','monthly','permanent'):
            await group(quota_limit=10000,quota_period=period)
            response=await request();assert response.status_code==200;await wait_until(clean)
            result=await snapshot();assert result['reported_tokens']==5 and result['reserved_budget']==0 and result['unreported_budget']==0
            old='2000-01-01' if period=='daily' else '2000-01'
            if period!='permanent':
                async with seed.session_factory.begin() as db:db.add(QuotaBucket(group_id=seed.ids['ug'],period=period,period_start=old,reported_tokens=10000))
                assert (await request()).status_code==200;await wait_until(clean)
                assert (await snapshot())['reported_tokens']==10
            async with seed.session_factory.begin() as db:
                bucket=await db.get(QuotaBucket,(seed.ids['ug'],period,quota.period_key(period)),with_for_update=True);bucket.reported_tokens=10000
            before=len(calls);response=await request();assert response.status_code==429 and response.json()['error']['code']=='QUOTA_EXCEEDED' and len(calls)==before
        assert quota.period_key('daily',datetime(2026,10,4,15,59,tzinfo=timezone.utc))=='2026-10-04'
        assert quota.period_key('daily',datetime(2026,10,4,16,0,tzinfo=timezone.utc))=='2026-10-05'
        assert quota.period_key('monthly',datetime(2026,10,31,16,0,tzinfo=timezone.utc))=='2026-11'
        assert quota.period_key('permanent',datetime(2000,1,1,tzinfo=timezone.utc))=='all'
        print('PASS: daily/monthly/permanent actual usage, quota-exceeded before network, historical periods isolated, Asia/Shanghai day/month boundaries')

        await clear_quota();amount=len(json.dumps(body,ensure_ascii=False).encode())+4
        await group(quota_limit=amount+10,quota_period='permanent');mode='hold';gate.clear()
        first=asyncio.create_task(request());tasks=[first];await wait_until(lambda:active==1)
        second=await request();assert second.status_code==429 and second.json()['error']['code']=='QUOTA_EXCEEDED'
        assert (await snapshot())['reserved_budget']==amount and active==1
        gate.set();await first;tasks=[];await wait_until(clean);assert (await snapshot())['reported_tokens']==5
        await configure(client,max_concurrency=2,queue_size=1,queue_timeout=2)
        assert (await snapshot())['reported_tokens']==5
        print('PASS: atomic concurrent quota reservation prevents budget oversubscription; actual5 reconciles reservation; restart preserves durable usage')

        await group(quota_limit=0);await clear_quota();mode='hold';gate.clear()
        async with client.stream('POST','/v1/chat/completions',json={**body,'stream':True}) as response:
            assert response.status_code==200
            async for line in response.aiter_lines():
                if line.startswith('data:'):break
        await wait_until(clean);result=await snapshot();assert result['reported_tokens']==0 and result['unreported_budget']>0 and result['reserved_budget']==0
        records=await client.get('/api/admin/user-groups/'+str(seed.ids['ug'])+'/quota-reservations',headers=admin)
        assert records.status_code==200 and len(records.json()['data'])==1
        ident=records.json()['data'][0]['id'];endpoint='/api/admin/user-groups/'+str(seed.ids['ug'])+'/quota-reservations/'+ident
        async with seed.session_factory.begin() as db:
            rid=await db.scalar(select(seed.Role.id).where(seed.Role.code=='user'));user=await db.get(seed.User,seed.ids['user']);user.role='user';user.role_id=rid
        denied=await client.put(endpoint,json={'reported_tokens':7},headers=admin);assert denied.status_code==403
        async with seed.session_factory.begin() as db:
            rid=await db.scalar(select(seed.Role.id).where(seed.Role.code=='admin'));user=await db.get(seed.User,seed.ids['user']);user.role='admin';user.role_id=rid
        reconciled=await client.put(endpoint,json={'reported_tokens':7},headers=admin);assert reconciled.status_code==200
        assert (await client.put(endpoint,json={'reported_tokens':7},headers=admin)).status_code==409
        own=await client.get('/api/portal/quota',headers=admin);assert own.status_code==200 and own.json()['data']['reported_tokens']==7 and own.json()['data']['unreported_budget']==0
        print('PASS: authorized explicit usage reconciliation is audited/idempotent, ordinary user denied, own quota summary reflects known vs unreported budget')
        await clear_quota();mode='usage_hold'
        async with client.stream('POST','/v1/chat/completions',json={**body,'stream':True}) as response:
            async for line in response.aiter_lines():
                if 'total_tokens' in line:break
        await wait_until(clean);result=await snapshot();assert result['reported_tokens']==5 and result['unreported_budget']==0
        print('PASS: stream cancellation without usage retains explicitly unreported budget; cancellation after actual usage settles5; four levels released')
        async with seed.session_factory.begin() as db:
            period='permanent';start=quota.period_key(period)
            bucket=await db.get(QuotaBucket,(seed.ids['ug'],period,start),with_for_update=True);bucket.reserved_budget+=20
            db.add(QuotaReservation(id='req_expired_'+seed.PREFIX,group_id=seed.ids['ug'],period=period,period_start=start,budget=20,state='active',expires_at=now()-timedelta(seconds=1)))
        recovered=await snapshot();assert recovered['reserved_budget']==0 and recovered['unreported_budget']==20
        async with seed.session_factory() as db:
            stale=await db.get(QuotaReservation,'req_expired_'+seed.PREFIX);assert stale.state=='unreported'
        print('PASS: crash-expired quota reservation converts to unreported hold, never silently refunded or fabricated as usage')
        mode='normal';before=len(calls)
        existing=(await client.get('/api/admin/user-groups/'+str(seed.ids['ug']),headers=admin)).json()['data']
        group_input={name:existing[name] for name in ('name','description','status','quota_limit','quota_period','max_concurrency','key_max_concurrency','model_group_ids')}
        workload=[client.post('/api/gateway/preflight',json={'model':seed.NAME}) for _ in range(24)]
        workload+=[client.get('/api/admin/user-groups',params={'q':seed.PREFIX},headers=admin) for _ in range(12)]
        workload+=[client.put('/api/admin/user-groups/'+str(seed.ids['ug']),json=group_input,headers=admin) for _ in range(4)]
        results=await asyncio.gather(*workload);assert all(response.status_code==200 for response in results)
        assert len(calls)==before and not any(await counts())
        print('PASS: 24 preflights +12 group reads +4 group updates complete concurrently without DB pool/lock starvation or upstream use')

        await clear_quota();mode='bad';response=await request();assert response.status_code==400;await wait_until(clean)
        assert (await snapshot())['unreported_budget']==0
        mode='fail';response=await request();assert response.status_code==502;await wait_until(clean)
        assert (await snapshot())['unreported_budget']>0
        await provider(health_status='unknown',failure_count=0,cooldown_until=None)
        mode='hold';gate.clear()
        from app.main import app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test',headers={'Authorization':'Bearer '+seed.KEY}) as local:
            with patch('app.gateway.upstream.CHAT_TIMEOUT_SECONDS',.05):
                response=await local.post('/v1/chat/completions',json=body);assert response.status_code==504
        await wait_until(clean)
        print('PASS: upstream parameter errors release unused budget; failure/timeout preserve uncertain consumption and release all slots')
      finally:
        gate.set()
        for task in tasks:
            if not task.done():task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        await wait_until(clean)
        CONFIG.write_text(original_config);subprocess.run(['supervisorctl','restart','uvicorn'],check=True,stdout=subprocess.DEVNULL)
        server.shutdown();server.server_close()
        async with seed.session_factory.begin() as db:
            await db.execute(delete(seed.User).where(seed.User.id==seed.ids['user']))
            await db.execute(delete(seed.UserGroup).where(seed.UserGroup.id==seed.ids['ug']))
            await db.execute(delete(seed.ModelGroup).where(seed.ModelGroup.id==seed.ids['mg']))
            await db.execute(delete(seed.ProviderModelMapping).where(seed.ProviderModelMapping.provider_id==seed.ids['provider']))
            await db.execute(delete(seed.Provider).where(seed.Provider.id==seed.ids['provider']))
            await db.execute(delete(seed.LogicalModel).where(seed.LogicalModel.name.in_([seed.NAME,seed.EMBED])))
        keys=[k async for k in redis_client.scan_iter(match=f'sticky:{seed.ids["key"]}:*')]
        keys.extend([k async for k in redis_client.scan_iter(match=f'sticky:{seed.ids["key2"]}:*')])
        if keys:await redis_client.delete(*keys)
        await redis_client.aclose();await seed.engine.dispose()
        print('PASS: original Gateway configuration restored and temporary quota/identity records removed')

if __name__=='__main__':asyncio.run(main())
