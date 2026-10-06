"""Complementary API/privacy checks in the held UI fixture."""
import asyncio, json, subprocess
import httpx
from sqlalchemy import select
from app.core.database import session_factory, engine
from app.models.call_log import CallLog
from app.models.user import User,Role
from app.core.security import hash_password
from app.services.provider_crypto import encrypt_secret, decrypt_secret
from app.core.exceptions import APIError
import stage12_nonstream_regression as seed


async def main():
    seed.URL='http://127.0.0.1:9'
    await seed.seed()
    async with session_factory.begin() as db:
        roles=dict((code,ident) for ident,code in (await db.execute(select(Role.id,Role.code))).all())
        for role in ('super_admin','admin','user'):
            db.add(User(username=seed.PREFIX+'-probe-'+role,role=role,role_id=roles[role],password_hash=await hash_password('Stage19!Isolated84925'),must_change_password=False))
    async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=30) as c:
        for role,expected in [('super_admin',200),('admin',403),('user',403)]:
            r=await c.post('/api/auth/login',json={'username':seed.PREFIX+'-probe-'+role,'password':'Stage19!Isolated84925'})
            assert r.status_code==200
            token=r.json()['data']['access_token']
            assert (await c.get('/api/admin/runtime',headers={'Authorization':'Bearer '+token})).status_code==expected
            if role=='super_admin':admin=token
        headers={'Authorization':'Bearer '+admin}
        raw='isolated-private-key-never-echo'
        first,second=encrypt_secret(raw),encrypt_secret(raw)
        assert first!=second and decrypt_secret(first)==raw
        try:decrypt_secret(first[:-3]+'AAA')
        except APIError as error:assert error.detail['code']=='PROVIDER_KEY_DECRYPT_FAILED'
        else:raise AssertionError('tampered ciphertext accepted')
        r=await c.post('/api/admin/providers',headers=headers,json={raw:raw})
        assert r.status_code==422 and raw not in r.text
        malicious='<img src=x onerror=alert(19)>'
        r=await c.post('/api/admin/providers',headers=headers,json={'name':malicious,
            'provider_type':'custom_openai','protocol':'openai','base_url':'http://127.0.0.1:9/v1','status':'disabled'})
        assert r.status_code==201,r.text[:100]
        r=await c.get('/api/admin/providers',headers=headers,params={'q':"%' OR 1=1 --"})
        assert r.status_code==200 and r.json()['data']['total']==0
        r=await c.get('/api/admin/providers',headers=headers,params={'q':malicious})
        assert r.status_code==200 and r.json()['data']['total']==1
        recorded=[]
        for service in ('redis','postgresql'):
            subprocess.check_call(['supervisorctl','stop',service],stdout=subprocess.DEVNULL)
            try:
                r=await c.post('/api/gateway/preflight',headers={'Authorization':'Bearer '+seed.KEY},json={'model':seed.NAME})
                assert r.status_code>=500 and seed.KEY not in r.text
                recorded.append((r.headers['X-Request-ID'],r.status_code,r.json()['error']['code']))
            finally:subprocess.check_call(['supervisorctl','start',service],stdout=subprocess.DEVNULL)
            for _ in range(30):
                if (await c.get('/health')).status_code==200:break
                await asyncio.sleep(1)
            r=await c.get('/v1/models',headers={'Authorization':'Bearer '+seed.KEY})
            assert r.status_code==200
        for _ in range(20):
            async with session_factory() as db:
                rows=(await db.scalars(select(CallLog).where(CallLog.request_id.in_([r[0] for r in recorded])))).all()
            if len(rows)==2:break
            await asyncio.sleep(1)
        assert {(r.request_id,r.http_status,r.error_code) for r in rows}==set(recorded)
        print('PASS: super/admin/user runtime boundary; randomized authenticated AES encryption rejects tampering; unknown JSON-key privacy; parameterized SQL search; literal XSS label seeded; real Redis/Postgres outage response/log agreement and catalog recovery',flush=True)
    await engine.dispose()


asyncio.run(main())
