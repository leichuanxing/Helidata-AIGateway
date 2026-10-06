"""Real account/model failover, Redis admission and persistent health acceptance."""
import asyncio
from datetime import timedelta
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import select as socket_select
import secrets
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from redis.exceptions import RedisError
from sqlalchemy import select,delete
import stage11_nonstream_regression as seed
from app.core.redis import redis_client
from app.gateway import provider_concurrency,provider_health
from app.core.exceptions import APIError
from app.core.security import now,hash_password

NEXT=seed.PREFIX+'-next';extra=[];trace=[];modes={'A':'normal','B':'normal','C':'normal'}
gates={name:threading.Event() for name in modes};active={name:0 for name in modes};lock=threading.Lock()

class Fixture(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
        self.wfile.write(b'{"data":[{"id":"private-probe-model"}]}')
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        name=self.path.split('/')[1];mode=modes[name]
        assert self.headers.get('Authorization')=='Bearer '+seed.SECRET
        assert body['model'].startswith('private-')
        trace.append((name,body['model'],body.get('stream',False),self.headers['X-Request-ID']))
        with lock:active[name]+=1
        try:
            if mode.startswith('hold') and not body.get('stream'):
                until=time.monotonic()+5
                while not gates[name].is_set() and time.monotonic()<until:
                    ready,_,_=socket_select.select([self.connection],[],[],.02)
                    if ready and self.connection.recv(1)==b'':return
            status=500 if mode in ('fail','hold_fail') else 401 if mode=='auth' else 400 if mode=='bad' else 429 if mode=='rate' else 200
            streaming=body.get('stream',False) and status==200
            self.send_response(status);self.send_header('Content-Type','text/event-stream' if streaming else 'application/json');self.end_headers()
            if status!=200:
                self.wfile.write(json.dumps({'error':seed.SECRET+' '+seed.KEY}).encode());return
            if streaming:
                chunk={'id':'fixture','object':'chat.completion.chunk','created':1791110000,'model':body['model'],'choices':[{'index':0,'delta':{'content':name},'finish_reason':None}]}
                self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode());self.wfile.flush()
                if mode=='stream_error':self.wfile.write(b'event: error\ndata: private error\n\n')
                else:self.wfile.write(b'data: [DONE]\n\n')
            else:
                response={'id':'fixture','object':'chat.completion','created':1791110000,'model':body['model'],
                    'choices':[{'index':0,'message':{'role':'assistant','content':name},'finish_reason':'stop'}]}
                self.wfile.write(json.dumps(response).encode())
        except (BrokenPipeError,ConnectionResetError):pass
        finally:
            with lock:active[name]-=1

async def wait_until(predicate):
    start=time.monotonic()
    while not predicate():
        assert time.monotonic()-start<3,'timed out waiting for real upstream'
        await asyncio.sleep(.02)

async def edit(name,**values):
    async with seed.session_factory.begin() as db:
        row=await db.get(seed.Provider,seed.ids[name])
        for k,v in values.items():setattr(row,k,v)

async def row(name):
    async with seed.session_factory() as db:return await db.get(seed.Provider,seed.ids[name])

async def clear_sticky():
    keys=[k async for k in redis_client.scan_iter(match=f'sticky:{seed.ids["key"]}:*')]
    if keys:await redis_client.delete(*keys)

async def reset():
    await clear_sticky();trace.clear()
    for name in modes:
        modes[name]='normal';gates[name].clear()
        await edit(name,status='enabled',health_status='unknown',cooldown_until=None,failure_count=0,priority={'A':100,'B':90,'C':80}[name],max_concurrency=1)

async def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);server.daemon_threads=True
    seed.URL='http://127.0.0.1:'+str(server.server_port);threading.Thread(target=server.serve_forever,daemon=True).start()
    await seed.seed();seed.ids['A']=seed.ids['provider']
    password=secrets.token_urlsafe(32)+'aA1!'
    async with seed.session_factory.begin() as db:
        db.add(seed.LogicalModel(name=NEXT,model_type='text'));await db.flush()
        db.add(seed.ModelGroupModel(model_group_id=seed.ids['mg'],logical_model=NEXT,position=2))
        for name,logical in [('B',seed.NAME),('C',NEXT)]:
            provider=seed.Provider(name=seed.PREFIX+'-'+name,provider_type='custom_openai',protocol='openai',base_url=seed.URL+'/'+name+'/v1',api_key_encrypted=seed.encrypt_secret(seed.SECRET),max_concurrency=1)
            db.add(provider);await db.flush();seed.ids[name]=provider.id;extra.append(provider.id)
            db.add(seed.ProviderModelMapping(provider_id=provider.id,logical_model=logical,upstream_model='private-'+name,model_type='text'))
        role_id=await db.scalar(select(seed.Role.id).where(seed.Role.code=='admin'))
        u=await db.get(seed.User,seed.ids['user']);u.password_hash=await hash_password(password);u.role='admin';u.role_id=role_id
    await edit('A',base_url=seed.URL+'/A/v1');await reset()
    payload={'model':seed.NAME,'messages':[{'role':'user','content':'fixture'}],'stream':False}
    async with httpx.AsyncClient(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+seed.KEY},timeout=15) as client:
      try:
        login=await client.post('/api/auth/login',json={'username':seed.PREFIX,'password':password})
        assert login.status_code==200;admin={'Authorization':'Bearer '+login.json()['data']['access_token']}
        async def detail(name):
            response=await client.get('/api/admin/providers/'+str(seed.ids[name]),headers=admin)
            assert response.status_code==200;return response.json()['data']
        async def call(expected=200,body=None):
            response=await client.post('/v1/chat/completions',json=body or payload)
            assert response.status_code==expected,(response.status_code,response.text[:120])
            assert seed.SECRET not in response.text and seed.KEY not in response.text and 'private-' not in response.text
            if expected==200 and not (body or payload)['stream']:assert response.json()['model']==seed.NAME
            if (body or payload)['stream']:
                # HTTP EOF can precede the shielded terminal bookkeeping/slot release.
                start=time.monotonic()
                while any((await provider_concurrency.loads([await row(name) for name in modes])).values()):
                    assert time.monotonic()-start<3
                    await asyncio.sleep(.02)
            return response

        modes['A']='fail';response=await call();assert response.json()['choices'][0]['message']['content']=='B'
        assert [t[0] for t in trace]==['A','B'] and len({t[3] for t in trace})==1
        trace.clear();modes['A']='normal';await call();assert [t[0] for t in trace]==['B']
        sticky=[k async for k in redis_client.scan_iter(match=f'sticky:{seed.ids["key"]}:*')]
        assert len(sticky)==1 and seed.KEY not in sticky[0] and await redis_client.ttl(sticky[0])>1700
        print('PASS: A failure -> B success; common Request ID; sticky chooses successful B over higher priority A; TTL and Key privacy')

        await reset();modes['A']=modes['B']='fail';response=await call()
        assert [t[0] for t in trace]==['A','B','C'] and trace[-1][1]=='private-C'
        assert response.json()['choices'][0]['message']['content']=='C'
        await reset();await edit('A',status='disabled');await edit('B',status='disabled')
        async with seed.session_factory.begin() as db:
            await db.execute(delete(seed.ModelGroupModel).where(seed.ModelGroupModel.model_group_id==seed.ids['mg'],seed.ModelGroupModel.logical_model==NEXT))
        await call(503);assert trace==[]
        async with seed.session_factory.begin() as db:db.add(seed.ModelGroupModel(model_group_id=seed.ids['mg'],logical_model=NEXT,position=2))
        print('PASS: exhausted same-model accounts -> ordered authorized same-type next model, requested alias restored; removed membership cannot be used')

        await reset();modes['A']='hold';task=asyncio.create_task(call());await wait_until(lambda:active['A']==1)
        d=await detail('A');assert d['current_concurrency']==1 and d['scheduling_state']=='Available'
        await redis_client.set(sticky[0],str(seed.ids['A']),ex=1800)
        second=await call();assert second.json()['choices'][0]['message']['content']=='B'
        gates['A'].set();await task;await wait_until(lambda:not any(active.values()))
        assert (await detail('A'))['current_concurrency']==0
        await reset();await edit('A',priority=90,max_concurrency=2);await edit('B',max_concurrency=2)
        modes['A']='hold';task=asyncio.create_task(call());await wait_until(lambda:active['A']==1)
        second=await call();assert second.json()['choices'][0]['message']['content']=='B'
        gates['A'].set();await task
        print('PASS: actual in-flight count, full sticky account rescheduled, equal-priority least-loaded account selected, slots released')

        await reset();provider=await row('A');admitted=[];release=asyncio.Event();attempted=[]
        async def contender(index):
            try:
                async with provider_concurrency.acquire(SimpleNamespace(provider=provider)):
                    admitted.append(index);attempted.append(index);await release.wait()
            except APIError as error:
                assert error.detail['code']=='PROVIDER_BUSY';attempted.append(index)
        tasks=[asyncio.create_task(contender(i)) for i in range(24)]
        await wait_until(lambda:len(attempted)==24);assert len(admitted)==1
        release.set();await asyncio.gather(*tasks)
        # Expired process ownership is reclaimed; renewal keeps a live request owned.
        slot=provider_concurrency.key(provider.id);await redis_client.zadd(slot,{'dead-process':time.time()-10})
        with patch('app.gateway.provider_concurrency.TTL',1),patch('app.gateway.provider_concurrency.RENEW_SECONDS',.2):
            async with provider_concurrency.acquire(SimpleNamespace(provider=provider)):
                await asyncio.sleep(1.3);assert (await provider_concurrency.loads([provider]))[provider.id]==1
        assert (await provider_concurrency.loads([provider]))[provider.id]==0
        print('PASS: 24 concurrent Redis admissions respect max=1, expired owner reclaimed, long ownership renewed and released')
        original_eval=redis_client.eval
        async def broken_renew(script,*args):
            if script==provider_concurrency.RENEW:raise RedisError('fixture store outage')
            return await original_eval(script,*args)
        context=SimpleNamespace(provider=provider,provider_lease_lost=False)
        async def lost_owner():
            try:
                async with provider_concurrency.acquire(context):await asyncio.sleep(2)
            except asyncio.CancelledError:return
            raise AssertionError('store outage bypassed ownership')
        with patch.object(redis_client,'eval',broken_renew),patch('app.gateway.provider_concurrency.RENEW_SECONDS',.05):
            await asyncio.wait_for(asyncio.create_task(lost_owner()),1)
        assert context.provider_lease_lost and (await provider_concurrency.loads([provider]))[provider.id]==0
        with patch.object(redis_client,'eval',side_effect=RedisError('fixture store outage')):
            try:
                async with provider_concurrency.acquire(SimpleNamespace(provider=provider)):raise AssertionError('admitted while store unavailable')
            except APIError as error:assert error.detail['code']=='SCHEDULER_UNAVAILABLE'
        print('PASS: Redis admission failure is closed; renewal failure cancels owner and releases slot')

        await reset();await edit('B',status='disabled');await edit('C',status='disabled');modes['A']='fail'
        await call(502);assert (await row('A')).failure_count==1
        await call(502);d=await detail('A');assert d['scheduling_state']=='Cooling' and d['failure_count']==2
        delta=((await row('A')).cooldown_until-now()).total_seconds();assert 27<delta<=30
        before=len(trace);await call(503);assert len(trace)==before
        for count,delay in [(3,60),(4,120),(5,300)]:
            await edit('A',cooldown_until=now()-timedelta(seconds=1));await call(502)
            p=await row('A');assert p.failure_count==count and delay-3<(p.cooldown_until-now()).total_seconds()<=delay
        await edit('A',cooldown_until=now()-timedelta(seconds=1));modes['A']='hold'
        task=asyncio.create_task(call());await wait_until(lambda:active['A']==1);before=len(trace)
        second=asyncio.create_task(call());await asyncio.sleep(.2);assert len(trace)==before
        gates['A'].set();await task;await second;p=await row('A');assert p.failure_count==0 and p.cooldown_until is None and p.health_status=='healthy'
        print('PASS: consecutive failure cooling 30/60/120/300, cooling excluded, expired cooldown single recovery probe, success resets health')
        await reset();await edit('B',status='disabled');await edit('C',status='disabled');modes['A']='rate'
        for count,delay in [(1,30),(2,60),(3,120),(4,300)]:
            if count>1:await edit('A',cooldown_until=now()-timedelta(seconds=1))
            await call(503);p=await row('A')
            assert p.failure_count==count and delay-3<(p.cooldown_until-now()).total_seconds()<=delay
        print('PASS: upstream rate limit cools immediately and backs off 30/60/120/300')

        await reset();await edit('B',status='disabled');await edit('C',status='disabled');modes['A']='auth'
        await call(502);assert (await detail('A'))['scheduling_state']=='Unavailable'
        await reset();modes['A']='bad';await call(400);assert [t[0] for t in trace]==['A'] and (await row('A')).failure_count==0
        await edit('A',status='disabled');assert (await detail('A'))['scheduling_state']=='Disabled'
        print('PASS: hard authentication failure unavailable; client parameter failure neither failovers nor poisons health; Disabled state')
        await reset();await edit('A',failure_count=3,cooldown_until=now()+timedelta(seconds=60))
        result=await client.post('/api/admin/providers/'+str(seed.ids['A'])+'/test',headers=admin)
        assert result.status_code==200 and result.json()['data']['success']
        p=await row('A');assert p.failure_count==0 and p.cooldown_until is None and p.health_status=='healthy'
        print('PASS: explicit successful connection test clears cooling and restores account health')

        await reset();modes['A']='hold_fail';task=asyncio.create_task(call());await wait_until(lambda:active['A']==1)
        p=await row('A');await edit('A',config_version=p.config_version+1);gates['A'].set();await task
        assert (await row('A')).failure_count==0
        print('PASS: stale in-flight failure cannot overwrite edited provider configuration health')

        await reset();modes['A']='fail';response=await call(body={**payload,'stream':True})
        assert [t[0] for t in trace]==['A','B'] and 'data: [DONE]' in response.text
        await reset();modes['A']='stream_error';response=await call(body={**payload,'stream':True})
        assert [t[0] for t in trace]==['A'] and 'event: error' in response.text and 'data: [DONE]' not in response.text
        await wait_until(lambda:(not any(active.values())))
        assert (await row('A')).failure_count==1
        assert all(value==0 for value in (await provider_concurrency.loads([await row(name) for name in modes])).values())
        print('PASS: streaming header failure can failover, emitted stream never retries, terminal failure updates health, no slot/HTTP fixture leaks')
      finally:
        for gate in gates.values():gate.set()
        await wait_until(lambda:not any(active.values()));server.shutdown();server.server_close();await clear_sticky()
        await redis_client.delete(*[provider_concurrency.key(seed.ids[name]) for name in modes])
        async with seed.session_factory.begin() as db:
            await db.execute(delete(seed.User).where(seed.User.id==seed.ids['user']))
            await db.execute(delete(seed.UserGroup).where(seed.UserGroup.id==seed.ids['ug']))
            await db.execute(delete(seed.ModelGroup).where(seed.ModelGroup.id==seed.ids['mg']))
            await db.execute(delete(seed.ProviderModelMapping).where(seed.ProviderModelMapping.provider_id.in_([seed.ids['A'],*extra])))
            await db.execute(delete(seed.Provider).where(seed.Provider.id.in_([seed.ids['A'],*extra])))
            await db.execute(delete(seed.LogicalModel).where(seed.LogicalModel.name.in_([seed.NAME,seed.EMBED,NEXT])))
        await redis_client.aclose();await seed.engine.dispose()

if __name__=='__main__':asyncio.run(main())
