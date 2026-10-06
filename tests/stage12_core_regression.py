"""Live DB/HTTP pipeline acceptance; disposable rows only, no upstream inference."""
import asyncio
import io
import logging
import re
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import httpx
from sqlalchemy import select, delete
from app.core.database import session_factory, engine
from app.core.security import digest, hash_password, now
from app.models.user import User, Role, UserGroup, ModelGroup, UserGroupModelGroup, ModelGroupModel, LogicalModel, Provider, ProviderModelMapping, ApiKey
from app.main import app
from app.gateway.request_id import RequestIDFilter

PREFIX = 'stage12core_' + uuid.uuid4().hex[:10]
KEY = 'sk-hd-' + secrets.token_urlsafe(32)
NAME = PREFIX + '-model'
ids = {}


async def seed():
    async with session_factory.begin() as db:
        ug = UserGroup(name=PREFIX, quota_limit=10); db.add(ug); await db.flush(); ids['ug']=ug.id
        role = await db.scalar(select(Role.id).where(Role.code=='user'))
        u = User(username=PREFIX, role='user', role_id=role, user_group_id=ug.id,
            must_change_password=False, password_hash=await hash_password(secrets.token_urlsafe(24)))
        db.add(u); await db.flush(); ids['user']=u.id
        k=ApiKey(user_id=u.id,name=PREFIX,key_hash=digest(KEY),prefix=KEY[:12],suffix=KEY[-4:]);db.add(k);await db.flush();ids['key']=k.id
        g=ModelGroup(name=PREFIX);db.add(g);await db.flush();ids['mg']=g.id
        db.add(LogicalModel(name=NAME,model_type='text'));await db.flush()
        db.add(ModelGroupModel(model_group_id=g.id,logical_model=NAME,position=0))
        db.add(UserGroupModelGroup(user_group_id=ug.id,model_group_id=g.id))
        p=Provider(name=PREFIX,provider_type='custom_openai',protocol='openai',base_url='http://127.0.0.1:1')
        db.add(p);await db.flush();ids['provider']=p.id
        db.add(ProviderModelMapping(provider_id=p.id,logical_model=NAME,upstream_model='private-upstream-model',model_type='text'))


async def change(model,key,**values):
    async with session_factory.begin() as db:
        row=await db.get(model,ids[key])
        for name,value in values.items(): setattr(row,name,value)


def check(response,status,code=None):
    assert response.status_code==status, response.text
    rid=response.headers['X-Request-ID'];assert re.fullmatch('req_[0-9a-f]{32}',rid)
    assert response.headers['Cache-Control']=='no-store'
    assert KEY not in response.text and 'private-upstream-model' not in response.text
    if code:
        error=response.json()['error']
        assert error['code']==code and error['type']=='gateway_error' and error['request_id']==rid
        assert set(error)=={'code','type','message','request_id'}
    return response.json(),rid


async def main():
    await seed()
    client=httpx.AsyncClient(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+KEY})
    logs=io.StringIO();handler=logging.StreamHandler(logs);handler.addFilter(RequestIDFilter())
    handler.setFormatter(logging.Formatter('request_id=%(request_id)s %(message)s'));logging.getLogger().addHandler(handler)
    try:
        data,_=check(await client.get('/v1/models'),200)
        assert isinstance(data['data'][0].pop('created'),int)
        assert data=={'object':'list','data':[{'id':NAME,'object':'model','owned_by':'helidata'}]}
        data,_=check(await client.post('/api/gateway/preflight',json={'model':NAME}),200)
        assert data['data']['ready'] and data['data']['inference_enabled'] is True
        assert 'quota' not in data['data']['deferred'] and data['data']['quota']['limit']==10
        assert data['data']['quota']['reported_tokens']==0 and data['data']['quota']['reserved_budget']==0
        async with session_factory() as db: assert (await db.get(ApiKey,ids['key'])).last_used_at
        check(await client.post('/api/gateway/preflight',json={'model':'ungranted'}),403,'MODEL_FORBIDDEN')
        check(await client.get('/v1/models',headers={'Authorization':'Bearer invalid'}),401,'INVALID_API_KEY')
        check(await client.post('/api/gateway/preflight',json={'model':{'secret':KEY}}),422,'VALIDATION_ERROR')
        check(await client.get('/v1/missing'),404,'HTTP_404')
        check(await client.post('/v1/models'),405,'HTTP_405')
        await change(Provider,'provider',status='disabled')
        check(await client.post('/api/gateway/preflight',json={'model':NAME}),503,'NO_AVAILABLE_PROVIDER')
        await change(Provider,'provider',status='enabled',health_status='unhealthy')
        check(await client.post('/api/gateway/preflight',json={'model':NAME}),503,'NO_AVAILABLE_PROVIDER')
        from datetime import timedelta
        await change(Provider,'provider',health_status='healthy',cooldown_until=now()+timedelta(minutes=5))
        check(await client.post('/api/gateway/preflight',json={'model':NAME}),503,'NO_AVAILABLE_PROVIDER')
        await change(Provider,'provider',cooldown_until=None)
        await change(ModelGroup,'mg',status='disabled')
        check(await client.post('/api/gateway/preflight',json={'model':NAME}),403,'MODEL_FORBIDDEN')
        data,_=check(await client.get('/v1/models'),200);assert data['data']==[]
        await change(ModelGroup,'mg',status='enabled')
        for model,key,values,code in [(UserGroup,'ug',{'status':'disabled'},'GROUP_DISABLED'),
            (User,'user',{'status':'disabled'},'USER_DISABLED'),(User,'user',{'must_change_password':True},'PASSWORD_CHANGE_REQUIRED'),
            (ApiKey,'key',{'status':'disabled'},'INVALID_API_KEY')]:
            await change(model,key,**values)
            check(await client.get('/v1/models'),401 if key=='key' else 403,code)
            await change(model,key,**{n:False if n=='must_change_password' else 'enabled' for n in values})
        responses=await asyncio.gather(*[client.post('/api/gateway/preflight',json={'model':NAME}) for _ in range(12)])
        assert len({check(r,200)[1] for r in responses})==12
        print('PASS: live HTTP pipeline, model list/preflight, no upstream network, live authorization/disable/cooldown, concurrent unique Request IDs, unified 401/403/404/405/422/503')
        transport=httpx.ASGITransport(app=app,raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport,base_url='http://test',headers={'Authorization':'Bearer '+KEY}) as local:
            data,rid=check(await local.post('/api/gateway/preflight',json={'model':NAME}),200)
            text=logs.getvalue();lines=[l for l in text.splitlines() if rid in l]
            assert any('"stages"' in l and 'protocol_adapter' in l and 'call_log' in l for l in lines)
            assert any('status=200' in l for l in lines)
            async def broken(*args): raise RuntimeError('secret '+KEY)
            with patch('app.gateway.model_selection.select_model',broken):
                result,failed=check(await local.post('/api/gateway/preflight',json={'model':NAME}),500,'INTERNAL_ERROR')
                assert any(failed in l and '"outcome": "failure"' in l for l in logs.getvalue().splitlines())
            assert KEY not in logs.getvalue() and 'private-upstream-model' not in logs.getvalue()
        print('PASS: Request ID spans pipeline completion/failure and HTTP logs; unexpected 500 sanitized with header; no credentials/body/model secrets in logs')
    finally:
        await client.aclose();logging.getLogger().removeHandler(handler)
        async with session_factory.begin() as db:
            await db.execute(delete(User).where(User.id==ids['user']))
            await db.execute(delete(UserGroup).where(UserGroup.id==ids['ug']))
            await db.execute(delete(ModelGroup).where(ModelGroup.id==ids['mg']))
            await db.execute(delete(ProviderModelMapping).where(ProviderModelMapping.provider_id==ids['provider']))
            await db.execute(delete(Provider).where(Provider.id==ids['provider']))
            await db.execute(delete(LogicalModel).where(LogicalModel.name==NAME))
        await engine.dispose()

asyncio.run(main())
