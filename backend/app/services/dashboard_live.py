"""Real lease snapshots and bounded minute peaks. Redis gaps remain unknown."""
import asyncio,json,logging
from datetime import datetime,timezone
from app.core.redis import redis_client
from app.gateway.admission import QUEUE,QUEUE_LEASES,STREAMS
HISTORY='dashboard:concurrency:history'
RETENTION=31*86400
LIVE="""
local t=redis.call('TIME');local n=tonumber(t[1])+tonumber(t[2])/1000000
redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',n)
redis.call('ZREMRANGEBYSCORE',KEYS[2],'-inf',n)
for _,token in ipairs(redis.call('ZRANGE',KEYS[2],0,-1)) do
 if not redis.call('ZSCORE',KEYS[1],token) then redis.call('ZREM',KEYS[2],token) end
end
for _,token in ipairs(redis.call('ZRANGEBYSCORE',KEYS[4],'-inf',n)) do redis.call('ZREM',KEYS[3],token) end
redis.call('ZREMRANGEBYSCORE',KEYS[4],'-inf',n)
local result={t[1],redis.call('ZCARD',KEYS[1]),redis.call('ZCARD',KEYS[2]),redis.call('ZCARD',KEYS[3])}
for i=5,#KEYS do
 redis.call('ZREMRANGEBYSCORE',KEYS[i],'-inf',n);table.insert(result,redis.call('ZCARD',KEYS[i]))
end
return result
"""
SAMPLE="""
local t=redis.call('TIME');local n=tonumber(t[1]);local minute=math.floor(n/60)*60
local key=ARGV[1]..minute;local data=cjson.decode(ARGV[2]);local old=redis.call('GET',key)
if old then
 local previous=cjson.decode(old)
 for _,field in ipairs({'active','streaming','queued'}) do data[field]=math.max(data[field],previous[field]) end
 data.samples=previous.samples+1
else data.samples=1 end
data.timestamp=minute;data.last_sample=n
redis.call('SET',key,cjson.encode(data),'EX',ARGV[3]);redis.call('ZADD',KEYS[1],minute,key)
redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',n-tonumber(ARGV[3]));redis.call('EXPIRE',KEYS[1],ARGV[3])
return minute
"""

async def snapshot(slots=()):
    result=await redis_client.eval(LIVE,4+len(slots),'gateway:concurrency',STREAMS,QUEUE,QUEUE_LEASES,*slots)
    return {'timestamp':datetime.fromtimestamp(int(result[0]),timezone.utc),'active':int(result[1]),'streaming':int(result[2]),'queued':int(result[3]),'loads':[int(x) for x in result[4:]]}

async def sample_once():
    data=await snapshot()
    await redis_client.eval(SAMPLE,1,HISTORY,'dashboard:concurrency:minute:',json.dumps({k:data[k] for k in ('active','streaming','queued')}),RETENTION)

async def history(start,end,grain):
    keys=await redis_client.zrangebyscore(HISTORY,start.timestamp()-60,end.timestamp(),start=0,num=44641)
    values=await redis_client.mget(keys) if keys else []
    bins={}
    for raw in values:
        if not raw:continue
        data=json.loads(raw);stamp=data['timestamp']
        if stamp+60<=start.timestamp() or stamp>=end.timestamp():continue
        bucket=int(stamp//60*60) if grain=='minute' else int(stamp//3600*3600) if grain=='hour' else int((stamp+28800)//86400*86400-28800)
        previous=bins.setdefault(bucket,{'bucket':datetime.fromtimestamp(bucket,timezone.utc),'active':0,'streaming':0,'queued':0,'samples':0})
        for field in ('active','streaming','queued'):previous[field]=max(previous[field],data[field])
        previous['samples']+=data['samples']
    step=60 if grain=='minute' else 3600 if grain=='hour' else 86400
    offset=28800 if grain=='day' else 0
    cursor=int((start.timestamp()+offset)//step*step-offset)
    while cursor<end.timestamp():
        bins.setdefault(cursor,{'bucket':datetime.fromtimestamp(cursor,timezone.utc),'active':None,'streaming':None,'queued':None,'samples':0})
        cursor+=step
    return [bins[k] for k in sorted(bins)]

async def sample_loop():
    while True:
        try:await sample_once()
        except Exception:logging.getLogger(__name__).warning('Dashboard concurrency sample unavailable')
        await asyncio.sleep(10)
