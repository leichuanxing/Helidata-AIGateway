"""Run only in an isolated candidate container: real Nginx/API/DB/Redis/HTTPX."""
import asyncio,json,secrets,threading,time,os
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from sqlalchemy import select,func,delete
import httpx
from app.core.database import session_factory,engine
from app.core.security import hash_password,digest
from app.models.user import User,Role,UserGroup,ModelGroup,ModelGroupModel,UserGroupModelGroup,LogicalModel,Provider,ProviderModelMapping,ApiKey
from app.models.routing import RouteSample,RouteVector,RouteDecision
from app.models.call_log import CallLog
from app.models.quota import QuotaBucket
from app.services.provider_crypto import encrypt_secret
from app.core.redis import redis_client

PASSWORD='Stage16!Isolated84925';KEY='sk-hd-'+secrets.token_urlsafe(32);calls=[];mode='normal'


class Fixture(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append((self.path,body['model']))
        if self.path.endswith('/embeddings'):
            if mode=='slow':time.sleep(2)
            if mode=='fail':self.answer({'error':'fixture rejected'},400);return
            value=body['input'];vector=[1,1] if 'ambiguous' in value else [0,1] if 'complex' in value else [1,0]
            if mode=='zero':vector=[0,0]
            result={'object':'list','model':body['model'],'data':[{'object':'embedding','index':0,'embedding':vector}], 'usage':{'prompt_tokens':4,'total_tokens':4}}
        else:
            assert body['model'] in ('real-simple','real-complex')
            if body.get('stream'):
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                chunk={'id':'fixture-stream','object':'chat.completion.chunk','created':1791110000,'model':body['model']}
                for content in ({'choices':[{'index':0,'delta':{'content':'fixture'},'finish_reason':None}]},
                                {'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}, {'choices':[],'usage':{'prompt_tokens':4,'completion_tokens':2,'total_tokens':6}}):
                    self.wfile.write(('data: '+json.dumps({**chunk,**content})+'\n\n').encode());self.wfile.flush()
                self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush();return
            result={'id':'fixture-chat','object':'chat.completion','created':1791110000,'model':body['model'],
                    'choices':[{'index':0,'message':{'role':'assistant','content':body['model']},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':4,'completion_tokens':2,'total_tokens':6}}
        self.answer(result)
    def answer(self,result,status=200):
        raw=json.dumps(result).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers()
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):pass


async def main():
    global mode
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=server.serve_forever,daemon=True).start()
    async with session_factory.begin() as db:
        roles={code:ident for ident,code in (await db.execute(select(Role.id,Role.code))).all()}
        group=UserGroup(name='isolated-route-users',max_concurrency=1,key_max_concurrency=1,quota_limit=1000000)
        db.add(group);await db.flush()
        admin=User(username='isolated-route-admin',role='admin',role_id=roles['admin'],password_hash=await hash_password(PASSWORD),must_change_password=False)
        user=User(username='isolated-route-user',role='user',role_id=roles['user'],user_group_id=group.id,password_hash=await hash_password(PASSWORD),must_change_password=False)
        db.add_all([admin,user]);await db.flush()
        db.add(ApiKey(user_id=user.id,name='route-key',key_hash=digest(KEY),prefix=KEY[:12],suffix=KEY[-4:]))
        provider=Provider(name='isolated-route-provider',provider_type='custom_openai',protocol='openai',base_url=f'http://127.0.0.1:{server.server_port}/v1',api_key_encrypted=encrypt_secret('fixture-key'),max_concurrency=1)
        db.add(provider);await db.flush()
        db.add_all([LogicalModel(name=name,model_type=kind) for name,kind in [('route-simple','text'),('route-complex','reasoning'),('route-embedding','embedding')]])
        await db.flush()
        db.add_all([ProviderModelMapping(provider_id=provider.id,logical_model=name,model_type=kind,upstream_model=real) for name,kind,real in
                    [('route-simple','text','real-simple'),('route-complex','reasoning','real-complex'),('route-embedding','embedding','real-embedding')]])
        targets=[ModelGroup(name=name) for name in ('route-simple-group','route-complex-group','route-access-group')]
        db.add_all(targets);await db.flush()
        for target,name in zip(targets,('route-simple','route-complex','route-embedding')):
            db.add(ModelGroupModel(model_group_id=target.id,logical_model=name,position=0))
            db.add(UserGroupModelGroup(user_group_id=group.id,model_group_id=target.id))
        group_id=group.id;target_ids=[g.id for g in targets];provider_id=provider.id
    async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=30) as client:
        def check(r,status=200):
            assert r.status_code==status,(r.status_code,r.text[:500]);return r.json().get('data')
        headers={'Authorization':'Bearer '+check(await client.post('/api/auth/login',json={'username':admin.username,'password':PASSWORD}))['access_token']}
        normal={'Authorization':'Bearer '+check(await client.post('/api/auth/login',json={'username':user.username,'password':PASSWORD}))['access_token']}
        for endpoint in ('configs','samples?config_id=1','logs','statistics'):
            check(await client.get('/api/admin/smart-route/'+endpoint),401)
            check(await client.get('/api/admin/smart-route/'+endpoint,headers=normal),403)
        body=dict(virtual_model='AI-Auto',embedding_model='route-embedding',simple_model_group=target_ids[0],complex_model_group=target_ids[1],top_k=5,similarity_threshold=.75,confidence_gap=.1,fallback='error',status='enabled')
        check(await client.post('/api/admin/smart-route/configs',json={**body,'virtual_model':'route-simple'},headers=headers),409)
        cfg=check(await client.post('/api/admin/smart-route/configs',json=body,headers=headers),201);ident=cfg['id']
        check(await client.post(f'/api/admin/providers/{provider_id}/model-mappings',json={'logical_model':'AI-Auto','upstream_model':'bad','model_type':'text'},headers=headers),409)
        async with session_factory.begin() as db:db.add(ModelGroupModel(model_group_id=target_ids[2],logical_model='AI-Auto',position=1))
        sample_ids=check(await client.post('/api/admin/smart-route/samples',json={'config_id':ident,'samples':[{'prompt':'simple task','classification':'simple'},{'prompt':'complex task','classification':'complex'}]},headers=headers),201)['ids']
        check(await client.post('/api/admin/smart-route/samples/import',json={'config_id':ident,'content':'prompt,classification\nsimple task,simple\nother task,complex'},headers=headers),409)
        for _ in range(100):
            rows=check(await client.get('/api/admin/smart-route/samples',params={'config_id':ident},headers=headers))['items']
            if all(row['vector_status']=='ready' for row in rows):break
            await asyncio.sleep(.1)
        assert len(rows)==2 and all(row['vector_status']=='ready' for row in rows),rows
        print('PASS1: authenticated CRUD/name collision; atomic duplicate CSV rejection; real worker Embedding vectorization')
        gateway={'Authorization':'Bearer '+KEY};rids=[]
        for prompt,expected in [('simple task','real-simple'),('complex task','real-complex')]:
            r=await client.post('/v1/chat/completions',headers=gateway,json={'model':'AI-Auto','messages':[{'role':'user','content':prompt}],'max_tokens':10})
            check(r);assert r.json()['model']=='AI-Auto' and r.json()['choices'][0]['message']['content']==expected,r.text
            rid=r.headers['X-Request-ID'];rids.append(rid)
            decision=check(await client.get('/api/admin/smart-route/logs',params={'request_id':rid},headers=headers))['items'][0]
            assert decision['status']=='classified' and len(decision['evidence'])==2
            async with session_factory() as db:
                child=await db.scalar(select(CallLog).where(CallLog.request_id==decision['embedding_request_id']))
                parent=await db.scalar(select(CallLog).where(CallLog.request_id==rid))
                assert child.total_tokens==4 and child.trace['parent_request_id']==rid
                assert parent.request_model=='AI-Auto' and parent.total_tokens==6
                assert 'simple task' not in json.dumps(parent.trace) and 'complex task' not in json.dumps(decision)
        models=(await client.get('/v1/models',headers=gateway)).json()['data'];assert any(row['id']=='AI-Auto' for row in models)
        async with session_factory() as db:
            bucket=await db.scalar(select(QuotaBucket).where(QuotaBucket.group_id==group_id));assert bucket.reported_tokens==20 and bucket.reserved_budget==0
        stats=check(await client.get('/api/admin/smart-route/statistics',headers=headers));assert sum(row['requests'] for row in stats['items'])==2 and sum(row['total_tokens'] for row in stats['items'])==12
        print('PASS2: AI-Auto selects both real groups; Request ID joins; virtual directory; actual quota20 / parent statistics12; capacity1 without nested deadlock')
        count=len(calls)
        r=await client.post('/api/gateway/preflight',headers=gateway,json={'model':'AI-Auto'});check(r);assert len(calls)==count
        r=await client.post('/v1/chat/completions',headers=gateway,json={'model':'AI-Auto','messages':[{'role':'user','content':'simple task'}],'stream':True,'max_tokens':10})
        assert r.status_code==200 and '[DONE]' in r.text,r.text
        assert all(json.loads(line[6:]).get('model')=='AI-Auto' for line in r.text.splitlines() if line.startswith('data: {'))
        print('PASS3: preflight makes no upstream call; routed SSE retains virtual model and terminal usage')
        async with session_factory.begin() as db:await db.execute(delete(UserGroupModelGroup).where(UserGroupModelGroup.user_group_id==group_id,UserGroupModelGroup.model_group_id==target_ids[1]))
        count=len(calls);check(await client.post('/v1/chat/completions',headers=gateway,json={'model':'AI-Auto','messages':[{'role':'user','content':'simple task'}]}),403);assert len(calls)==count
        async with session_factory.begin() as db:db.add(UserGroupModelGroup(user_group_id=group_id,model_group_id=target_ids[1]))
        check(await client.put('/api/admin/smart-route/configs/'+str(ident),json={**body,'fallback':'complex'},headers=headers))
        mode='fail'
        r=await client.post('/v1/chat/completions',headers=gateway,json={'model':'AI-Auto','messages':[{'role':'user','content':'simple task'}],'max_tokens':10});check(r)
        assert r.json()['choices'][0]['message']['content']=='real-complex'
        decision=check(await client.get('/api/admin/smart-route/logs',params={'request_id':r.headers['X-Request-ID']},headers=headers))['items'][0]
        assert decision['status']=='fallback' and decision['reason']=='UPSTREAM_REQUEST_REJECTED'
        mode='normal'
        print('PASS4: revoked target permission prevents all upstream calls; explicit failed-Embedding fallback recorded')
        mode='zero';check(await client.post('/api/admin/smart-route/samples/'+str(sample_ids[0])+'/vectorize',headers=headers))
        for _ in range(100):
            rows=check(await client.get('/api/admin/smart-route/samples',params={'config_id':ident},headers=headers))['items']
            bad=next(row for row in rows if row['id']==sample_ids[0])
            if bad['vector_status']=='failed':break
            await asyncio.sleep(.1)
        assert bad['vector_status']=='failed' and bad['vector_error']=='ROUTE_INVALID_VECTOR'
        mode='normal';check(await client.post('/api/admin/smart-route/samples/'+str(sample_ids[0])+'/vectorize',headers=headers))
        for _ in range(100):
            rows=check(await client.get('/api/admin/smart-route/samples',params={'config_id':ident},headers=headers))['items']
            if next(row for row in rows if row['id']==sample_ids[0])['vector_status']=='ready':break
            await asyncio.sleep(.1)
        else:raise AssertionError('retry failed')
        # Configuration change during the paid child call must not silently fall back.
        mode='slow';count=len(calls)
        pending=asyncio.create_task(client.post('/v1/chat/completions',headers=gateway,json={'model':'AI-Auto','messages':[{'role':'user','content':'simple task'}],'max_tokens':10}))
        for _ in range(100):
            if len(calls)>count:break
            await asyncio.sleep(.01)
        check(await client.put('/api/admin/smart-route/configs/'+str(ident),json={**body,'fallback':'complex','status':'disabled'},headers=headers))
        check(await pending,409);assert all(path.endswith('/embeddings') for path,_ in calls[count:])
        mode='normal';check(await client.put('/api/admin/smart-route/configs/'+str(ident),json={**body,'fallback':'complex'},headers=headers))
        # Cancellation must release both the child admission and parent request.
        mode='slow';count=len(calls)
        pending=asyncio.create_task(client.post('/v1/chat/completions',headers=gateway,json={'model':'AI-Auto','messages':[{'role':'user','content':'simple task'}],'max_tokens':10}))
        for _ in range(100):
            if len(calls)>count:break
            await asyncio.sleep(.01)
        pending.cancel()
        try:await pending
        except asyncio.CancelledError:pass
        for _ in range(100):
            if await redis_client.zcard('gateway:concurrency')==0:break
            await asyncio.sleep(.05)
        assert await redis_client.zcard('gateway:concurrency')==0
        mode='normal'
        async with session_factory.begin() as db:
            group=await db.get(UserGroup,group_id);bucket=await db.scalar(select(QuotaBucket).where(QuotaBucket.group_id==group_id));group.quota_limit=bucket.reported_tokens+1
        count=len(calls)
        check(await client.post('/v1/chat/completions',headers=gateway,json={'model':'AI-Auto','messages':[{'role':'user','content':'simple task'}],'max_tokens':10}),429)
        assert len(calls)==count
        async with session_factory.begin() as db:
            group=await db.get(UserGroup,group_id);group.quota_limit=1000000
        print('PASS6: config changed during Embedding rejects409; child/parent cancel release; exhausted reservation cannot bypass quota through fallback')
        # Simulate persisted state left by a crashed vectorization worker.
        async with session_factory.begin() as db:
            from app.core.security import now
            from datetime import timedelta
            row=await db.get(RouteSample,sample_ids[0]);row.vector_status='processing';row.job_started_at=now()-timedelta(seconds=181);row.vector_request_id='req_crashed_worker'
            previous=row.revision
        for _ in range(100):
            rows=check(await client.get('/api/admin/smart-route/samples',params={'config_id':ident},headers=headers))['items']
            row=next(row for row in rows if row['id']==sample_ids[0])
            if row['vector_status']=='ready' and row['revision']>previous:break
            await asyncio.sleep(.1)
        else:raise AssertionError('durable recovery failed')
        print('PASS7: abandoned processing job recovered with increased revision and real re-vectorization')
        if os.getenv('STAGE16_UI_HOLD'):
            print('UI_READY: isolated-route-admin / fixed test password from script; candidate fixture remains active',flush=True)
            for _ in range(900):
                if Path('/tmp/stage16-ui-release').exists():break
                await asyncio.sleep(1)
        check(await client.delete('/api/admin/smart-route/configs/'+str(ident),headers=headers),409)
        async with session_factory.begin() as db:await db.execute(delete(ModelGroupModel).where(ModelGroupModel.logical_model=='AI-Auto'))
        check(await client.delete('/api/admin/smart-route/configs/'+str(ident),headers=headers))
        async with session_factory() as db:
            assert await db.scalar(select(func.count()).select_from(RouteVector))==0
            assert await db.scalar(select(func.count()).select_from(RouteDecision))>=5
        for slot in ('gateway:concurrency','gateway:streaming','gateway:queue',f'provider:{provider_id}:concurrency'):
            assert await redis_client.zcard(slot)==0,(slot,await redis_client.zcard(slot))
        print('PASS5: invalid vector failed/retry/ready; in-use delete blocked; cascade/history and all runtime leases released')
    server.shutdown();server.server_close();await engine.dispose()


if __name__=='__main__':asyncio.run(main())
