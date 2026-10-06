"""Typed groups, custom names, atomic validation and route reference protection."""
import asyncio
from pathlib import Path
from uuid import uuid4
import httpx


async def main():
    assert Path('/data/.reproduction-ui-isolated').read_text().strip()=='reproduction-ui-isolated'
    prefix='typed-'+uuid4().hex[:10]
    async with httpx.AsyncClient(base_url='http://127.0.0.1',trust_env=False,timeout=20) as c:
        login=await c.post('/api/auth/login',json={'username':'replica-manager','password':'Reproduction!Fixture2026'})
        assert login.status_code==200
        h={'Authorization':'Bearer '+login.json()['data']['access_token']}
        async def create(name,category,models):
            return await c.post('/api/admin/model-groups',json={'name':name,'protocol_type':category,'logical_models':models},headers=h)
        custom=prefix+'-custom'
        r=await create(prefix,'text',['deepseek-flash',custom]);assert r.status_code==201,r.text
        group=r.json()['data'];ident=group['id'];assert group['logical_models']==['deepseek-flash',custom]
        r=await c.put(f'/api/admin/model-groups/{ident}',json={'name':prefix,'protocol_type':'text','logical_models':[custom,'deepseek-flash']},headers=h)
        assert r.status_code==200 and r.json()['data']['logical_models']==[custom,'deepseek-flash']
        listed=(await c.get('/api/admin/model-groups',params={'protocol_type':'text','q':prefix},headers=h)).json()['data']
        assert listed['total']==1 and listed['items'][0]['id']==ident
        assert (await c.get('/api/admin/model-groups',params={'protocol_type':'image','q':prefix},headers=h)).json()['data']['total']==0
        r=await create(prefix+'-wrong','image',[prefix+'-rollback','deepseek-flash']);assert r.status_code==409
        names={m['name'] for m in (await c.get('/api/admin/logical-models',headers=h)).json()['data']}
        assert prefix+'-rollback' not in names
        assert (await create(prefix+'-bad','text',['name with spaces'])).status_code==422
        assert (await create(prefix+'-dup','text',['deepseek-flash']*2)).status_code==422
        assert (await create(prefix+'-vector','vector',[prefix+'-vector-model'])).status_code==201
        assert (await create(prefix+'-image','image',[prefix+'-image-model'])).status_code==201
        legacy=await c.post('/api/admin/model-groups',json={'name':prefix+'-legacy','logical_models':['deepseek-flash']},headers=h)
        assert legacy.status_code==201 and legacy.json()['data']['protocol_type']=='text'
        second=await create(prefix+'-second','text',['deepseek-flash']);assert second.status_code==201
        route=await c.post('/api/admin/smart-route/configs',json={'virtual_model':prefix+'-auto','embedding_model':'semantic-vector',
            'simple_model_group':ident,'complex_model_group':second.json()['data']['id'],'status':'disabled'},headers=h)
        assert route.status_code==201,route.text
        r=await c.delete(f'/api/admin/model-groups/{ident}',headers=h)
        assert r.status_code==409 and r.json()['error']['code']=='MODEL_GROUP_IN_USE'
        r=await c.put(f'/api/admin/model-groups/{ident}',json={'name':prefix,'protocol_type':'image','logical_models':[]},headers=h)
        assert r.status_code==409
        assert (await c.delete('/api/admin/smart-route/configs/'+str(route.json()['data']['id']),headers=h)).status_code==200
        assert (await c.delete(f'/api/admin/model-groups/{ident}',headers=h)).status_code==200
        assert custom in {m['name'] for m in (await c.get('/api/admin/logical-models',headers=h)).json()['data']}
        viewer=await c.post('/api/auth/login',json={'username':'replica-viewer','password':'Reproduction!Fixture2026'})
        r=await c.post('/api/admin/model-groups',json={'name':prefix+'-forbidden','protocol_type':'text'},headers={'Authorization':'Bearer '+viewer.json()['data']['access_token']})
        assert r.status_code==403
        print('PASS: typed filtering, custom names, persisted order, incompatible-type rollback, invalid/duplicate names, legacy API, route delete/type protection, ordinary-user403; no upstream inference.')


asyncio.run(main())
