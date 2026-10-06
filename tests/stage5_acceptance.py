"""Real socket/HTTP acceptance with temporary protocol fixtures, no paid generation."""
import asyncio,json,secrets,threading,uuid,time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import httpx
from sqlalchemy import select,delete
from app.core.database import session_factory,engine
from app.core.security import hash_password
from app.models.user import User,Role,Provider,AuditLog
from app.services.provider_crypto import decrypt_secret
PREFIX='stage5_'+uuid.uuid4().hex[:10]
PASSWORD='Stage5-Acceptance-2026!'
SECRET='sk-stage5-'+secrets.token_urlsafe(32)
created=[];providers=[];seen=[]
started=threading.Event();release=threading.Event()


class Fixture(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        path=self.path
        seen.append((path,self.headers.get('Authorization'),self.headers.get('x-api-key'),self.headers.get('anthropic-version')))
        code=200;body={'data':[{'id':'fixture-model'}]}
        if path.startswith('/invalid'):
            code=401;body={'error':{'message':SECRET}}
        elif path.startswith('/redirect'):
            self.send_response(302);self.send_header('Location','http://127.0.0.1:'+str(self.server.server_port)+'/leak/models');self.end_headers();return
        elif path.startswith('/bad'):
            body={'not_models':SECRET}
        elif path.startswith('/huge'):
            body={'data':[],'padding':'a'*1100000}
        elif path.startswith('/slow'):
            started.set();release.wait(8)
        elif path=='/api/tags':
            body={'models':[{'name':'fixture-ollama'}]}
        elif path.startswith('/claude'):
            assert self.headers.get('x-api-key')==SECRET and self.headers.get('anthropic-version')=='2023-06-01'
        elif path.startswith('/compatible') or path.startswith('http://'):
            if self.headers.get('Authorization')!='Bearer '+SECRET:
                code=401;body={'error':'wrong test credentials'}
        else:
            code=404;body={'error':'fixture route absent'}
        encoded=json.dumps(body).encode()
        self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)


def call(c,method,path,status=200,**kwargs):
    r=c.request(method,'/api'+path,**kwargs)
    assert r.status_code==status,f'{method} {path}: {r.status_code} != {status}: {r.text}'
    assert SECRET not in r.text,'upstream key leaked to HTTP client'
    assert 'api_key_encrypted' not in r.text,'ciphertext leaked'
    return r.json()


def login(name):
    c=httpx.Client(base_url='http://127.0.0.1',timeout=30)
    c.headers['Authorization']='Bearer '+call(c,'POST','/auth/login',json={'username':name,'password':PASSWORD})['data']['access_token']
    return c


async def seed():
    async with session_factory.begin() as db:
        for suffix,role in [('_admin','admin'),('_user','user')]:
            role_id=await db.scalar(select(Role.id).where(Role.code==role))
            u=User(username=PREFIX+suffix,role=role,role_id=role_id,status='enabled',must_change_password=False,password_hash=await hash_password(PASSWORD))
            db.add(u);await db.flush();created.append(u.id)


async def main():
    fixture=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
    thread=threading.Thread(target=fixture.serve_forever,daemon=True);thread.start()
    url='http://127.0.0.1:'+str(fixture.server_port)
    await seed()
    try:
        admin,user=login(PREFIX+'_admin'),login(PREFIX+'_user')
        types=call(admin,'GET','/admin/providers/types')['data']
        assert len(types)>=8 and all(t['protocols'] for t in types)
        body={'name':PREFIX+'_compatible','provider_type':'custom_openai','protocol':'openai','base_url':url+'/compatible','api_key':SECRET,'priority':5,'max_concurrency':4,'remark':'中文备注'}
        data=call(admin,'POST','/admin/providers',201,json=body)['data'];pid=data['id'];providers.append(pid)
        assert data['has_api_key'] and data['health_status']=='unknown'
        call(admin,'POST','/admin/providers',409,json=body)
        call(admin,'POST','/admin/providers',422,json={**body,'name':PREFIX+'_bad','protocol':'anthropic'})
        call(admin,'POST','/admin/providers',422,json={**body,'api_key':'secret\nheader'})
        call(admin,'POST','/admin/providers',422,json={**body,'base_url':'https://username:password@example.com/v1'})
        call(admin,'POST','/admin/providers',422,json={**body,'base_url':'https://example.com/v1?key='+SECRET})
        call(admin,'PATCH','/admin/providers/'+str(pid),422,json={'base_url':'file:///etc/passwd'})
        call(admin,'PATCH','/admin/providers/'+str(pid),422,json={'max_concurrency':None})
        call(user,'GET','/admin/providers',403)
        call(user,'GET','/admin/providers/'+str(pid),403)
        call(user,'POST','/admin/providers/'+str(pid)+'/test',403)
        call(user,'PATCH','/admin/providers/'+str(pid),403,json={'status':'disabled'})
        call(user,'DELETE','/admin/providers/'+str(pid),403)
        async with session_factory() as db:
            row=await db.get(Provider,pid);cipher=row.api_key_encrypted
            assert SECRET not in cipher and cipher.startswith('v1:') and decrypt_secret(cipher)==SECRET
        call(admin,'PATCH','/admin/providers/'+str(pid),json={'name':PREFIX+'_renamed'})
        async with session_factory() as db:
            assert (await db.get(Provider,pid)).api_key_encrypted==cipher
        r=call(admin,'POST','/admin/providers/'+str(pid)+'/test')['data']
        assert r['success'] and r['network_connected'] and r['authentication']=='accepted' and r['http_status']==200 and r['model_count']==1 and r['latency_ms']>=0
        assert call(admin,'GET','/admin/providers/'+str(pid))['data']['health_status']=='healthy'
        assert call(admin,'GET','/admin/providers',params={'q':PREFIX,'provider_type':'custom_openai','protocol':'openai','health_status':'healthy'})['data']['total']==1
        assert call(admin,'GET','/admin/providers',params={'q':PREFIX,'protocol':'anthropic'})['data']['total']==0
        call(admin,'PATCH','/admin/providers/'+str(pid),json={'api_key':SECRET})
        async with session_factory() as db:
            assert (await db.get(Provider,pid)).api_key_encrypted!=cipher
        print('PASS: provider CRUD, eight types, validation, admin/user boundary, AES-256-GCM ciphertext and no secret echo',flush=True)
        for path,code,status in [('invalid','UPSTREAM_AUTH_FAILED',401),('redirect','UPSTREAM_HTTP_ERROR',302),('bad','UPSTREAM_INVALID_RESPONSE',200),('huge','UPSTREAM_RESPONSE_TOO_LARGE',200)]:
            call(admin,'PATCH','/admin/providers/'+str(pid),json={'base_url':url+'/'+path})
            r=call(admin,'POST','/admin/providers/'+str(pid)+'/test')['data']
            assert not r['success'] and r['network_connected'] and r['error_code']==code and r['http_status']==status
        assert not any(p.startswith('/leak') for p,*_ in seen)
        call(admin,'POST','/admin/providers/'+str(pid)+'/test')
        assert call(admin,'GET','/admin/providers/'+str(pid))['data']['failure_count']==2
        call(admin,'PATCH','/admin/providers/'+str(pid),json={'base_url':'http://127.0.0.1:1'})
        r=call(admin,'POST','/admin/providers/'+str(pid)+'/test')['data']
        assert not r['success'] and r['error_code']=='UPSTREAM_NETWORK_ERROR' and r['http_status'] is None
        call(admin,'PATCH','/admin/providers/'+str(pid),json={'base_url':url+'/compatible','status':'disabled'})
        before=len(seen);call(admin,'POST','/admin/providers/'+str(pid)+'/test',409);assert len(seen)==before
        call(admin,'PATCH','/admin/providers/'+str(pid),json={'status':'enabled','base_url':url+'/slow'})
        def pending():
            c=httpx.Client(base_url='http://127.0.0.1',timeout=20,headers=dict(admin.headers))
            return c.post('/api/admin/providers/'+str(pid)+'/test')
        with ThreadPoolExecutor(max_workers=1) as pool:
            f=pool.submit(pending);assert started.wait(5)
            call(admin,'PATCH','/admin/providers/'+str(pid),json={'status':'disabled'});release.set()
            assert f.result().status_code==409
        assert call(admin,'GET','/admin/providers/'+str(pid))['data']['health_status']=='unknown'
        print('PASS: auth/HTTP/network/schema/size failures, no credential redirect, disable blocks network, stale test cannot overwrite new config',flush=True)
        for kind,protocol,base in [('anthropic','anthropic',url+'/claude'),('ollama','ollama',url)]:
            p=call(admin,'POST','/admin/providers',201,json={'name':PREFIX+'_'+kind,'provider_type':kind,'protocol':protocol,'base_url':base,'api_key':SECRET if kind=='anthropic' else None})['data'];providers.append(p['id'])
            r=call(admin,'POST','/admin/providers/'+str(p['id'])+'/test')['data'];assert r['success'] and r['model_count']==1
        call(admin,'PATCH','/admin/providers/'+str(pid),json={'status':'enabled','base_url':'http://upstream.test.invalid/v1','proxy':url})
        assert call(admin,'POST','/admin/providers/'+str(pid)+'/test')['data']['success']
        call(admin,'PATCH','/admin/providers/'+str(pid),json={'clear_api_key':True,'proxy':None,'base_url':url+'/compatible'})
        assert not call(admin,'GET','/admin/providers/'+str(pid))['data']['has_api_key']
        call(admin,'PATCH','/admin/providers/'+str(pid),422,json={'provider_type':'openai'})
        async with session_factory() as db:
            logs=(await db.scalars(select(AuditLog).where(AuditLog.actor_id.in_(created)))).all()
            assert logs and all(SECRET not in str(log.__dict__) for log in logs)
        call(admin,'DELETE','/admin/providers/'+str(pid))
        call(admin,'GET','/admin/providers/'+str(pid),404);call(admin,'POST','/admin/providers/'+str(pid)+'/test',404)
        async with session_factory() as db:
            row=await db.get(Provider,pid);assert row.status=='deleted' and row.deleted_at
        print('PASS: native Anthropic/Ollama protocol requests, actual HTTP proxy, secret replacement/clear, audit and soft deletion',flush=True)
        print('PASS: all stage5 backend acceptance checks (isolated HTTP protocol fixtures; no live paid model credentials)',flush=True)
    finally:
        release.set();fixture.shutdown();fixture.server_close()
        async with session_factory.begin() as db:
            await db.execute(delete(Provider).where(Provider.id.in_(providers)))
            await db.execute(delete(User).where(User.id.in_(created)))
        await engine.dispose()

asyncio.run(main())

