"""Stage6 uses PostgreSQL and real HTTP protocol fixtures; no paid model inference."""
import asyncio,json,secrets,threading,uuid
from urllib.parse import urlsplit,parse_qs
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from concurrent.futures import ThreadPoolExecutor
import httpx
from sqlalchemy import select,delete
from app.core.database import session_factory,engine
from app.core.security import hash_password
from app.core.exceptions import APIError
from app.models.user import User,Role,Provider,ProviderModelMapping,LogicalModel,ModelGroup,ModelGroupModel,UserGroup
from app.services.model_catalog import authorized_candidates
PREFIX='stage6_'+uuid.uuid4().hex[:10]
PASSWORD='Stage6-Acceptance-2026!';SECRET='sk-upstream-'+secrets.token_urlsafe(32)
users=[];providers=[];groups=[];ugroups=[];names=[]
started=threading.Event();release=threading.Event()


class Fixture(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        p=urlsplit(self.path);code=200
        if p.path.startswith('/unsupported'):
            code=404;body={'error':SECRET}
        elif p.path.startswith('/slow'):
            started.set();release.wait(8);body={'data':[{'id':'real-alpha'}]}
        elif p.path.startswith('/anthropic'):
            assert self.headers.get('x-api-key')==SECRET
            if parse_qs(p.query).get('after_id'):
                body={'data':[{'id':'real-beta'}],'has_more':False,'last_id':'real-beta'}
            else:
                body={'data':[{'id':'real-alpha'}],'has_more':True,'last_id':'real-alpha'}
        else:
            assert self.headers.get('Authorization')=='Bearer '+SECRET
            body={'data':[{'id':'real-alpha'},{'id':'real-beta'},{'id':'real-alpha'}]}
        raw=json.dumps(body).encode();self.send_response(code);self.send_header('Content-Length',str(len(raw)));self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)


def call(c,method,path,status=200,**kwargs):
    r=c.request(method,'/api'+path,**kwargs)
    assert r.status_code==status,f'{method} {path}: {r.status_code} != {status}: {r.text}'
    assert SECRET not in r.text and 'api_key_encrypted' not in r.text
    return r.json()


def login(name):
    c=httpx.Client(base_url='http://127.0.0.1',timeout=30)
    c.headers['Authorization']='Bearer '+call(c,'POST','/auth/login',json={'username':name,'password':PASSWORD})['data']['access_token'];return c


async def seed():
    async with session_factory.begin() as db:
        for suffix,role in [('_admin','admin'),('_user','user'),('_other','user')]:
            rid=await db.scalar(select(Role.id).where(Role.code==role))
            u=User(username=PREFIX+suffix,role=role,role_id=rid,status='enabled',must_change_password=False,password_hash=await hash_password(PASSWORD))
            db.add(u);await db.flush();users.append(u.id)


async def candidate_ids(group_id,name):
    async with session_factory() as db:
        rows=await authorized_candidates(db,group_id,name)
        return [m.provider_id for m,p in rows]


async def denied_candidates(group_id,name,code):
    try:
        await candidate_ids(group_id,name)
        raise AssertionError('Unauthorized/unavailable model returned candidates')
    except APIError as e: assert e.detail['code']==code


async def main():
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);threading.Thread(target=server.serve_forever,daemon=True).start()
    url='http://127.0.0.1:'+str(server.server_port)
    await seed()
    try:
        admin,user,other=login(PREFIX+'_admin'),login(PREFIX+'_user'),login(PREFIX+'_other')
        def provider(suffix,kind='custom_openai',path='/v1',protocol='openai'):
            r=call(admin,'POST','/admin/providers',201,json={'name':PREFIX+suffix,'provider_type':kind,'protocol':protocol,'base_url':url+path,'api_key':SECRET})['data'];providers.append(r['id']);return r['id']
        p1,p2=provider('_p1'),provider('_p2')
        result=call(admin,'POST',f'/admin/providers/{p1}/discover-models')['data']
        assert [m['id'] for m in result['models']]==['real-alpha','real-beta'] and result['http_status']==200
        pa=provider('_anthropic','anthropic','/anthropic','anthropic')
        assert [m['id'] for m in call(admin,'POST',f'/admin/providers/{pa}/discover-models')['data']['models']]==['real-alpha','real-beta']
        call(admin,'PATCH',f'/admin/providers/{p2}',json={'base_url':url+'/unsupported'})
        call(admin,'POST',f'/admin/providers/{p2}/discover-models',502)
        call(user,'POST',f'/admin/providers/{p1}/discover-models',403)
        alpha,beta=PREFIX+'-chat',PREFIX+'-reason';names.extend([alpha,beta])
        def add(pid,name,upstream,kind='text'):
            return call(admin,'POST',f'/admin/providers/{pid}/model-mappings',201,json={'logical_model':name,'upstream_model':upstream,'model_type':kind})['data']
        a1,a2,b1=add(p1,alpha,'real-alpha'),add(p2,alpha,'manual-real-name'),add(p1,beta,'real-beta','reasoning')
        assert len(call(admin,'GET',f'/admin/providers/{p1}/model-mappings')['data'])==2
        call(admin,'POST',f'/admin/providers/{p1}/model-mappings',409,json={'logical_model':alpha,'upstream_model':'duplicate'})
        conflict=call(admin,'POST',f'/admin/providers/{pa}/model-mappings',409,json={'logical_model':alpha,'upstream_model':'x','model_type':'image'})
        assert conflict['error']['code']=='MODEL_TYPE_CONFLICT'
        call(admin,'PUT',f'/admin/providers/{p2}/model-mappings/{a1["id"]}',404,json={'logical_model':alpha,'upstream_model':'x'})
        call(user,'POST',f'/admin/providers/{p1}/model-mappings',403,json={'logical_model':'no-access','upstream_model':'x'})
        call(user,'GET','/admin/logical-models',403)
        print('PASS: actual HTTP discovery/dedup, Anthropic pagination, manual fallback, multi-provider/multi-mapping and type/ownership constraints',flush=True)
        body={'name':PREFIX+'_group','description':'顺序验收','logical_models':[alpha,beta],'status':'enabled'}
        g=call(admin,'POST','/admin/model-groups',201,json=body)['data'];gid=g['id'];groups.append(gid)
        assert g['logical_models']==[alpha,beta]
        call(admin,'POST','/admin/model-groups',422,json={**body,'name':PREFIX+'_duplicate','logical_models':[alpha,alpha]})
        call(admin,'POST','/admin/model-groups',400,json={**body,'name':PREFIX+'_missing','logical_models':['not-in-catalog']})
        call(user,'GET','/admin/model-groups',403)
        body['logical_models']=[beta,alpha];call(admin,'PUT',f'/admin/model-groups/{gid}',json=body)
        assert call(admin,'GET',f'/admin/model-groups/{gid}')['data']['logical_models']==[beta,alpha]
        async with session_factory() as db:
            members=(await db.scalars(select(ModelGroupModel).where(ModelGroupModel.model_group_id==gid).order_by(ModelGroupModel.position))).all()
            assert [(m.logical_model,m.position) for m in members]==[(beta,0),(alpha,1)]
        hidden=call(admin,'POST','/admin/model-groups',201,json={'name':PREFIX+'_private','logical_models':[alpha]})['data'];groups.append(hidden['id'])
        ub={'name':PREFIX+'_users','quota_limit':1000,'model_group_ids':[gid]}
        ug=call(admin,'POST','/admin/user-groups',201,json=ub)['data'];uid=ug['id'];ugroups.append(uid)
        call(admin,'PATCH','/admin/users/'+str(users[1]),json={'user_group_id':uid})
        user=login(PREFIX+'_user')
        raw=call(user,'POST','/portal/api-keys',201,json={'name':'目录验收'})['data']['secret']
        key=httpx.Client(base_url='http://127.0.0.1',timeout=20,headers={'Authorization':'Bearer '+raw})
        catalog=call(user,'GET','/portal/models')['data']['groups'];assert len(catalog)==1
        assert [m['logical_model'] for m in catalog[0]['models']]==[beta,alpha]
        assert 'upstream_model' not in str(catalog) and 'provider_id' not in str(catalog) and url not in str(catalog)
        assert call(key,'GET','/gateway/models')['data']['groups']==catalog
        assert call(other,'GET','/portal/models')['data']['groups']==[]
        call(admin,'DELETE',f'/admin/model-groups/{gid}',409)
        assert await candidate_ids(uid,alpha)==[p1,p2]
        call(admin,'PUT',f'/admin/providers/{p1}/model-mappings/{a1["id"]}',json={'logical_model':alpha,'upstream_model':'real-alpha','status':'disabled'})
        assert await candidate_ids(uid,alpha)==[p2]
        call(admin,'PATCH',f'/admin/providers/{p2}',json={'status':'disabled'})
        await denied_candidates(uid,alpha,'NO_AVAILABLE_PROVIDER')
        assert not next(m for m in call(key,'GET','/gateway/models')['data']['groups'][0]['models'] if m['logical_model']==alpha)['configured']
        body['status']='disabled';call(admin,'PUT',f'/admin/model-groups/{gid}',json=body)
        assert call(key,'GET','/gateway/models')['data']['groups']==[]
        await denied_candidates(uid,beta,'MODEL_FORBIDDEN')
        body['status']='enabled';call(admin,'PUT',f'/admin/model-groups/{gid}',json=body)
        ub['model_group_ids']=[];call(admin,'PUT',f'/admin/user-groups/{uid}',json=ub)
        assert call(key,'GET','/gateway/models')['data']['groups']==[]
        await denied_candidates(uid,beta,'MODEL_FORBIDDEN')
        print('PASS: ordered multi-model groups, persisted reorder, user/group/Key catalog isolation and live disable/revoke candidate filtering',flush=True)
        call(admin,'DELETE',f'/admin/providers/{p1}/model-mappings/{b1["id"]}')
        assert len(call(admin,'GET',f'/admin/providers/{p1}/model-mappings')['data'])==1
        b2=add(p1,beta,'real-beta','reasoning')
        assert b2['id']!=b1['id']
        call(admin,'PATCH',f'/admin/providers/{p1}',json={'base_url':url+'/slow'})
        def pending():
            c=httpx.Client(base_url='http://127.0.0.1',timeout=20,headers=dict(admin.headers));return c.post(f'/api/admin/providers/{p1}/discover-models')
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(pending);assert started.wait(5)
            call(admin,'PATCH',f'/admin/providers/{p1}',json={'remark':'发现期间变更'});release.set();assert future.result().status_code==409
        call(admin,'DELETE',f'/admin/model-groups/{gid}');groups.remove(gid)
        print('PASS: mapping soft-delete/recreate, referenced group protection, discovery race safety and model group delete',flush=True)
        print('PASS: all stage6 acceptance checks',flush=True)
    finally:
        release.set();server.shutdown();server.server_close()
        async with session_factory.begin() as db:
            await db.execute(delete(User).where(User.id.in_(users)))
            await db.execute(delete(UserGroup).where(UserGroup.id.in_(ugroups)))
            await db.execute(delete(ModelGroup).where(ModelGroup.id.in_(groups)))
            await db.execute(delete(ProviderModelMapping).where(ProviderModelMapping.provider_id.in_(providers)))
            await db.execute(delete(Provider).where(Provider.id.in_(providers)))
            await db.execute(delete(LogicalModel).where(LogicalModel.name.in_(names)))
        await engine.dispose()

asyncio.run(main())

