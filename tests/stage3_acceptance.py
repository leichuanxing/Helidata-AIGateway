"""Run inside the stage3 container against Nginx and real PostgreSQL/Redis."""
import asyncio
import secrets
import subprocess
import uuid
import httpx
import jwt
from sqlalchemy import delete, select
from app.core.config import get_settings
from app.core.redis import redis_client
from concurrent.futures import ThreadPoolExecutor
from app.core.database import session_factory,engine
from app.core.security import hash_password,digest
from app.models.user import User,Role,RefreshSession,AuditLog

PREFIX='stage3_'+uuid.uuid4().hex[:10]
created=[]
base='http://127.0.0.1'
new_password='Stage3-Test-Password-2026!'


def call(client,method,path,status=200,**kwargs):
    csrf=client.cookies.get('hd_csrf')
    headers={'X-CSRF-Token':csrf} if csrf else {}
    headers.update(kwargs.pop('headers',{}))
    result=client.request(method,'/api'+path,headers=headers,**kwargs)
    assert result.status_code==status, f'{method} {path}: {result.status_code} != {status}: {result.text}'
    return result.json()


def login(client,username,password,status=200):
    result=call(client,'POST','/auth/login',status,json={'username':username,'password':password})
    if status==200:
        client.headers['Authorization']='Bearer '+result['data']['access_token']
    return result


def activate(username,password):
    client=httpx.Client(base_url=base,timeout=20)
    login(client,username,password)
    call(client,'POST','/auth/change-password',json={'old_password':password,'new_password':new_password})
    login(client,username,new_password)
    return client


async def seed():
    async with session_factory.begin() as db:
        role_id=await db.scalar(select(Role.id).where(Role.code=='super_admin'))
        password='Aa1!'+secrets.token_urlsafe(24)
        user=User(username=PREFIX+'_root',role='super_admin',role_id=role_id,
                  password_hash=await hash_password(password),status='enabled',must_change_password=True)
        db.add(user)
        await db.flush()
        created.append(user.id)
        return user.username,password,user.id


async def inspect_sessions(client):
    raw=client.cookies.get('hd_refresh')
    async with session_factory() as db:
        session=await db.scalar(select(RefreshSession).where(RefreshSession.token_hash==digest(raw)))
        assert session and session.token_hash!=raw and len(session.token_hash)==64


async def cleanup():
    async with session_factory.begin() as db:
        await db.execute(delete(User).where(User.id.in_(created)))
    await engine.dispose()


async def main():
    await redis_client.delete('login:ip:'+digest('127.0.0.1'))
    username,password,root_id=await seed()
    try:
        operator=httpx.Client(base_url=base,timeout=20)
        original=login(operator,username,password)['data']
        assert original['user']['must_change_password']
        assert 'password_hash' not in str(original)
        assert call(operator,'GET','/admin/users',403)['error']['code']=='PASSWORD_CHANGE_REQUIRED'
        call(operator,'POST','/auth/change-password',422,json={'old_password':password,'new_password':'short'})
        call(operator,'POST','/auth/change-password',400,json={'old_password':'wrong','new_password':new_password})
        call(operator,'POST','/auth/change-password',400,json={'old_password':password,'new_password':password})
        call(operator,'POST','/auth/change-password',json={'old_password':password,'new_password':new_password})
        call(operator,'GET','/auth/me',401)
        login(operator,username,new_password)
        assert not call(operator,'GET','/auth/me')['data']['must_change_password']
        print('PASS: login, forced password change, password policy, old token invalidation',flush=True)

        old_refresh=operator.cookies.get('hd_refresh')
        old_csrf=operator.cookies.get('hd_csrf')
        refreshed=call(operator,'POST','/auth/refresh')['data']
        operator.headers['Authorization']='Bearer '+refreshed['access_token']
        assert operator.cookies.get('hd_refresh')!=old_refresh
        replay=httpx.Client(base_url=base,timeout=20,headers={'Cookie':f'hd_refresh={old_refresh}; hd_csrf={old_csrf}','X-CSRF-Token':old_csrf})
        call(replay,'POST','/auth/refresh',401)
        call(operator,'POST','/auth/refresh',403,headers={'X-CSRF-Token':''})
        call(operator,'POST','/auth/refresh',403,headers={'Origin':'https://untrusted.example'})
        await inspect_sessions(operator)
        print('PASS: refresh rotation, replay rejection, CSRF/origin protection, hash-only refresh storage',flush=True)

        def add(role,suffix):
            data=call(operator,'POST','/admin/users',201,json={'username':PREFIX+suffix,'role':role,'name':'验收用户','status':'enabled'})['data']
            created.append(data['user']['id'])
            assert data['user']['must_change_password']
            assert 'password_hash' not in str(data)
            return data['user'],data['initial_password']
        ordinary,initial=add('user','_user')
        ordinary_client=activate(ordinary['username'],initial)
        regular_admin,initial=add('admin','_admin')
        admin_client=activate(regular_admin['username'],initial)
        other_admin,initial=add('admin','_admin2')
        call(ordinary_client,'GET','/admin/users',403)
        call(admin_client,'GET','/admin/users/'+str(root_id),403)
        call(admin_client,'GET','/admin/users/'+str(other_admin['id']),403)
        call(admin_client,'POST','/admin/users/'+str(root_id)+'/reset-password',403)
        call(admin_client,'DELETE','/admin/users/'+str(other_admin['id']),403)
        call(admin_client,'POST','/admin/users',403,json={'username':PREFIX+'_bad','role':'super_admin'})
        call(admin_client,'PATCH','/admin/users/'+str(ordinary['id']),403,json={'role':'admin','status':'enabled'})
        assert all(user['role']=='user' for user in call(admin_client,'GET','/admin/users')['data']['items'])
        call(operator,'DELETE','/admin/users/'+str(root_id),409)
        call(operator,'PATCH','/admin/users/'+str(root_id),409,json={'role':'super_admin','status':'disabled'})
        print('PASS: ordinary/admin/super-admin server permissions, no privilege escalation, self-protection',flush=True)

        call(ordinary_client,'PATCH','/portal/profile',json={'name':'姓名更新','email':'test@example.com','phone':'13800000000'})
        call(ordinary_client,'PATCH','/portal/profile',422,json={'name':'x','role':'super_admin'})
        call(ordinary_client,'PATCH','/portal/profile',json={'name':'姓名更新'})
        assert call(ordinary_client,'GET','/auth/me')['data']['email']=='test@example.com'
        assert call(ordinary_client,'GET','/auth/me')['data']['name']=='姓名更新'
        q=call(operator,'GET','/admin/users',params={'q':ordinary['username']})['data']
        assert q['total']==1 and q['items'][0]['id']==ordinary['id']
        user_id=ordinary['id']
        call(operator,'PATCH','/admin/users/'+str(user_id),json={'name':'姓名更新','role':'user','status':'disabled'})
        assert call(ordinary_client,'GET','/auth/me',403)['error']['code']=='USER_DISABLED'
        call(ordinary_client,'POST','/auth/refresh',401)
        login(httpx.Client(base_url=base),ordinary['username'],new_password,401)
        call(operator,'PATCH','/admin/users/'+str(user_id),json={'name':'姓名更新','role':'user','status':'enabled'})
        call(ordinary_client,'GET','/auth/me',401)
        login(ordinary_client,ordinary['username'],new_password)
        reset=call(operator,'POST','/admin/users/'+str(user_id)+'/reset-password')['data']['initial_password']
        call(ordinary_client,'GET','/auth/me',401)
        call(ordinary_client,'POST','/auth/refresh',401)
        login(ordinary_client,ordinary['username'],reset)
        call(ordinary_client,'PATCH','/portal/profile',403,json={'name':'x'})
        call(operator,'DELETE','/admin/users/'+str(user_id))
        call(operator,'GET','/admin/users/'+str(user_id),404)
        login(httpx.Client(base_url=base),ordinary['username'],reset,401)
        print('PASS: profile/search, disable revokes access/refresh, re-enable cannot revive old tokens, reset/delete',flush=True)

        raw=operator.headers['Authorization'][7:]
        operator.headers['Authorization']='Bearer '+raw[:-5]+'xxxxx'
        call(operator,'GET','/auth/me',401)
        claims=jwt.decode(raw,get_settings().security.jwt_secret.get_secret_value(),algorithms=['HS256'],audience='helidata-web')
        claims['exp']=1
        operator.headers['Authorization']='Bearer '+jwt.encode(claims,get_settings().security.jwt_secret.get_secret_value(),algorithm='HS256')
        call(operator,'GET','/auth/me',401)
        operator.headers['Authorization']='Bearer '+raw
        call(operator,'POST','/auth/logout')
        call(operator,'GET','/auth/me',401)
        call(operator,'POST','/auth/refresh',401)
        unknown=PREFIX+'_unknown'
        for _ in range(get_settings().security.login_max_attempts):
            result=login(httpx.Client(base_url=base),unknown,'wrong',401)
            assert result['error']['message']=='用户名或密码错误'
        login(httpx.Client(base_url=base),unknown,'wrong',429)
        async with session_factory() as db:
            user=await db.get(User,user_id)
            assert user.deleted_at is not None and user.status=='deleted'
            assert (await db.scalars(select(AuditLog).where(AuditLog.actor_id==root_id))).all()
        def attempt(_):
            with httpx.Client(base_url=base,timeout=20) as client:
                return client.post('/api/auth/login',json={'username':PREFIX+'_parallel','password':'wrong'}).status_code
        with ThreadPoolExecutor(max_workers=12) as pool:
            statuses=list(pool.map(attempt,range(12)))
        assert statuses.count(401)==get_settings().security.login_max_attempts and statuses.count(429)==12-get_settings().security.login_max_attempts
        print('PASS: concurrent login attempts respect atomic failure limit',flush=True)
        print('PASS: forged/expired JWT, logout revocation, login throttling, soft delete and audit records',flush=True)
        print('PASS: all stage3 backend acceptance checks',flush=True)
    finally:
        await cleanup()


asyncio.run(main())
