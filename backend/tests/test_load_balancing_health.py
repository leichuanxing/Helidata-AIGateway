"""Persistent circuit transitions and half-open leases against isolated services."""
import asyncio,os,unittest
from types import SimpleNamespace
from uuid import uuid4
from time import monotonic
from unittest.mock import patch
from sqlalchemy import delete,select
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from sqlalchemy.pool import NullPool
from redis.asyncio import Redis
from app.core.config import get_settings
from app.models.user import Provider,ProviderModelMapping,LogicalModel
from app.services.model_catalog import eligible_query
from app.gateway import provider_health,provider_concurrency
from app.core.exceptions import APIError

@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','disposable container only')
class CircuitRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_cooling_exclusion_single_probe_and_successful_rejoin(self):
        ident=os.environ.get('AUDIT_CONTAINER_ID','')
        self.assertGreaterEqual(len(ident),12);self.assertEqual(os.environ.get('HOSTNAME','')[:12],ident[:12])
        cfg=get_settings();engine=create_async_engine(cfg.database.url(),poolclass=NullPool,connect_args={'ssl':False})
        factory=async_sessionmaker(engine,expire_on_commit=False)
        redis=Redis(host=cfg.redis.host,port=cfg.redis.port,decode_responses=True)
        provider_id=None
        model='circuit-'+uuid4().hex
        try:
            async with factory.begin() as db:
                row=Provider(name='circuit-'+uuid4().hex,provider_type='custom_openai',protocol='openai',base_url='http://127.0.0.1:1/v1',max_concurrency=5)
                db.add(row);await db.flush();provider_id=row.id
                db.add(LogicalModel(name=model,model_type='text'));await db.flush()
                db.add(ProviderModelMapping(provider_id=row.id,logical_model=model,upstream_model='fixture',model_type='text'))
            ctx=SimpleNamespace(provider=row,adapter=SimpleNamespace(http_status=503),operation='chat',attempt_started=monotonic(),request_id='circuit-test',admission=None)
            settings=SimpleNamespace(gateway=SimpleNamespace(failure_threshold=1,cooldown_seconds=1))
            with patch.object(provider_health,'session_factory',factory),patch.object(provider_health,'get_settings',lambda:settings),patch.object(provider_concurrency,'redis_client',redis):
                await provider_health.finish(ctx,'failure','UPSTREAM_TIMEOUT')
                async with factory() as db:
                    cooling=await db.get(Provider,provider_id)
                    self.assertEqual(provider_health.state(cooling),'Cooling')
                    self.assertEqual((await db.execute(eligible_query().where(Provider.id==provider_id))).all(),[])
                await asyncio.sleep(1.1)
                async with factory() as db:
                    ready=await db.get(Provider,provider_id)
                    self.assertIsNotNone(ready.cooldown_until)
                    self.assertEqual(len((await db.execute(eligible_query().where(Provider.id==provider_id))).all()),1)
                # A recovered endpoint is allowed a single inference probe even though max=5.
                ctx.provider=ready
                async with provider_concurrency.acquire(ctx):
                    with self.assertRaises(APIError) as busy:
                        async with provider_concurrency.acquire(ctx):pass
                    self.assertEqual(busy.exception.detail['code'],'PROVIDER_BUSY')
                self.assertEqual(await redis.zcard(provider_concurrency.key(provider_id)),0)
                ctx.adapter.http_status=200
                await provider_health.finish(ctx,'success')
                async with factory() as db:
                    recovered=await db.get(Provider,provider_id)
                    self.assertEqual(recovered.health_status,'healthy');self.assertEqual(recovered.failure_count,0)
                    self.assertIsNone(recovered.cooldown_until)
        finally:
            if provider_id:
                await redis.delete(provider_concurrency.key(provider_id))
                async with factory.begin() as db:
                    await db.execute(delete(ProviderModelMapping).where(ProviderModelMapping.provider_id==provider_id))
                    await db.execute(delete(LogicalModel).where(LogicalModel.name==model))
                    await db.execute(delete(Provider).where(Provider.id==provider_id))
            await redis.aclose();await engine.dispose()
