"""Atomic account slots with expiry and renewal for long streams."""
import asyncio
from contextlib import asynccontextmanager, suppress
from uuid import uuid4
from redis.exceptions import RedisError
from app.core.redis import redis_client
from app.core.exceptions import APIError
from app.core.security import now

TTL=90
RENEW_SECONDS=20
ACQUIRE="""
local t=redis.call('TIME'); local n=tonumber(t[1])+tonumber(t[2])/1000000
redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',n)
if redis.call('ZCARD',KEYS[1])>=tonumber(ARGV[2]) then return 0 end
redis.call('ZADD',KEYS[1],n+tonumber(ARGV[3]),ARGV[1])
redis.call('EXPIRE',KEYS[1],tonumber(ARGV[3])+30); return 1
"""
RENEW="""
if not redis.call('ZSCORE',KEYS[1],ARGV[1]) then return 0 end
local t=redis.call('TIME'); local n=tonumber(t[1])+tonumber(t[2])/1000000
redis.call('ZADD',KEYS[1],n+tonumber(ARGV[2]),ARGV[1])
redis.call('EXPIRE',KEYS[1],tonumber(ARGV[2])+30); return 1
"""
LOAD="""
local t=redis.call('TIME'); local n=tonumber(t[1])+tonumber(t[2])/1000000
redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',n); return redis.call('ZCARD',KEYS[1])
"""

def key(provider_id): return f'provider:{provider_id}:concurrency'

async def loads(providers):
    try:
        async with redis_client.pipeline(transaction=False) as pipe:
            for provider in providers: pipe.eval(LOAD,1,key(provider.id))
            values=await pipe.execute()
        return {provider.id:int(value) for provider,value in zip(providers,values)}
    except RedisError:
        raise APIError(503,'SCHEDULER_UNAVAILABLE','调度状态暂不可用') from None

@asynccontextmanager
async def acquire(ctx):
    provider=ctx.provider; token=uuid4().hex; slot=key(provider.id)
    admission=getattr(ctx,'admission',None)
    inherited=await admission.take_provider(provider.id) if admission else None
    if admission and not inherited:await admission.release_pending()
    if inherited:token=inherited
    limit=1 if provider.cooldown_until and provider.cooldown_until<=now() else provider.max_concurrency
    try: admitted=await redis_client.eval(RENEW,1,slot,token,TTL) if inherited else await redis_client.eval(ACQUIRE,1,slot,token,limit,TTL)
    except RedisError: raise APIError(503,'SCHEDULER_UNAVAILABLE','调度状态暂不可用') from None
    if not admitted: raise APIError(503,'PROVIDER_BUSY','账号并发已满')
    owner=asyncio.current_task()
    async def renew():
        try:
            while True:
                await asyncio.sleep(RENEW_SECONDS)
                if not await redis_client.eval(RENEW,1,slot,token,TTL):
                    ctx.provider_lease_lost=True
                    owner.cancel();return
        except RedisError:
            ctx.provider_lease_lost=True
            owner.cancel()
    task=asyncio.create_task(renew())
    try: yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError): await task
        try: await redis_client.zrem(slot,token)
        except RedisError: pass
