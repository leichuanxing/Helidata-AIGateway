"""Ascending priority with real DB catalog and Redis capacity/sticky state."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from uuid import uuid4
from sqlalchemy import delete
from app.core.database import session_factory,engine
from app.core.redis import redis_client
from app.models.user import Provider,ProviderModelMapping,LogicalModel
from app.services.model_catalog import candidates
from app.gateway import provider_scheduler as scheduler,provider_concurrency


async def main():
    assert Path('/data/.reproduction-ui-isolated').read_text().strip()=='reproduction-ui-isolated'
    name='priority-'+uuid4().hex[:12];ids=[]
    ctx=SimpleNamespace(key=SimpleNamespace(id=-int(uuid4().hex[:8],16)),client_ip='127.0.0.1',logical_model=name)
    try:
        async with session_factory.begin() as db:
            db.add(LogicalModel(name=name,model_type='text'));await db.flush()
            for i,priority in enumerate((30,10,20)):
                p=Provider(name=f'{name}-{i}',provider_type='custom_openai',protocol='openai',base_url='http://127.0.0.1:9/v1',priority=priority,max_concurrency=1)
                db.add(p);await db.flush();ids.append(p.id)
                db.add(ProviderModelMapping(provider_id=p.id,logical_model=name,upstream_model=name,model_type='text'))
        async with session_factory() as db:
            pairs=list(await candidates(db,name));assert [p.priority for m,p in pairs]==[10,20,30]
            with patch.object(scheduler.model_selection,'routes',AsyncMock(side_effect=lambda *a:([(name,list(pairs))],False))):
                rows,_=await scheduler.ranked(ctx,db);assert [p.priority for m,p in rows]==[10,20,30]
                await redis_client.set(scheduler.sticky_key(ctx),str(ids[0]),ex=60)
                rows,_=await scheduler.ranked(ctx,db);assert rows[0][1].id==ids[0]
                await redis_client.delete(scheduler.sticky_key(ctx))
                low=pairs[0][1]
                lease=SimpleNamespace(provider=low)
                async with provider_concurrency.acquire(lease):
                    rows,_=await scheduler.ranked(ctx,db);assert low.id not in [p.id for m,p in rows]
                    rows,_=await scheduler.ranked(ctx,db,False);assert rows[0][1].id==low.id
                    for m,p in pairs:p.priority=10
                    rows,_=await scheduler.ranked(ctx,db,False);assert rows[-1][1].id==low.id
                assert all(n==0 for n in (await provider_concurrency.loads([p for m,p in pairs])).values())
        print('PASS: low-number-first DB catalog and scheduling; sticky affinity; full-account exclusion; equal-priority least load; slots released; no inference.')
    finally:
        await redis_client.delete(scheduler.sticky_key(ctx))
        if ids:
            await redis_client.delete(*[provider_concurrency.key(i) for i in ids])
            async with session_factory.begin() as db:
                await db.execute(delete(ProviderModelMapping).where(ProviderModelMapping.provider_id.in_(ids)))
                await db.execute(delete(Provider).where(Provider.id.in_(ids)))
                await db.execute(delete(LogicalModel).where(LogicalModel.name==name))
        await engine.dispose();await redis_client.aclose()


asyncio.run(main())
