"""Real HTTP/DB Stage4 acceptance; never resets real admin or removes business data."""
import asyncio,uuid
import httpx
from sqlalchemy import delete,select,update
from app.core.database import session_factory,engine
from app.core.security import hash_password,digest
from app.models.user import User,Role,ModelGroup,UserGroup,ApiKey,AuditLog
from app.services.key_auth import KeyPrincipal,require_model_group
from app.core.exceptions import APIError
PREFIX='stage4_'+uuid.uuid4().hex[:10]
PASSWORD='Stage4-Acceptance-2026!'
users=[];groups=[];models=[]


def call(client,method,path,status=200,**kwargs):
    response=client.request(method,'/api'+path,**kwargs)
    assert response.status_code==status,f'{method} {path}: {response.status_code} != {status}: {response.text}'
    return response.json()


def login(name):
    client=httpx.Client(base_url='http://127.0.0.1',timeout=20)
    data=call(client,'POST','/auth/login',json={'username':name,'password':PASSWORD})['data']
    client.headers['Authorization']='Bearer '+data['access_token']
    return client


async def seed():
    async with session_factory.begin() as db:
        for suffix,role in [('_root','super_admin'),('_one','user'),('_two','user')]:
            role_id=await db.scalar(select(Role.id).where(Role.code==role))
            user=User(username=PREFIX+suffix,role=role,role_id=role_id,status='enabled',must_change_password=False,password_hash=await hash_password(PASSWORD))
            db.add(user);await db.flush();users.append(user.id)
        for suffix in ('a','b'):
            model=ModelGroup(name=PREFIX+suffix,status='enabled')
            db.add(model);await db.flush();models.append(model.id)


async def main():
    await seed()
    try:
        root,one,two=login(PREFIX+'_root'),login(PREFIX+'_one'),login(PREFIX+'_two')
        body={'name':PREFIX+'_group','description':'中文用户组','quota_limit':123456,'quota_period':'daily','max_concurrency':7,'key_max_concurrency':3,'model_group_ids':[models[0]],'status':'enabled'}
        group=call(root,'POST','/admin/user-groups',201,json=body)['data'];gid=group['id'];groups.append(gid)
        assert group['model_group_ids']==[models[0]] and group['quota_limit']==123456
        call(root,'POST','/admin/user-groups',409,json=body)
        call(root,'POST','/admin/user-groups',422,json={**body,'quota_limit':-1})
        call(root,'POST','/admin/user-groups',400,json={**body,'name':PREFIX+'_bad','model_group_ids':[2147483647]})
        call(one,'GET','/admin/user-groups',403)
        call(one,'POST','/admin/user-groups',403,json=body)
        assert call(root,'GET','/admin/user-groups',params={'q':PREFIX})['data']['total']==1
        for uid in users[1:]:
            call(root,'PATCH','/admin/users/'+str(uid),json={'user_group_id':gid})
        call(one,'GET','/auth/me',401)
        one,two=login(PREFIX+'_one'),login(PREFIX+'_two')
        call(root,'DELETE','/admin/user-groups/'+str(gid),409)
        print('PASS: group CRUD, validation, model group FK, assignment revokes sessions, referenced group protected',flush=True)

        data=call(one,'POST','/portal/api-keys',201,json={'name':'验收 Key'})['data']
        raw=data['secret'];kid=data['key']['id'];assert raw.startswith('sk-hd-') and len(raw)==49
        key_client=httpx.Client(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+raw})
        identity=call(key_client,'GET','/gateway/identity')['data']
        assert identity['allowed_model_group_ids']==[models[0]] and identity['user_group']['max_concurrency']==7
        listing=call(one,'GET','/portal/api-keys')['data'];assert listing['total']==1
        assert raw not in str(listing) and 'key_hash' not in str(listing) and 'secret' not in str(listing)
        assert call(one,'GET','/portal/api-keys/'+str(kid))['data']['last_used_at']
        async with session_factory() as db:
            key=await db.get(ApiKey,kid)
            assert key.key_hash==digest(raw) and raw not in str(key.__dict__) and key.prefix==raw[:12] and key.suffix==raw[-4:]
            audit=(await db.scalars(select(AuditLog).where(AuditLog.actor_id.in_(users)))).all()
            assert all(raw not in str(a.__dict__) and digest(raw) not in str(a.__dict__) for a in audit)
        refreshed=call(one,'POST','/auth/refresh',headers={'X-CSRF-Token':one.cookies.get('hd_csrf')})['data']
        one.headers['Authorization']='Bearer '+refreshed['access_token']
        assert raw not in str(call(one,'GET','/portal/api-keys'))
        call(two,'GET','/portal/api-keys/'+str(kid),404)
        call(two,'PATCH','/portal/api-keys/'+str(kid),404,json={'name':'越权'})
        call(two,'DELETE','/portal/api-keys/'+str(kid),404)
        call(root,'GET','/portal/api-keys/'+str(kid),404)
        call(one,'PATCH','/portal/api-keys/'+str(kid),422,json={'user_id':users[2]})
        call(one,'PATCH','/portal/api-keys/'+str(kid),422,json={'name':None})
        call(one,'PATCH','/portal/api-keys/'+str(kid),json={'name':'更新名称','status':'disabled'})
        call(key_client,'GET','/gateway/identity',401)
        call(one,'PATCH','/portal/api-keys/'+str(kid),json={'status':'enabled'})
        call(key_client,'GET','/gateway/identity')
        print('PASS: hash-only storage, one-time key display, refresh secrecy, last use, ownership isolation and immediate Key disable',flush=True)

        body['status']='disabled';call(root,'PUT','/admin/user-groups/'+str(gid),json=body)
        assert call(key_client,'GET','/gateway/identity',403)['error']['code']=='GROUP_DISABLED'
        body.update(status='enabled',model_group_ids=[models[1]],quota_period='permanent',quota_limit=789,max_concurrency=9)
        call(root,'PUT','/admin/user-groups/'+str(gid),json=body)
        identity=call(key_client,'GET','/gateway/identity')['data']
        assert identity['allowed_model_group_ids']==[models[1]] and identity['user_group']['quota_limit']==789 and identity['user_group']['max_concurrency']==9
        try:
            require_model_group(KeyPrincipal(None,None,None,identity['allowed_model_group_ids']),models[0])
            raise AssertionError('unauthorized model allowed')
        except APIError as e:
            assert e.detail['code']=='MODEL_FORBIDDEN'
        async with session_factory.begin() as db:
            await db.execute(update(ModelGroup).where(ModelGroup.id==models[1]).values(status='disabled'))
        assert call(key_client,'GET','/gateway/identity')['data']['allowed_model_group_ids']==[]
        second=call(one,'POST','/portal/api-keys',201,json={'name':'第二 Key'})['data']['secret']
        second_client=httpx.Client(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+second})
        call(root,'PATCH','/admin/users/'+str(users[1]),json={'status':'disabled'})
        for c in (key_client,second_client):
            assert call(c,'GET','/gateway/identity',403)['error']['code']=='USER_DISABLED'
        call(root,'PATCH','/admin/users/'+str(users[1]),json={'status':'enabled','user_group_id':None})
        assert call(key_client,'GET','/gateway/identity',403)['error']['code']=='GROUP_REQUIRED'
        call(root,'PATCH','/admin/users/'+str(users[1]),json={'user_group_id':gid})
        one=login(PREFIX+'_one')
        call(root,'POST','/admin/users/'+str(users[1])+'/reset-password')
        assert call(key_client,'GET','/gateway/identity',403)['error']['code']=='PASSWORD_CHANGE_REQUIRED'
        async with session_factory.begin() as db:
            user=await db.get(User,users[1]);user.must_change_password=False;user.password_hash=await hash_password(PASSWORD)
        one=login(PREFIX+'_one')
        call(one,'DELETE','/portal/api-keys/'+str(kid))
        call(key_client,'GET','/gateway/identity',401)
        call(one,'GET','/portal/api-keys/'+str(kid),404)
        call(one,'PATCH','/portal/api-keys/'+str(kid),404,json={'status':'enabled'})
        call(root,'DELETE','/admin/users/'+str(users[1]))
        call(second_client,'GET','/gateway/identity',403)
        invalid=httpx.Client(base_url='http://127.0.0.1',headers={'Authorization':'Bearer sk-hd-invalid'})
        call(invalid,'GET','/gateway/identity',401)
        print('PASS: immediate group/user/model disable, live permission/quota changes, unassigned group denial, forced change and deletion',flush=True)
        print('PASS: all stage4 backend acceptance checks',flush=True)
    finally:
        async with session_factory.begin() as db:
            await db.execute(delete(User).where(User.id.in_(users)))
            await db.execute(delete(UserGroup).where(UserGroup.id.in_(groups)))
            await db.execute(delete(ModelGroup).where(ModelGroup.id.in_(models)))
        await engine.dispose()

asyncio.run(main())
