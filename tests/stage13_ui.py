"""Disposable actual-HTTP browser verification account and facts."""
import asyncio,json,sys,threading,time
from pathlib import Path
import httpx
from sqlalchemy import select,delete,text
import stage13_acceptance as fixture
seed=fixture.seed
STATE=Path('/opt/AIGateway/.deployment/stage13-ui.json')
PASSWORD='Stage13Check!9842Temporary'

async def setup():
    server=fixture.ThreadingHTTPServer(('127.0.0.1',0),fixture.Fixture);server.daemon_threads=True
    seed.URL='http://127.0.0.1:'+str(server.server_port);threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        await seed.seed()
        async with seed.session_factory.begin() as db:
            role=await db.scalar(select(seed.Role.id).where(seed.Role.code=='admin'));user=await db.get(seed.User,seed.ids['user']);user.role='admin';user.role_id=role;user.password_hash=await seed.hash_password(PASSWORD)
        rids=[]
        async with httpx.AsyncClient(base_url='http://127.0.0.1',headers={'Authorization':'Bearer '+seed.KEY},timeout=20) as client:
            body={'model':seed.NAME,'messages':[{'role':'user','content':'browser acceptance fixture'}]}
            for stream in (False,True):
                response=await client.post('/v1/chat/completions',json={**body,'stream':stream});assert response.status_code==200;rids.append(response.headers['X-Request-ID'])
            await seed.change(seed.Provider,'provider',base_url=seed.URL+'/bad/v1')
            response=await client.post('/v1/chat/completions',json=body);assert response.status_code==400;rids.append(response.headers['X-Request-ID'])
        await asyncio.sleep(.2)
        await seed.change(seed.Provider,'provider',status='disabled')
        payload={'username':seed.PREFIX,'password':PASSWORD,'ids':seed.ids,'model':seed.NAME,'embed':seed.EMBED,'rids':rids}
        target=Path('/tmp/stage13-ui.json');target.write_text(json.dumps(payload));target.chmod(0o600)
        print('PASS: disposable browser admin and actual nonstream/SSE/failure facts prepared; fixture Provider disabled')
    finally:server.shutdown();server.server_close();await seed.engine.dispose()

async def cleanup():
    data=json.loads(Path('/tmp/stage13-ui.json').read_text());ids=data['ids'];assert data['username'].startswith('stage12_')
    async with seed.session_factory.begin() as db:
        await db.execute(delete(seed.User).where(seed.User.id==ids['user'],seed.User.username==data['username']))
        await db.execute(delete(seed.UserGroup).where(seed.UserGroup.id==ids['ug']))
        await db.execute(delete(seed.ModelGroup).where(seed.ModelGroup.id==ids['mg']))
        await db.execute(delete(seed.ProviderModelMapping).where(seed.ProviderModelMapping.provider_id==ids['provider']))
        await db.execute(delete(seed.Provider).where(seed.Provider.id==ids['provider']))
        await db.execute(delete(seed.LogicalModel).where(seed.LogicalModel.name.in_([data['model'],data['embed']])))
        await db.execute(delete(fixture.CallLog).where(fixture.CallLog.request_id.in_(data['rids'])))
        for table in ('usage_hourly','usage_daily'):
            await db.execute(text(f'DELETE FROM {table} WHERE request_model=:model'),{'model':data['model']})
    from app.core.redis import redis_client
    keys=[k async for k in redis_client.scan_iter(match=f'sticky:{ids["key"]}:*')]
    if keys:await redis_client.delete(*keys)
    await redis_client.aclose();await seed.engine.dispose();Path('/tmp/stage13-ui.json').unlink()
    print('PASS: browser test identities, actual call records and aggregate rows removed')

if __name__=='__main__':asyncio.run(cleanup() if len(sys.argv)>1 else setup())
