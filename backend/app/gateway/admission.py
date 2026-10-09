"""FIFO queue and atomic all-four-level admission on a single Redis instance."""
import asyncio
import json
from contextlib import suppress
from time import monotonic
from redis.exceptions import RedisError
from app.core.redis import redis_client
from app.core.database import session_factory
from app.core.config import get_settings
from app.core.exceptions import APIError
from app.core.security import now
from app.gateway import authentication,user_validation,group_validation,model_permission
from app.gateway.provider_concurrency import RENEW,TTL,RENEW_SECONDS,key as provider_key

STREAMS='gateway:streaming'
QUEUE='gateway:queue';QUEUE_LEASES='gateway:queue:leases'
ADMIT="""
local t=redis.call('TIME');local n=tonumber(t[1])+tonumber(t[2])/1000000
local token=ARGV[1];local ttl=tonumber(ARGV[6]);local providers=cjson.decode(ARGV[7])
for _,expired in ipairs(redis.call('ZRANGEBYSCORE',KEYS[5],'-inf',n)) do redis.call('ZREM',KEYS[4],expired) end
redis.call('ZREMRANGEBYSCORE',KEYS[5],'-inf',n)
local room=true
for i=1,3 do
 redis.call('ZREMRANGEBYSCORE',KEYS[i],'-inf',n)
 if redis.call('ZCARD',KEYS[i])>=tonumber(ARGV[i+1]) then room=false end
end
local selected=nil
for _,p in ipairs(providers) do
 redis.call('ZREMRANGEBYSCORE',p.key,'-inf',n)
 if not selected and redis.call('ZCARD',p.key)<p.limit then selected=p end
end
local head=redis.call('ZRANGE',KEYS[4],0,0)[1]
if room and selected and (not head or head==token) then
 for i=1,3 do redis.call('ZADD',KEYS[i],n+ttl,token);redis.call('EXPIRE',KEYS[i],ttl+30) end
 if ARGV[8]=='1' then redis.call('ZADD',KEYS[7],n+ttl,token);redis.call('EXPIRE',KEYS[7],ttl+30) end
 redis.call('ZADD',selected.key,n+ttl,token);redis.call('EXPIRE',selected.key,ttl+30)
 redis.call('ZREM',KEYS[4],token);redis.call('ZREM',KEYS[5],token)
 return {1,selected.id}
end
if not redis.call('ZSCORE',KEYS[4],token) then
 if redis.call('ZCARD',KEYS[4])>=tonumber(ARGV[5]) then return {-1,0} end
 redis.call('ZADD',KEYS[4],redis.call('INCR',KEYS[6]),token)
end
redis.call('ZADD',KEYS[5],n+ttl,token)
redis.call('EXPIRE',KEYS[4],ttl+30);redis.call('EXPIRE',KEYS[5],ttl+30);redis.call('EXPIRE',KEYS[6],ttl+30)
return {0,0}
"""

class Admission:
    def __init__(self,ctx):
        self.ctx=ctx;self.token=ctx.request_id;self.pending=None;self.owned=[];self.task=None;self.waited=0
        self.owner=asyncio.current_task()

    async def refresh(self):
        async with session_factory() as db:
            self.ctx.key,self.ctx.user,self.ctx.group=await authentication.authenticate(self.ctx.request,db)
            user_validation.validate(self.ctx.user);group_validation.validate(self.ctx.group)
            await model_permission.check(db,self.ctx)

    async def take_provider(self,provider_id):
        if self.pending!=provider_id:return None
        self.pending=None;self.owned.remove(provider_key(provider_id))
        return self.token

    async def release_pending(self):
        if self.pending is not None:
            slot=provider_key(self.pending);self.pending=None
            if slot in self.owned:self.owned.remove(slot)
            await redis_client.zrem(slot,self.token)

    async def release(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):await self.task
            self.task=None
        owned,self.owned=self.owned,[];self.pending=None
        async with redis_client.pipeline(transaction=False) as pipe:
            for slot in owned:pipe.zrem(slot,self.token)
            pipe.zrem(QUEUE,self.token);pipe.zrem(QUEUE_LEASES,self.token)
            await pipe.execute()

    async def renew(self):
        try:
            while True:
                await asyncio.sleep(RENEW_SECONDS)
                # Snapshot: the initial provider slot may be handed to its attempt lease.
                for slot in list(self.owned):
                    if not await redis_client.eval(RENEW,1,slot,self.token,TTL):
                        if slot not in self.owned:continue
                        self.ctx.lease_error='CONCURRENCY_UNAVAILABLE';self.owner.cancel();return
        except RedisError:
            self.ctx.lease_error='CONCURRENCY_UNAVAILABLE';self.owner.cancel()

    async def wait(self,excluded=()):
        from app.gateway.provider_scheduler import ranked
        cfg=get_settings().gateway;start=monotonic();last_refresh=0
        try:
            while True:
                if monotonic()-last_refresh>.25:
                    await self.refresh();last_refresh=monotonic()
                async with session_factory() as db:rows,_=await ranked(self.ctx,db,filter_capacity=False)
                rows=[pair for pair in rows if pair[0].id not in excluded]
                if not rows:raise APIError(503,'NO_AVAILABLE_PROVIDER','没有可用上游账号')
                providers=[];seen=set()
                for mapping,provider in rows:
                    if provider.id in seen:continue
                    seen.add(provider.id)
                    limit=1 if provider.cooldown_until and provider.cooldown_until<=now() else provider.max_concurrency
                    providers.append({'id':provider.id,'key':provider_key(provider.id),'limit':limit})
                slots=['gateway:concurrency',f'group:{self.ctx.group.id}:concurrency',f'apikey:{self.ctx.key.id}:concurrency' if self.ctx.key else f'webchat:{self.ctx.user.id}:concurrency']
                from app.services.group_access import concurrency_limits
                group_limit,key_limit=concurrency_limits(self.ctx.group,cfg.max_concurrency)
                result=await redis_client.eval(ADMIT,7,*slots,QUEUE,QUEUE_LEASES,'gateway:queue:seq',STREAMS,self.token,
                    cfg.max_concurrency,group_limit,key_limit,cfg.queue_size,TTL,json.dumps(providers),int(bool(self.ctx.payload and self.ctx.payload.get('stream'))))
                if result[0]==1:
                    self.pending=int(result[1]);self.owned=slots+[provider_key(self.pending)]+([STREAMS] if self.ctx.payload and self.ctx.payload.get('stream') else [])
                    self.task=asyncio.create_task(self.renew());return
                if result[0]==-1:raise APIError(429,'QUEUE_FULL','等待队列已满')
                if self.waited+monotonic()-start>=cfg.queue_timeout:raise APIError(429,'QUEUE_TIMEOUT','等待并发名额超时')
                # The request body was parsed before admission. Read only disconnect notifications.
                try:
                    message=await asyncio.wait_for(self.ctx.request.receive(),.05)
                    if message['type']=='http.disconnect':raise APIError(499,'CLIENT_DISCONNECTED','客户端已断开')
                except TimeoutError:pass
        except RedisError:raise APIError(503,'CONCURRENCY_UNAVAILABLE','并发状态暂不可用') from None
        finally:self.waited+=monotonic()-start

    async def readmit(self,excluded):
        await self.release();await self.wait(excluded)
