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

PASSWORD='Stage17!Isolated84925';KEY='sk-hd-'+secrets.token_urlsafe(32);calls=[];mode='normal'


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
        from app.models.compliance import ComplianceLog,AuditSample,AuditVector
        from sqlalchemy import text
        gateway={'Authorization':'Bearer '+KEY}
        for endpoint in ('words','samples','policies','logs'):
            check(await client.get('/api/admin/compliance/'+endpoint),401)
            check(await client.get('/api/admin/compliance/'+endpoint,headers=normal),403)
        def payload(prompt,model='route-simple',stream=False):return {'model':model,'messages':[{'role':'user','content':prompt}],'max_tokens':10,'stream':stream}
        async def post(path,body):return check(await client.post('/api/admin/compliance/'+path,json=body,headers=headers))
        words=[]
        for kind,pattern,prompt in [('text','BADTOKEN','fullwidth ＢＡＤＴＯＫＥＮ here'),('wildcard','danger?','prefix dangerX suffix'),('regex','risk-[0-9]+','RISK-42')]:
            w=await post('words',{'kind':kind,'pattern':pattern,'risk':'high'});words.append(w)
            p=await post('policies',{'name':'fixture-'+kind,'action':'block','status':'enabled','word_ids':[w['id']]})
            count=len(calls);r=await client.post('/v1/chat/completions',headers=gateway,json=payload(prompt));check(r,403);assert r.json()['error']['code']=='CONTENT_BLOCKED' and len(calls)==count
            rid=r.headers['X-Request-ID']
            log=check(await client.get('/api/admin/compliance/logs',params={'request_id':rid},headers=headers))['items'][0]
            assert log['action']=='block' and log['matches'][0]['evidence'][0]['id']==w['id']
            async with session_factory() as db:
                call=await db.scalar(select(CallLog).where(CallLog.request_id==rid));assert call.provider_id is None and call.total_tokens is None and call.trace['attempts']==[]
            check(await client.delete('/api/admin/compliance/words/'+str(w['id']),headers=headers),409)
            check(await client.delete('/api/admin/compliance/policies/'+str(p['id']),headers=headers))
        check(await client.post('/api/admin/compliance/words',json={'kind':'regex','pattern':'['},headers=headers),400)
        allblock=await post('policies',{'name':'fixture-all-protocol-block','action':'block','status':'enabled','word_ids':[words[0]['id']]})
        for endpoint,body in [('responses',{'model':'route-simple','input':'BADTOKEN'}),('messages',{'model':'route-simple','system':'BADTOKEN','messages':[{'role':'user','content':'hello'}],'max_tokens':10}),('embeddings',{'model':'route-embedding','input':'BADTOKEN'})]:
            count=len(calls);response=await client.post('/v1/'+endpoint,headers=gateway,json=body);check(response,403);assert len(calls)==count and response.json()['error']['code']=='CONTENT_BLOCKED'
        count=len(calls)
        check(await client.post('/v1/messages',headers=gateway,json={'model':'route-simple','max_tokens':10,'messages':[{'role':'assistant','content':[{'type':'tool_use','id':'fixture-tool','name':'fixture','input':{'arbitrary_argument':'BADTOKEN'}}]}]}),403)
        assert len(calls)==count
        check(await client.post('/v1/chat/completions',headers=gateway,json={'model':'route-simple','messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':'https://example.com/fixture.png'}}]}]}),400)
        check(await client.post('/v1/responses',headers=gateway,json={'model':'route-simple','previous_response_id':'fixture-prior'}),400)
        check(await client.delete('/api/admin/compliance/policies/'+str(allblock['id']),headers=headers))
        print('PASS1: role gates; NFKC text/wildcard/regex Block; zero upstream/Provider slot/usage; immutable Request ID evidence; invalid regex rejected')
        audit=await post('policies',{'name':'fixture-audit','action':'audit','status':'enabled','word_ids':[words[0]['id']],'models':['route-simple'],'group_ids':[group_id]})
        count=len(calls);r=await client.post('/v1/chat/completions',headers=gateway,json=payload('BADTOKEN'));check(r);assert len(calls)==count+1
        rid=r.headers['X-Request-ID']
        async with session_factory() as db:
            call=await db.scalar(select(CallLog).where(CallLog.request_id==rid));assert call.total_tokens==6 and call.trace['compliance']['action']=='audit'
        r=await client.post('/v1/chat/completions',headers=gateway,json=payload('BADTOKEN','route-complex'));check(r)
        async with session_factory() as db:
            assert await db.scalar(select(ComplianceLog).where(ComplianceLog.request_id==r.headers['X-Request-ID'])) is None
        print('PASS2: Audit continues real HTTP generation and actual6 Token settlement; model/group scoped rules; logs contain IDs/risk snapshots without text')
        # Hold the isolated audit table lock until the real API's write deadline expires.
        async with session_factory.begin() as unavailable:
            await unavailable.execute(text('LOCK TABLE compliance_logs IN ACCESS EXCLUSIVE MODE'))
            count=len(calls);r=await client.post('/v1/chat/completions',headers=gateway,json=payload('BADTOKEN'));check(r);assert len(calls)==count+1
            pending_id=r.headers['X-Request-ID'];path=Path('/data/logs/compliance-outbox')/(pending_id+'.json');assert path.exists() and (path.stat().st_mode&0o777)==0o600
            contents=path.read_text();assert 'BADTOKEN' not in contents and KEY not in contents
        for _ in range(100):
            async with session_factory() as db:stored=await db.scalar(select(ComplianceLog).where(ComplianceLog.request_id==pending_id))
            if stored and not path.exists():break
            await asyncio.sleep(.1)
        else:raise AssertionError('audit replay failed')
        print('PASS3: actual audit DB outage does not block generation; protected body-free outbox replays once after recovery')
        sample=await post('samples',{'text':'明天上午去图书馆借一本关于天文学的书','risk':'medium'})
        ready=None
        for _ in range(200):
            listing=check(await client.get('/api/admin/compliance/samples',headers=headers))['items'];ready=next(x for x in listing if x['id']==sample['id'])
            if ready['vector_status']=='ready':break
            await asyncio.sleep(.1)
        assert ready['vector_status']=='ready',ready
        sem=await post('policies',{'name':'fixture-semantic','action':'block','status':'enabled','sample_ids':[sample['id']],'threshold':.90})
        count=len(calls);r=await client.post('/v1/chat/completions',headers=gateway,json=payload(sample['text']));check(r,403);assert len(calls)==count
        evidence=check(await client.get('/api/admin/compliance/logs',params={'request_id':r.headers['X-Request-ID']},headers=headers))['items'][0]
        h=evidence['matches'][0]['evidence'][0];assert h['source']=='sample' and h['similarity']>.99
        async with session_factory() as db:
            dims=await db.scalar(text('SELECT vector_dims(embedding) FROM review_vectors WHERE sample_id=:id'),{'id':sample['id']});assert dims==384
        print('PASS4: pinned real local ONNX multilingual Embedding ->384 dimensions -> actual pgvector cosine -> semantic Block with zero Provider requests')
        # Virtual model blocking must happen before its metered Embedding child.
        cfgbody=dict(virtual_model='AI-Auto',embedding_model='route-embedding',simple_model_group=target_ids[0],complex_model_group=target_ids[1],top_k=5,similarity_threshold=.75,confidence_gap=.1,fallback='simple',status='enabled')
        check(await client.post('/api/admin/smart-route/configs',json=cfgbody,headers=headers),201)
        async with session_factory.begin() as db:db.add(ModelGroupModel(model_group_id=target_ids[2],logical_model='AI-Auto',position=1))
        count=len(calls);check(await client.post('/v1/chat/completions',headers=gateway,json=payload(sample['text'],'AI-Auto')),403);assert len(calls)==count
        check(await client.get('/api/admin/compliance/logs',params={'start':'2026-01-01T00:00:00Z','end':'2026-03-01T00:00:00Z'},headers=headers),400)
        async with session_factory.begin() as db:
            from app.core.security import now
            from datetime import timedelta
            source=await db.get(AuditSample,sample['id']);previous=source.revision;source.vector_status='processing';source.job_started_at=now()-timedelta(seconds=61)
        for _ in range(100):
            listing=check(await client.get('/api/admin/compliance/samples',headers=headers))['items'];ready=next(x for x in listing if x['id']==sample['id'])
            if ready['vector_status']=='ready' and ready['revision']>previous:break
            await asyncio.sleep(.1)
        assert ready['revision']>previous and ready['vector_status']=='ready'
        print('PASS5: Block precedes AI-Auto Embedding; abandoned semantic jobs recover under version control; bounded time queries')
        # A Block policy must not disappear behind >100 higher-ranked Audit candidates.
        check(await client.put('/api/admin/compliance/policies/'+str(sem['id']),headers=headers,json={'name':'fixture-semantic','action':'block','status':'disabled','sample_ids':[sample['id']],'threshold':.90}))
        async with session_factory.begin() as db:
            import numpy as np
            from app.services.route_vectors import encode_vector
            from app.services.local_embedding import VERSION
            vector=json.loads(await db.scalar(text('SELECT embedding::text FROM review_vectors WHERE sample_id=:id'),{'id':sample['id']}))
            base=np.array(vector);orthogonal=np.zeros(384);orthogonal[0]=1;orthogonal-=np.dot(orthogonal,base)*base;orthogonal/=np.linalg.norm(orthogonal)
            lower,_=encode_vector((.95*base+np.sqrt(1-.95**2)*orthogonal).tolist())
            synthetic=[]
            for i in range(102):
                item=AuditSample(text='synthetic rank fixture '+str(i),text_hash=__import__('hashlib').sha256(('rank fixture '+str(i)).encode()).hexdigest(),risk='medium',vector_status='ready');db.add(item);await db.flush();synthetic.append(item.id)
                await db.execute(text('INSERT INTO review_vectors(sample_id,embedding,model_version,sample_revision) VALUES (:id,CAST(:v AS vector),:m,1)'),{'id':item.id,'v':lower if i==101 else json.dumps(vector),'m':VERSION})
        extra=[]
        for name,ids,action in [('rank-audit-1',synthetic[:100],'audit'),('rank-audit-2',[synthetic[100]],'audit'),('rank-block',[synthetic[101]],'block')]:extra.append(await post('policies',{'name':name,'action':action,'status':'enabled','sample_ids':ids,'threshold':.9}))
        count=len(calls);r=await client.post('/v1/chat/completions',headers=gateway,json=payload(sample['text']));check(r,403);assert len(calls)==count
        decision=check(await client.get('/api/admin/compliance/logs',headers=headers,params={'request_id':r.headers['X-Request-ID']}))['items'][0]
        assert any(m['action']=='block' and any(h['id']==synthetic[101] for h in m['evidence']) for m in decision['matches'])
        for policy in extra:check(await client.delete('/api/admin/compliance/policies/'+str(policy['id']),headers=headers))
        async with session_factory.begin() as db:await db.execute(delete(AuditSample).where(AuditSample.id.in_(synthetic)))
        check(await client.put('/api/admin/compliance/policies/'+str(sem['id']),headers=headers,json={'name':'fixture-semantic','action':'block','status':'enabled','sample_ids':[sample['id']],'threshold':.90}))
        print('PASS7: synthetic ranking regression with102 candidates proves lower-ranked Block evidence cannot be masked by101 Audit samples')
        if os.getenv('STAGE17_UI_HOLD'):
            print('UI_READY',flush=True)
            for _ in range(900):
                if Path('/tmp/stage17-ui-release').exists():break
                await asyncio.sleep(1)
        check(await client.delete('/api/admin/compliance/policies/'+str(sem['id']),headers=headers))
        check(await client.delete('/api/admin/compliance/samples/'+str(sample['id']),headers=headers))
        async with session_factory() as db:
            assert await db.scalar(select(func.count()).select_from(AuditVector))==0
            assert await db.scalar(select(func.count()).select_from(ComplianceLog))>=5
        for slot in ('gateway:concurrency','gateway:streaming','gateway:queue',f'provider:{provider_id}:concurrency'):assert await redis_client.zcard(slot)==0
        print('PASS6: source in-use protection and vector cascade preserve historical evidence; all runtime leases released')
    server.shutdown();server.server_close();await engine.dispose()
if __name__=='__main__':asyncio.run(main())
