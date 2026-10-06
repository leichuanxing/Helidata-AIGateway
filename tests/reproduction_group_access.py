"""Real migration, catalog/gateway scope, default guards and Redis inheritance checks."""
import asyncio,importlib.util,json,secrets
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import httpx
from sqlalchemy import select,text,delete
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.core.database import session_factory,engine
from app.core.redis import redis_client
from app.core.exceptions import APIError
from app.models.user import UserGroup,User,ApiKey,LogicalModel,Provider,ProviderModelMapping
from app.core.security import digest
from app.services.key_auth import api_key_principal,require_model_group
from starlette.requests import Request
from app.services.group_access import concurrency_limits
from app.services.model_catalog import catalog,authorized_candidates
from app.gateway.model_permission import check
from app.gateway.model_selection import routes
from app.gateway.admission import ADMIT


async def migration_test():
    schema='test_group22_'+uuid4().hex
    assert schema.startswith('test_group22_') and schema.isidentifier()
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA {schema}'))
        await conn.execute(text(f'SET LOCAL search_path TO {schema}'))
        await conn.execute(text("""CREATE TABLE user_groups(id serial PRIMARY KEY,name varchar(80) UNIQUE,
        description text DEFAULT '',status varchar(20) DEFAULT 'enabled',quota_limit bigint DEFAULT 0,
        quota_period varchar(20) DEFAULT 'monthly',max_concurrency integer DEFAULT 10,key_max_concurrency integer DEFAULT 5,
        CONSTRAINT ck_group_concurrency CHECK(max_concurrency>0 AND key_max_concurrency>0))"""))
        await conn.execute(text('CREATE TABLE providers(id integer PRIMARY KEY)'))
        await conn.execute(text("INSERT INTO user_groups(name,max_concurrency,key_max_concurrency) VALUES('Default',4,2),('legacy-denied',7,3)"))
        await conn.execute(text('INSERT INTO providers VALUES(1)'))
        def upgrade(sync):
            spec=importlib.util.spec_from_file_location('group22', '/app/backend/alembic/versions/0022_group_access.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            with Operations.context(MigrationContext.configure(sync)):module.upgrade()
        await conn.run_sync(upgrade)
        rows=(await conn.execute(text('SELECT name,max_concurrency,key_max_concurrency,model_access,is_default,status FROM user_groups ORDER BY id'))).all()
        assert rows[:2]==[('Default',4,2,'selected',False,'enabled'),('legacy-denied',7,3,'selected',False,'enabled')]
        assert rows[2]==('Default (1)',0,0,'selected',True,'enabled'),rows
        await conn.execute(text('SET LOCAL search_path TO public'))
        await conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))


async def main():
    assert Path('/data/.reproduction-ui-isolated').read_text().strip()=='reproduction-ui-isolated'
    await migration_test()
    stamp=uuid4().hex[:10];created=[];keys=[]
    orphan='orphan-'+stamp
    async with httpx.AsyncClient(base_url='http://127.0.0.1',trust_env=False,timeout=30) as client:
        login=await client.post('/api/auth/login',json={'username':'replica-manager','password':'Reproduction!Fixture2026'});assert login.status_code==200
        headers={'Authorization':'Bearer '+login.json()['data']['access_token']}
        default=next(g for g in (await client.get('/api/admin/user-groups',headers=headers)).json()['data']['items'] if g['is_default'])
        body={k:default[k] for k in ('name','description','status','quota_limit','quota_period','max_concurrency','key_max_concurrency','model_group_ids','model_access')}
        assert (await client.put(f'/api/admin/user-groups/{default["id"]}',json={**body,'status':'disabled'},headers=headers)).status_code==409
        assert (await client.delete(f'/api/admin/user-groups/{default["id"]}',headers=headers)).status_code==409
        for limits,scope in [((0,0),'all'),((2,0),'selected')]:
            payload={'name':'access-'+stamp+'-'+scope,'max_concurrency':limits[0],'key_max_concurrency':limits[1],'model_group_ids':[],'model_access':scope}
            response=await client.post('/api/admin/user-groups',json=payload,headers=headers);assert response.status_code==201,response.text
            group=response.json()['data'];created.append(group['id']);assert group['model_access']==scope
            assert group['effective_key_max_concurrency']==group['effective_max_concurrency']
        assert (await client.post('/api/admin/user-groups',json={'name':'negative-'+stamp,'max_concurrency':-1},headers=headers)).status_code==422
        old_payload={'name':'access-'+stamp+'-selected','max_concurrency':2,'key_max_concurrency':0,'model_group_ids':[]}
        old_response=await client.put('/api/admin/user-groups/'+str(created[1]),json=old_payload,headers=headers)
        assert old_response.status_code==200 and old_response.json()['data']['model_access']=='selected'
        view=await client.post('/api/auth/login',json={'username':'replica-viewer','password':'Reproduction!Fixture2026'})
        assert (await client.post('/api/admin/user-groups',json={'name':'forbidden-'+stamp},headers={'Authorization':'Bearer '+view.json()['data']['access_token']})).status_code==403
        password=secrets.token_urlsafe(24)+'aA1!'
        user=await client.post('/api/admin/users',json={'username':'default-'+stamp,'password':password,'password_confirmation':password},headers=headers)
        assert user.status_code==201,user.text
        assert user.json()['data']['user']['user_group_id']==default['id']
        assert (await client.delete('/api/admin/users/'+str(user.json()['data']['user']['id']),headers=headers)).status_code==200
        async with session_factory.begin() as db:
            provider=await db.scalar(select(Provider).where(Provider.name=='fixture-only-no-inference'))
            db.add(LogicalModel(name=orphan,model_type='text'));await db.flush()
            db.add(ProviderModelMapping(provider_id=provider.id,logical_model=orphan,upstream_model=orphan,model_type='text'))
            viewer=await db.scalar(select(User).where(User.username=='replica-viewer'))
            test_user=User(username='key-default-'+stamp,role='user',role_id=viewer.role_id,password_hash='not-a-login-hash',must_change_password=False)
            db.add(test_user);await db.flush();test_user_id=test_user.id
            raw='sk-hd-'+secrets.token_urlsafe(32)
            db.add(ApiKey(user_id=test_user.id,name='isolated-default-key',key_hash=digest(raw),prefix=raw[:12],suffix=raw[-4:]))
        try:
            async with session_factory() as db:
                unrestricted=await db.get(UserGroup,created[0]);denied=await db.get(UserGroup,created[1])
                assert any(m['logical_model']==orphan for g in await catalog(db,unrestricted.id) for m in g['models'])
                assert await catalog(db,denied.id)==[]
                assert await authorized_candidates(db,unrestricted.id,orphan)
                try:await authorized_candidates(db,denied.id,orphan)
                except APIError as exc:assert exc.status_code==403
                else:raise AssertionError('Old selected-only empty scope broadened')
                ctx=SimpleNamespace(group=unrestricted,logical_model=orphan,original_model=None,route_group_id=None,operation='chat')
                await check(db,ctx);selected,_=await routes(db,ctx);assert selected[0][0]==orphan and selected[0][1]
                request=Request({'type':'http','method':'GET','path':'/api/gateway/models','headers':[(b'authorization',('Bearer '+raw).encode())]})
                principal=await api_key_principal(request,db)
                assert principal.group.id==default['id'] and principal.user.user_group_id is None
                assert principal.model_group_ids
                require_model_group(principal,principal.model_group_ids[0])
                assert concurrency_limits(unrestricted,3)==(3,3)
                assert concurrency_limits(denied,3)==(2,2)
                denied.key_max_concurrency=9;assert concurrency_limits(denied,3)==(2,2)
                denied.key_max_concurrency=1;assert concurrency_limits(denied,3)==(2,1)
            keys=['test:'+stamp+':'+str(i) for i in range(8)]
            providers=json.dumps([{'id':1,'key':keys[7],'limit':10}])
            for i in range(3):
                result=await redis_client.eval(ADMIT,7,*keys[:7],stamp+str(i),3,3,3,0,30,providers,0)
                assert result[0]==1
            assert (await redis_client.eval(ADMIT,7,*keys[:7],stamp+'full',3,3,3,0,30,providers,0))[0]==-1
        finally:
            if keys:await redis_client.delete(*keys)
            async with session_factory.begin() as db:
                await db.execute(delete(ApiKey).where(ApiKey.user_id==test_user_id))
                await db.execute(delete(User).where(User.id==test_user_id))
                await db.execute(delete(ProviderModelMapping).where(ProviderModelMapping.logical_model==orphan))
                await db.execute(delete(LogicalModel).where(LogicalModel.name==orphan))
            for ident in created:
                assert (await client.delete('/api/admin/user-groups/'+str(ident),headers=headers)).status_code==200
    await engine.dispose();await redis_client.aclose()
    print('PASS: actual0021-to0022 migration preserves denied scopes/limits; default name collision/guards; new user default; zero inheritance/caps/Redis admission; unrestricted orphan model catalog/permission/selection; negative422/viewer403; zero upstream calls.')

asyncio.run(main())
