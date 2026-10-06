"""Real HTTP terminal-log acceptance, including failure/cancel/outbox/history/access control."""
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import secrets
import select as socket_select
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
import uuid
import httpx
from sqlalchemy import delete,func,select,text
import stage12_nonstream_regression as seed
from app.core.security import hash_password,now
from app.models.call_log import CallLog
from app.gateway.context import GatewayContext
from app.gateway import call_log

calls=[];active=set();seen=set();extra=[]
PROMPT='private-request-body-'+uuid.uuid4().hex

class Fixture(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        assert self.headers['Authorization']=='Bearer '+seed.SECRET
        rid=self.headers['X-Request-ID'];mode=self.path.split('/')[1]
        calls.append((rid,mode));active.add(rid)
        try:
            if mode in ('fail','bad'):
                status=500 if mode=='fail' else 400
                raw=json.dumps({'error':seed.SECRET+' '+seed.KEY+' '+PROMPT}).encode()
                self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
            if body.get('stream'):
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                chunk={'id':'fixture','object':'chat.completion.chunk','created':1791110000,'model':'private-upstream-model',
                    'choices':[{'index':0,'delta':{'content':'private-response-body'},'finish_reason':None}]}
                role={**chunk,'choices':[{'index':0,'delta':{'role':'assistant'},'finish_reason':None}]}
                self.wfile.write((': keepalive\n\ndata: '+json.dumps(role)+'\n\n').encode());self.wfile.flush();time.sleep(.06)
                self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode());self.wfile.flush()
                if mode=='cancel':
                    ready,_,_=socket_select.select([self.connection],[],[],5)
                    assert ready and self.connection.recv(1)==b'';return
                if mode=='sse-error':self.wfile.write(b'event: error\ndata: [DONE]\n\n');return
                time.sleep(.08)
                usage={**chunk,'choices':[],'usage':{'prompt_tokens':4,'completion_tokens':2,'total_tokens':6,'prompt_tokens_details':{'cached_tokens':1}}}
                invalid_usage={**usage,'usage':{'total_tokens':'invalid','prompt_tokens':-1}}
                self.wfile.write(('data: '+json.dumps(usage)+'\n\ndata: '+json.dumps(invalid_usage)+'\n\ndata: [DONE]\n\n').encode());return
            raw=json.dumps({'id':'fixture','object':'chat.completion','created':1791110000,'model':'private-upstream-model',
                'choices':[{'index':0,'message':{'role':'assistant','content':'private-response-body'},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':4,'completion_tokens':2,'total_tokens':6,'prompt_tokens_details':{'cached_tokens':1}}}).encode()
            if mode=='slow':time.sleep(.12)
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):pass
        finally:active.discard(rid)

async def wait_record(client,admin,rid):
    for _ in range(80):
        r=await client.get('/api/admin/call-logs/'+rid,headers=admin)
        if r.status_code==200:
            data=r.json()['data'];raw=json.dumps(data)
            assert seed.KEY not in raw and seed.SECRET not in raw and PROMPT not in raw and 'private-response-body' not in raw
            return data
        assert r.status_code==404,(r.status_code,r.text[:150])
        await asyncio.sleep(.05)
    raise AssertionError('terminal record missing '+rid)

async def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);server.daemon_threads=True
    seed.URL='http://127.0.0.1:'+str(server.server_port);threading.Thread(target=server.serve_forever,daemon=True).start()
    await seed.seed();password=secrets.token_urlsafe(24)+'aA1!'
    async with seed.session_factory.begin() as db:
        role=await db.scalar(select(seed.Role.id).where(seed.Role.code=='admin'));user=await db.get(seed.User,seed.ids['user']);user.role='admin';user.role_id=role;user.password_hash=await hash_password(password)
        first=await db.get(seed.Provider,seed.ids['provider']);first.priority=10
        second=seed.Provider(name=seed.PREFIX+'-second',provider_type='custom_openai',protocol='openai',base_url=seed.URL+'/normal/v1',api_key_encrypted=seed.encrypt_secret(seed.SECRET),priority=1)
        db.add(second);await db.flush();seed.ids['second']=second.id
        db.add(seed.ProviderModelMapping(provider_id=second.id,logical_model=seed.NAME,upstream_model='private-upstream-model',model_type='text'))
    async def capture(r):
        rid=r.headers.get('X-Request-ID')
        if rid:seen.add(rid)
    async with httpx.AsyncClient(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+seed.KEY},timeout=20,event_hooks={'response':[capture]}) as client:
      try:
        login=await client.post('/api/auth/login',json={'username':seed.PREFIX,'password':password});assert login.status_code==200
        admin={'Authorization':'Bearer '+login.json()['data']['access_token']}
        body={'model':seed.NAME,'messages':[{'role':'user','content':PROMPT}]}
        response=await client.post('/v1/chat/completions',json=body,headers={'X-Request-ID':'untrusted-customer-id'})
        assert response.status_code==200;rid=response.headers['X-Request-ID'];assert rid!='untrusted-customer-id'
        normal=await wait_record(client,admin,rid)
        assert normal['status']=='success' and normal['http_status']==200 and normal['user_id']==seed.ids['user']
        assert normal['api_key_id']==seed.ids['key'] and normal['user_group_id']==seed.ids['ug'] and normal['client_ip']
        assert normal['request_model']==seed.NAME and normal['upstream_model']=='private-upstream-model'
        assert [normal[x] for x in ('input_tokens','output_tokens','cached_tokens','total_tokens')]==[4,2,1,6]
        assert normal['gateway_latency_ms']>0 and normal['upstream_latency_ms']>0 and normal['ttft_ms'] is None and normal['tokens_per_second']>0 and normal['trace']['timing_mode']=='nonstream_full_response'
        assert normal['trace']['model_groups'][0]['id']==seed.ids['mg'] and normal['trace']['smart_routing']=='not_applicable'
        assert normal['trace']['attempts'][0]['status']=='success' and calls[-1][0]==rid
        print('PASS: real HTTP success durable log, server Request ID forwarded, identity/model/Provider snapshots, actual usage and ordered stages; no content/secrets')
        # Make primary fail and remove prior Sticky affinity so a real failover is exercised.
        from app.core.redis import redis_client
        sticky=[k async for k in redis_client.scan_iter(match=f'sticky:{seed.ids["key"]}:*')]
        if sticky:await redis_client.delete(*sticky)
        await seed.change(seed.Provider,'provider',base_url=seed.URL+'/fail/v1')
        response=await client.post('/v1/chat/completions',json=body);assert response.status_code==200
        failover=await wait_record(client,admin,response.headers['X-Request-ID'])
        attempts=failover['trace']['attempts'];assert len(attempts)==2,attempts
        assert attempts[0]['code']=='UPSTREAM_HTTP_ERROR' and attempts[0]['http_status']==500 and attempts[1]['status']=='success'
        assert failover['provider_id']==seed.ids['second'] and len({r for r,m in calls[-2:]})==1
        print('PASS: single durable terminal record reconstructs failed500 primary and successful fallback with snapshots/latencies and common Request ID')
        await seed.change(seed.Provider,'second',status='disabled')
        await seed.change(seed.Provider,'provider',base_url=seed.URL+'/bad/v1')
        response=await client.post('/v1/chat/completions',json=body);assert response.status_code==400
        failed=await wait_record(client,admin,response.headers['X-Request-ID']);assert failed['status']=='failure' and failed['http_status']==400 and failed['error_code']=='UPSTREAM_REQUEST_REJECTED'
        assert failed['trace']['attempts'][0]['http_status']==400
        for payload,headers,status in [({**body,'messages':[]},None,422),(body,{'Authorization':'Bearer invalid'},401)]:
            response=await client.post('/v1/chat/completions',json=payload,headers=headers);assert response.status_code==status
            record=await wait_record(client,admin,response.headers['X-Request-ID']);assert record['http_status']==status and record['status']=='failure'
        print('PASS: parameter rejection, validation before Pipeline and invalid API Key all persisted with sanitized errors')
        response=await client.post('/api/gateway/preflight',json={'model':''});assert response.status_code==422
        invalid_preflight=await wait_record(client,admin,response.headers['X-Request-ID'])
        assert invalid_preflight['operation']=='preflight' and invalid_preflight['logical_model'] is None and invalid_preflight['error_code']=='VALIDATION_ERROR'
        for mode,outcome,code in [('normal','success',None),('sse-error','failure','UPSTREAM_STREAM_ERROR'),('cancel','client_cancelled','CLIENT_DISCONNECTED')]:
            await seed.change(seed.Provider,'provider',base_url=seed.URL+'/'+mode+'/v1')
            async with client.stream('POST','/v1/chat/completions',json={**body,'stream':True}) as response:
                assert response.status_code==200;rid=response.headers['X-Request-ID']
                if mode=='cancel':
                    async for line in response.aiter_lines():
                        if line.startswith('data:'):break
                else:await response.aread()
            record=await wait_record(client,admin,rid)
            assert record['status']==outcome and record['error_code']==code and record['http_status']==200
            assert record['trace']['attempts'][-1]['status']==outcome
            assert record['total_tokens']==(6 if mode=='normal' else None)
            if mode=='normal':
                assert record['ttft_ms']>=55 and record['trace']['generation_time_ms']>=70 and record['tokens_per_second']>0
                assert record['trace']['usage_status']=='available'
            if mode=='cancel':print('CANCEL_REQUEST_ID='+rid)
        print('PASS: real SSE success/error/cancellation terminal records,200 header status retained, no fabricated usage; error[DONE] remains failure')
        # Every filter is applied server-side, exact matching and bounded time range.
        params={'user_id':seed.ids['user'],'user_group_id':seed.ids['ug'],'api_key_id':seed.ids['key'],'provider_id':seed.ids['provider'],
            'model':seed.NAME,'status':'failure','http_status':400,'error_code':'UPSTREAM_REQUEST_REJECTED','operation':'chat',
            'start':(now()-timedelta(hours=1)).isoformat(),'end':(now()+timedelta(hours=1)).isoformat(),'page_size':1}
        filtered=await client.get('/api/admin/call-logs',headers=admin,params=params);assert filtered.status_code==200
        data=filtered.json()['data'];assert data['total']==1 and data['items'][0]['request_id']==failed['request_id']
        params['user_id']=999999999;assert (await client.get('/api/admin/call-logs',headers=admin,params=params)).json()['data']['total']==0
        for values in [{'start':(now()-timedelta(days=32)).isoformat(),'end':now().isoformat()},
            {'start':'2026-10-05T00:00:00','end':'2026-10-05T01:00:00'},{'page':0},{'http_status':999}]:
            assert (await client.get('/api/admin/call-logs',headers=admin,params=values)).status_code==422
        assert (await client.get('/api/admin/call-logs',headers=admin,params={'request_id':normal['request_id']})).json()['data']['total']==1
        assert (await client.get('/api/admin/call-logs',headers=admin,params={'request_id':"' OR 1=1--"})).json()['data']['total']==0
        assert (await client.get('/api/admin/call-logs/req_missing',headers=admin)).status_code==404
        # Admin reads and inference must not exhaust the database pool through nested log transactions.
        await seed.change(seed.Provider,'provider',base_url=seed.URL+'/slow/v1')
        responses=await asyncio.gather(*[client.post('/v1/chat/completions',json=body) for _ in range(10)],
            *[client.get('/api/admin/call-logs',headers=admin,params={'user_id':seed.ids['user']}) for _ in range(16)])
        assert all(r.status_code==200 for r in responses),[r.status_code for r in responses]
        print('PASS: all combination filters/pagination/exact Request ID/invalid ranges and26 concurrent inference/admin queries without pool starvation')
        async with seed.session_factory.begin() as db:
            role=await db.scalar(select(seed.Role.id).where(seed.Role.code=='user'));user=await db.get(seed.User,seed.ids['user']);user.role='user';user.role_id=role
        assert (await client.get('/api/admin/call-logs',headers=admin)).status_code==403
        assert (await client.get('/api/admin/call-logs/'+normal['request_id'],headers=admin)).status_code==403
        assert (await client.get('/api/admin/call-logs',headers={'Authorization':''})).status_code==401
        async with seed.session_factory.begin() as db:
            role=await db.scalar(select(seed.Role.id).where(seed.Role.code=='admin'));user=await db.get(seed.User,seed.ids['user']);user.role='admin';user.role_id=role
        subprocess.run(['supervisorctl','restart','uvicorn'],check=True,stdout=subprocess.DEVNULL)
        for _ in range(80):
            try:
                if (await client.get('/health')).status_code==200:break
            except httpx.HTTPError:pass
            await asyncio.sleep(.1)
        persisted=await wait_record(client,admin,normal['request_id']);assert persisted['id']==normal['id']
        # Historical snapshots must survive renaming and actual deletion, without cascading logs.
        await seed.change(seed.Provider,'provider',name=seed.PREFIX+'-renamed')
        assert (await wait_record(client,admin,normal['request_id']))['provider_name_snapshot']==seed.PREFIX
        async with seed.session_factory.begin() as db:
            await db.execute(delete(seed.ProviderModelMapping).where(seed.ProviderModelMapping.provider_id==seed.ids['provider']))
            await db.execute(delete(seed.Provider).where(seed.Provider.id==seed.ids['provider']))
        assert (await wait_record(client,admin,normal['request_id']))['provider_id']==seed.ids['provider']
        print('PASS: ordinary users403/anonymous401, restart persistence and historical Provider rename/delete without log mutation')
        # Actual PostgreSQL insertion after injected storage failure and disk replay; unique Request ID prevents duplicates.
        with tempfile.TemporaryDirectory(prefix='stage12-outbox-',dir='/data/logs') as folder:
            ctx=GatewayContext('req_'+uuid.uuid4().hex,'chat',seed.NAME);seen.add(ctx.request_id)
            with patch.object(call_log,'OUTBOX',Path(folder)):
                async def unavailable(record):raise RuntimeError(seed.SECRET)
                with patch.object(call_log,'persist',unavailable):await call_log.write(ctx,'failure','INTERNAL_ERROR')
                pending=list(Path(folder).glob('*.json'));assert len(pending)==1 and (pending[0].stat().st_mode&0o777)==0o600
                assert (Path(folder).stat().st_mode&0o777)==0o700
                raw=pending[0].read_text();assert seed.SECRET not in raw and PROMPT not in raw
                await call_log.replay_once();assert not list(Path(folder).glob('*.json'))
                await call_log.persist(call_log.snapshot(ctx,'failure','INTERNAL_ERROR'))
                async with seed.session_factory() as db:
                    assert await db.scalar(select(func.count()).select_from(CallLog).where(CallLog.request_id==ctx.request_id))==1
                await call_log.write(ctx,'failure','INTERNAL_ERROR')
        print('PASS: DB failure produces protected durable outbox, replay inserts actual DB record exactly once without leaking error text')
        await statistics_checks(client,admin,normal,seen)
      finally:
        server.shutdown();server.server_close()
        for _ in range(40):
            if not active:break
            await asyncio.sleep(.05)
        assert not active,active
        async with seed.session_factory.begin() as db:
            await db.execute(delete(seed.User).where(seed.User.id==seed.ids['user']))
            await db.execute(delete(seed.UserGroup).where(seed.UserGroup.id==seed.ids['ug']))
            await db.execute(delete(seed.ModelGroup).where(seed.ModelGroup.id==seed.ids['mg']))
            await db.execute(delete(seed.ProviderModelMapping).where(seed.ProviderModelMapping.provider_id.in_([seed.ids['provider'],seed.ids['second']])))
            await db.execute(delete(seed.Provider).where(seed.Provider.id.in_([seed.ids['provider'],seed.ids['second']])))
            await db.execute(delete(seed.LogicalModel).where(seed.LogicalModel.name.in_([seed.NAME,seed.EMBED])))
            for table in ('usage_hourly','usage_daily'):
                await db.execute(text(f'DELETE FROM {table} WHERE request_model IN (:name,:embed)'),{'name':seed.NAME,'embed':seed.EMBED})
            # Only known test Request IDs and owned identities/models, never arbitrary production rows.
            await db.execute(delete(CallLog).where((CallLog.request_id.in_(seen))|(CallLog.username_snapshot==seed.PREFIX)|(CallLog.request_model.in_([seed.NAME,seed.EMBED]))))
        from app.core.redis import redis_client
        keys=[k async for k in redis_client.scan_iter(match=f'sticky:{seed.ids["key"]}:*')]
        if keys:await redis_client.delete(*keys)
        await redis_client.aclose();await seed.engine.dispose()
        print('PASS: fixture sockets and all owned disposable records cleaned')


async def statistics_checks(client,admin,normal,seen):
    from app.services.usage import COUNTERS,contribution
    from app.gateway.usage import effective
    from app.services import usage as usage_service
    assert not effective({'choices':[{'delta':{'role':'assistant'}}]})
    assert effective({'choices':[{'delta':{'tool_calls':[{'function':{'arguments':'{}'}}]}}]})
    assert not effective({'choices':[],'usage':{'completion_tokens':2}})
    # Seed historical facts across daily/hourly edges through the actual atomic persist path.
    base={k:v for k,v in normal.items() if k!='id'}
    from datetime import datetime,timezone
    for offset in (0,1,3,6):
        record={**base,'request_id':'req_'+uuid.uuid4().hex,'created_at':now()-timedelta(days=offset,hours=2)}
        if offset==3:record['user_id']=seed.ids['user']+10000000
        seen.add(record['request_id'])
        await asyncio.gather(*[call_log.persist(record) for _ in range(6)])
        async with seed.session_factory() as db:
            assert await db.scalar(select(func.count()).select_from(CallLog).where(CallLog.request_id==record['request_id']))==1
    # Force aggregate failure: the terminal record must roll back as well.
    doomed={**base,'request_id':'req_'+uuid.uuid4().hex,'created_at':now()}
    async def fail(*args):raise RuntimeError('aggregate unavailable')
    with patch.object(usage_service,'accumulate',fail):
        try:await call_log.persist(doomed)
        except RuntimeError:pass
        else:raise AssertionError('expected rollback')
    async with seed.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(CallLog).where(CallLog.request_id==doomed['request_id']))==0
    params={'model':seed.NAME,'start':(now()-timedelta(days=7,minutes=13)).isoformat(),'end':(now()+timedelta(minutes=11)).isoformat()}
    for grain in ('day','hour'):
        for overrides in ({},{'user_id':seed.ids['user']},{'user_group_id':seed.ids['ug']},{'api_key_id':seed.ids['key']},{'provider_id':seed.ids['second']},{'protocol':'openai'}):
            q={**params,**overrides,'grain':grain};r=await client.get('/api/admin/usage',headers=admin,params=q)
            assert r.status_code==200,(r.status_code,r.text)
            result=r.json()['data'];summary=result['summary']
            async with seed.session_factory() as db:
                query=select(CallLog).where(CallLog.operation=='chat',CallLog.request_model==seed.NAME,CallLog.created_at>=datetime.fromisoformat(q['start']),CallLog.created_at<datetime.fromisoformat(q['end']))
                for k,v in overrides.items():query=query.where(getattr(CallLog,k)==v)
                records=(await db.scalars(query)).all()
            totals={k:0 for k in COUNTERS}
            for row in records:
                for k,v in contribution({c.name:getattr(row,c.name) for c in CallLog.__table__.columns}).items():totals[k]+=v
            for k in ('requests','success','failure','usage_unavailable'):assert summary[k]==totals[k],(grain,k,summary,totals)
            for k in ('input_tokens','output_tokens','cached_tokens','total_tokens'):
                expected=totals[k+'_sum'] if totals[k+'_count'] or not totals['requests'] else None
                assert summary[k]==expected,(k,summary,totals)
            assert summary['active_users']==len({x.user_id for x in records if x.user_id})
            for prefix,key in [('ttft','average_ttft_ms'),('tps','average_tokens_per_second')]:
                expected=round(totals[prefix+'_sum']/totals[prefix+'_count'],3) if totals[prefix+'_count'] else None
                assert summary[key]==expected,(key,summary[key],expected)
            assert sum(x['requests'] for x in result['series'])==summary['requests']
            assert result['storage'].startswith('daily' if grain=='day' else 'hourly')
    for bad in ({'start':'2026-10-05T00:00:00','end':'2026-10-06T00:00:00'},{'start':(now()-timedelta(days=367)).isoformat(),'end':now().isoformat()},{'provider_id':0}):
        assert (await client.get('/api/admin/usage',headers=admin,params=bad)).status_code==422
    # DB-authoritative role check and forced own-user scope even with malicious extra query fields.
    async with seed.session_factory.begin() as db:
        role=await db.scalar(select(seed.Role.id).where(seed.Role.code=='user'));user=await db.get(seed.User,seed.ids['user']);user.role='user';user.role_id=role
    assert (await client.get('/api/admin/usage',headers=admin)).status_code==403
    own=(await client.get('/api/portal/usage',headers=admin,params={**params,'user_id':seed.ids['user']+10000000,'provider_id':999999})).json()['data']
    assert own['summary']['active_users']==1 and own['summary']['requests']>0
    foreign=(await client.get('/api/portal/usage',headers=admin,params={**params,'api_key_id':999999999})).json()['data']
    assert foreign['summary']['requests']==0 and 'provider_id' not in json.dumps(own)
    assert (await client.get('/api/portal/usage',headers={'Authorization':''})).status_code==401
    async with seed.session_factory.begin() as db:
        role=await db.scalar(select(seed.Role.id).where(seed.Role.code=='admin'));user=await db.get(seed.User,seed.ids['user']);user.role='admin';user.role_id=role
    print('PASS: hourly/daily exact time edges and all dimensions match actual call_logs, weighted means, distinct users, race-idempotency and transactional rollback; own-user isolation enforced')

if __name__=='__main__':asyncio.run(main())
