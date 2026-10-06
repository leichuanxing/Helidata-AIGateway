"""Password confirmation/reset, session revocation and account-only unlock."""
import asyncio,secrets
from pathlib import Path
from uuid import uuid4
import httpx
from app.core.redis import redis_client
from app.core.security import digest
from app.core.config import get_settings


async def main():
    assert Path('/data/.reproduction-ui-isolated').read_text().strip()=='reproduction-ui-isolated'
    username='parity-'+uuid4().hex[:10]
    password=secrets.token_urlsafe(24)+'aA1!';new_password=secrets.token_urlsafe(24)+'aA1!'
    account_key='login:account:'+digest(username.lower());ip_key='login:ip:'+digest('203.0.113.98')
    async with httpx.AsyncClient(base_url='http://127.0.0.1',trust_env=False,timeout=20) as c:
        r=await c.post('/api/auth/login',json={'username':'replica-manager','password':'Reproduction!Fixture2026'});assert r.status_code==200
        actor=r.json()['data']['user'];h={'Authorization':'Bearer '+r.json()['data']['access_token']}
        body={'username':username,'password':password,'password_confirmation':password,'user_group_id':actor['user_group_id'],'remark':'用户备注验证'}
        assert (await c.post('/api/admin/users',json={**body,'password_confirmation':password+'x'},headers=h)).status_code==422
        assert (await c.post('/api/admin/users',json={**body,'password':'weak','password_confirmation':'weak'},headers=h)).status_code==422
        r=await c.post('/api/admin/users',json=body,headers=h);assert r.status_code==201
        user=r.json()['data']['user'];ident=user['id'];assert user['remark']=='用户备注验证' and user['must_change_password']
        assert not {'password','password_hash','password_confirmation'}.intersection(user)
        login=await c.post('/api/auth/login',json={'username':username,'password':password});assert login.status_code==200
        old={'Authorization':'Bearer '+login.json()['data']['access_token']}
        assert (await c.get('/api/admin/users',headers=old)).status_code==403
        reset={'password':new_password,'password_confirmation':new_password+'x'}
        assert (await c.post(f'/api/admin/users/{ident}/reset-password',json=reset,headers=h)).status_code==422
        assert (await c.get('/api/auth/me',headers=old)).status_code==200
        reset['password_confirmation']=new_password
        r=await c.post(f'/api/admin/users/{ident}/reset-password',json=reset,headers=h);assert r.status_code==200
        assert new_password not in r.text
        assert (await c.get('/api/auth/me',headers=old)).status_code==401
        assert (await c.post('/api/auth/login',json={'username':username,'password':password})).status_code==401
        r=await c.post('/api/auth/login',json={'username':username,'password':new_password});assert r.status_code==200 and r.json()['data']['user']['must_change_password']
        viewer=await c.post('/api/auth/login',json={'username':'replica-viewer','password':'Reproduction!Fixture2026'});assert viewer.status_code==200
        v={'Authorization':'Bearer '+viewer.json()['data']['access_token']}
        assert (await c.post(f'/api/admin/users/{ident}/unlock',headers=v)).status_code==403
        await redis_client.set(account_key,get_settings().security.login_max_attempts,ex=60)
        await redis_client.set(ip_key,5,ex=60)
        try:
            row=(await c.get(f'/api/admin/users/{ident}',headers=h)).json()['data']
            assert row['login_locked'] and 0<row['lock_remaining_seconds']<=60
            assert (await c.post('/api/auth/login',json={'username':username,'password':new_password})).status_code==429
            assert (await c.post(f'/api/admin/users/{ident}/unlock',headers=h)).status_code==200
            assert await redis_client.get(account_key) is None and await redis_client.get(ip_key)=='5'
            assert not (await c.get(f'/api/admin/users/{ident}',headers=h)).json()['data']['login_locked']
            assert (await c.post('/api/auth/login',json={'username':username,'password':new_password})).status_code==200
            assert (await c.patch(f'/api/admin/users/{actor["id"]}',json={'status':'disabled'},headers=h)).status_code==409
            assert (await c.delete(f'/api/admin/users/{ident}',headers=h)).status_code==200
        finally:
            await redis_client.delete(account_key,ip_key)
    await redis_client.aclose()
    print('PASS: password complexity/confirmation; remark persistence; reset invalidates old sessions, preserves first-login change requirement, no password echo; account lock display/unlock; IP protection retained; ordinary-user403; self-disable409; zero inference.')


asyncio.run(main())
