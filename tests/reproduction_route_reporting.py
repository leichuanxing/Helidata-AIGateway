"""Real SQL route reporting: missing usage, parent-only joins and combined filters."""
import asyncio,sys
from pathlib import Path
from uuid import uuid4
import httpx
from sqlalchemy import delete
from app.core.database import session_factory,engine
from app.models.routing import RouteDecision
from app.models.call_log import CallLog


async def main():
    assert Path('/data/.reproduction-ui-isolated').read_text().strip()=='reproduction-ui-isolated'
    name='report-'+uuid4().hex[:12];ids=[name+'-'+str(i) for i in range(4)]
    try:
        async with session_factory.begin() as db:
            for i in range(4):
                db.add(RouteDecision(request_id=ids[i],config_id=-1,virtual_model=name,top_k=5,
                    classification=['simple','complex',None,'simple'][i],status=['classified','classified','failed','fallback'][i],
                    elapsed_ms=(i+1)*10,evidence=[]))
            for i,tokens in enumerate((0,1500,None)):
                db.add(CallLog(request_id=ids[i],operation='chat' if i<2 else 'responses',client_ip='127.0.0.1',
                    stream=False,status='success',http_status=200,gateway_latency_ms=20,trace={},
                    logical_model='model-a' if i==0 else 'model-b',upstream_model='fixture',total_tokens=tokens))
            db.add(CallLog(request_id=name+'-embedding-child',operation='embedding',client_ip='127.0.0.1',
                stream=False,status='success',http_status=200,gateway_latency_ms=1,trace={},total_tokens=90000))
        async with httpx.AsyncClient(base_url='http://127.0.0.1',trust_env=False) as c:
            r=await c.post('/api/auth/login',json={'username':'replica-manager','password':'Reproduction!Fixture2026'})
            assert r.status_code==200;h={'Authorization':'Bearer '+r.json()['data']['access_token']}
            r=await c.get('/api/admin/smart-route/statistics',params={'virtual_model':name},headers=h);assert r.status_code==200,r.text
            data=r.json()['data'];summary=data['summary']
            assert summary=={'decisions':4,'real_requests':3,'failures':1,'total_tokens':1500,'average_tokens':750.0,'usage_count':2,'elapsed_ms':100.0},summary
            for rows in data['distributions'].values():
                assert sum(row['decisions'] for row in rows)==4
                assert sum(row['total_tokens'] or 0 for row in rows)==1500
            bands={row['name']:row['decisions'] for row in data['distributions']['tokens']}
            assert bands=={'unknown':2,'0-999':1,'1000-9999':1},bands
            p={'virtual_model':name,'classification':'simple','status':'classified','operation':'chat','selected_model':'model-a'}
            r=await c.get('/api/admin/smart-route/logs',params=p,headers=h);assert r.status_code==200,r.text
            data=r.json()['data'];assert data['total']==1 and data['items'][0]['request_id']==ids[0]
            assert data['items'][0]['total_tokens']==0 and data['items'][0]['selected_model']=='model-a'
            r=await c.get('/api/admin/smart-route/logs',params={'virtual_model':name,'classification':'unclassified'},headers=h)
            assert r.json()['data']['total']==1
            r=await c.get('/api/admin/smart-route/logs',params={'request_id':ids[3]},headers=h)
            assert r.json()['data']['items'][0]['selected_model'] is None
            assert (await c.get('/api/admin/smart-route/logs',params={'classification':'invalid'},headers=h)).status_code==422
            empty=(await c.get('/api/admin/smart-route/statistics',params={'virtual_model':name+'-empty'},headers=h)).json()['data']['summary']
            assert empty['decisions']==0 and empty['total_tokens'] is None and empty['average_tokens'] is None
            assert (await c.get('/api/admin/smart-route/statistics')).status_code==401
    finally:
        if '--keep-fixture' not in sys.argv:
            async with session_factory.begin() as db:
                await db.execute(delete(RouteDecision).where(RouteDecision.virtual_model==name))
                await db.execute(delete(CallLog).where(CallLog.request_id.in_([*ids,name+'-embedding-child'])))
        await engine.dispose()
    print('PASS: six metrics; parent-only tokens; zero versus missing usage; three distributions; combined classification/status/operation/model filters; unmatched histories; empty period; invalid filter422; unauthorized401; no upstream calls.')


asyncio.run(main())
