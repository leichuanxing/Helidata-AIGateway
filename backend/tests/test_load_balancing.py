"""Real Redis admission tests. Never run against production Redis."""
import asyncio,json,os,unittest
from uuid import uuid4
from app.gateway.admission import ADMIT
from app.gateway.load_balancing import retry_allowed
from app.gateway.upstream_errors import translate
from app.providers.base import ProviderFailure
from app.schemas.models import ModelGroupInput
from pydantic import ValidationError


class BalancingValidationTests(unittest.TestCase):
    def test_policy_validation(self):
        for strategy in ('legacy','round_robin','weighted_round_robin','least_concurrency'):
            self.assertEqual(ModelGroupInput(name='group',balancing_strategy=strategy,node_weights={'1':100}).balancing_strategy,strategy)
        for values in ({'max_retries':8},{'attempt_timeout':0},{'attempt_timeout':3601},{'node_weights':{'01':1}},{'node_weights':{'1':0}},{'node_weights':{'1':101}},{'balancing_strategy':'random'}):
            with self.assertRaises(ValidationError):ModelGroupInput(name='group',**values)

    def test_uncertain_generations_not_replayed_by_default(self):
        for code in ('UPSTREAM_TIMEOUT','UPSTREAM_NETWORK_ERROR','UPSTREAM_HTTP_ERROR','UPSTREAM_INVALID_RESPONSE','UPSTREAM_STREAM_INTERRUPTED'):
            error=translate(ProviderFailure(code))
            self.assertFalse(retry_allowed(error,{}))
            self.assertTrue(retry_allowed(error,{'retry_uncertain':True}))
        self.assertTrue(retry_allowed(translate(ProviderFailure('UPSTREAM_NETWORK_ERROR',safe_to_retry=True)),{}))
        self.assertTrue(retry_allowed(translate(ProviderFailure('UPSTREAM_HTTP_ERROR',429)),{}))
        self.assertTrue(retry_allowed(translate(ProviderFailure('UPSTREAM_AUTH_FAILED',401)),{}))


@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','isolated container only')
class AtomicBalancingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        ident=os.environ.get('AUDIT_CONTAINER_ID','')
        self.assertGreaterEqual(len(ident),12)
        self.assertEqual(os.environ.get('HOSTNAME','')[:12],ident[:12])
        from redis.asyncio import Redis
        from app.core.config import get_settings
        self.redis=Redis(host='127.0.0.1',port=get_settings().redis.port,decode_responses=True)
        self.prefix='test:lb:'+uuid4().hex
        self.slots=[self.prefix+':'+str(i) for i in range(7)]

    async def asyncTearDown(self):
        keys=[k async for k in self.redis.scan_iter(match=self.prefix+'*')]
        if keys:await self.redis.delete(*keys)
        await self.redis.aclose()

    def providers(self,strategy,weights=(1,1),limit=100):
        return [{'id':i+1,'key':self.prefix+':provider:'+str(i+1),'limit':limit,
            'pool':'model:0:0','strategy':strategy,'weight':w,'state':self.prefix+':state'} for i,w in enumerate(weights)]

    async def admit(self,providers,token=None,global_limit=100):
        token=token or uuid4().hex
        result=await self.redis.eval(ADMIT,7,*self.slots,token,global_limit,global_limit,global_limit,1000,90,json.dumps(providers),0)
        return token,result

    async def release(self,token,providers):
        for key in self.slots[:3]+[p['key'] for p in providers]:await self.redis.zrem(key,token)

    async def test_round_robin_sequential_and_no_queued_counter_consumption(self):
        providers=self.providers('round_robin')
        chosen=[]
        for _ in range(20):
            token,result=await self.admit(providers);self.assertEqual(result[0],1)
            chosen.append(result[1]);await self.release(token,providers)
        self.assertEqual(chosen,[1,2]*10)
        token,result=await self.admit(providers,global_limit=1)
        before=await self.redis.hgetall(self.prefix+':state')
        queued,result=await self.admit(providers,global_limit=1)
        self.assertEqual(result[0],0)
        self.assertEqual(await self.redis.hgetall(self.prefix+':state'),before)

    async def test_smooth_weighted_round_robin(self):
        providers=self.providers('weighted_round_robin',(1,3))
        chosen=[]
        for _ in range(40):
            token,result=await self.admit(providers);chosen.append(result[1]);await self.release(token,providers)
        self.assertEqual(chosen.count(1),10);self.assertEqual(chosen.count(2),30)

    async def test_least_concurrency_and_priority_pool(self):
        providers=self.providers('least_concurrency')
        token,first=await self.admit(providers)
        second_token,second=await self.admit(providers)
        self.assertNotEqual(first[1],second[1])
        await self.release(token,providers);await self.release(second_token,providers)
        providers[0]['limit']=1;providers[1]['pool']='model:0:1'
        token,first=await self.admit(providers);self.assertEqual(first[1],1)
        _,second=await self.admit(providers);self.assertEqual(second[1],2)

    async def test_atomic_concurrent_capacity_and_recovery(self):
        providers=self.providers('round_robin',(1,),limit=7)
        results=await asyncio.gather(*(self.admit(providers) for _ in range(100)))
        admitted=[t for t,r in results if r[0]==1]
        self.assertEqual(len(admitted),7)
        self.assertEqual(await self.redis.zcard(providers[0]['key']),7)
        await asyncio.gather(*(self.release(t,providers) for t in admitted))
        self.assertEqual(await self.redis.zcard(providers[0]['key']),0)
        queued=next(t for t,r in results if r[0]==0)
        _,retry=await self.admit(providers,queued);self.assertEqual(retry[0],1)

    async def test_expired_slots_and_pool_failover(self):
        providers=self.providers('round_robin')
        await self.redis.zadd(providers[0]['key'],{'expired':1})
        _,result=await self.admit(providers);self.assertEqual(result[0],1)
        self.assertIsNone(await self.redis.zscore(providers[0]['key'],'expired'))
