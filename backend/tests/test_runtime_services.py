"""Real Redis/SQL checks; enable only against an isolated migrated database."""
import asyncio
import os
import unittest
from types import SimpleNamespace
from uuid import uuid4
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy import select, delete
from redis.asyncio import Redis
from app.core.config import get_settings
from app.gateway import provider_concurrency as capacity
from app.services.gateway_security import RATE_SCRIPT
from app.gateway.context import GatewayContext
from app.gateway import call_log
from app.models.call_log import CallLog
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('RUNTIME_SERVICES_TEST')=='1','isolated real services explicitly enabled')
class RuntimeServicesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cfg=get_settings()
        self.redis=Redis(host=cfg.redis.host,port=cfg.redis.port)
        self.prefix='audit:'+uuid4().hex

    async def asyncTearDown(self):
        keys=[k async for k in self.redis.scan_iter(self.prefix+'*')]
        if keys:await self.redis.delete(*keys)
        await self.redis.aclose()

    async def test_provider_slot_limit_is_atomic_and_expiry_recovers(self):
        key=self.prefix+':slots'
        results=await asyncio.gather(*(self.redis.eval(capacity.ACQUIRE,1,key,str(i),3,90) for i in range(40)))
        self.assertEqual(sum(results),3)
        self.assertEqual(await self.redis.eval(capacity.LOAD,1,key),3)
        winners=[str(i) for i,n in enumerate(results) if n]
        self.assertEqual(await self.redis.eval(capacity.RENEW,1,key,winners[0],90),1)
        self.assertEqual(await self.redis.eval(capacity.RENEW,1,key,'missing',90),0)
        await self.redis.zadd(key,{token:0 for token in winners})
        self.assertEqual(await self.redis.eval(capacity.LOAD,1,key),0)
        self.assertEqual(await self.redis.eval(capacity.ACQUIRE,1,key,'next',3,90),1)

    async def test_cancelled_provider_request_releases_real_redis_lease(self):
        acquired=asyncio.Event()
        ctx=SimpleNamespace(provider=SimpleNamespace(id=999999999,max_concurrency=1,cooldown_until=None),admission=None)
        with patch.object(capacity,'redis_client',self.redis),patch.object(capacity,'key',lambda _:self.prefix+':lease'):
            async def request():
                async with capacity.acquire(ctx):
                    acquired.set();await asyncio.Event().wait()
            task=asyncio.create_task(request());await acquired.wait()
            self.assertEqual(await self.redis.zcard(self.prefix+':lease'),1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(await self.redis.zcard(self.prefix+':lease'),0)

    async def test_rate_counter_is_atomic_and_expires(self):
        key=self.prefix+':rate'
        values=await asyncio.gather(*(self.redis.eval(RATE_SCRIPT,1,key) for _ in range(40)))
        self.assertEqual(sorted(v[0] for v in values),list(range(1,41)))
        self.assertTrue(0<await self.redis.ttl(key)<=60)

    async def test_call_log_replay_is_idempotent_in_postgresql(self):
        engine=create_async_engine(get_settings().database.url(),poolclass=NullPool)
        factory=async_sessionmaker(engine,expire_on_commit=False)
        ctx=GatewayContext('req_'+uuid4().hex,'models')
        record=call_log.snapshot(ctx,'success',None)
        try:
            with patch.object(call_log,'session_factory',factory):
                await asyncio.gather(*(call_log.persist(record) for _ in range(8)))
            async with factory.begin() as db:
                rows=(await db.scalars(select(CallLog).where(CallLog.request_id==ctx.request_id))).all()
                self.assertEqual(len(rows),1)
                await db.execute(delete(CallLog).where(CallLog.request_id==ctx.request_id))
        finally:await engine.dispose()

    async def test_concurrent_quota_reservation_and_duplicate_settlement(self):
        from app.gateway import quota
        from app.models.user import UserGroup
        from app.models.quota import QuotaBucket,QuotaReservation
        from app.core.exceptions import APIError
        engine=create_async_engine(get_settings().database.url(),poolclass=NullPool)
        factory=async_sessionmaker(engine,expire_on_commit=False)
        ident=None
        try:
            async with factory.begin() as db:
                group=UserGroup(name=self.prefix,quota_limit=300,quota_period='permanent')
                db.add(group);await db.flush();ident=group.id
            contexts=[GatewayContext('req_'+uuid4().hex,'chat',payload={'max_tokens':100}) for _ in range(12)]
            for ctx in contexts:ctx.group=group;ctx.adapter=SimpleNamespace(http_status=200)
            with patch.object(quota,'session_factory',factory):
                async def reserve(ctx):
                    try:return await quota.reserve(ctx)
                    except APIError as error:
                        self.assertEqual(error.detail['code'],'QUOTA_EXCEEDED')
                        return None
                reservations=await asyncio.gather(*(reserve(ctx) for ctx in contexts))
                self.assertEqual(sum(r is not None for r in reservations),2)
                for ctx,reservation in zip(contexts,reservations):
                    if reservation:
                        ctx.quota_usage=20
                        await asyncio.gather(*(quota.settle(ctx,*reservation) for _ in range(3)))
                async with factory() as db:
                    bucket=await db.get(QuotaBucket,(ident,'permanent',quota.period_key('permanent')))
                    self.assertEqual(bucket.reserved_budget,0)
                    self.assertEqual(bucket.reported_tokens,40)
        finally:
            if ident:
                async with factory.begin() as db:await db.execute(delete(UserGroup).where(UserGroup.id==ident))
            await engine.dispose()
