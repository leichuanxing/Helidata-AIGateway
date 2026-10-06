import asyncio,json
from pathlib import Path
from app.core.redis import redis_client
from app.core.config import get_settings
async def main():
 for k in ('gateway:concurrency','gateway:streaming','gateway:queue','gateway:queue:leases'):
  n=await redis_client.zcard(k);assert n==0;print(k+'=0')
 g=get_settings().gateway
 for k,v in [('max_concurrency',500),('queue_size',1000),('queue_timeout',30),('stream_idle_timeout',300)]:
  assert getattr(g,k)==v;print(k+'='+str(v))
 print('outbox_pending='+str(len(list(Path('/data/logs/call-log-outbox').glob('*.json')))))
 await redis_client.aclose()
asyncio.run(main())
