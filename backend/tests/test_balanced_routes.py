"""Independent routing validation and real Redis atomic admission checks."""
import asyncio,json,os,unittest
from uuid import uuid4
from pydantic import ValidationError
from app.schemas.balance import RouteInput,matching_type
from app.gateway.admission import ADMIT

class BalancedValidationTests(unittest.TestCase):
    def test_strategies_and_strict_limits(self):
        for strategy in ('round_robin','weighted_round_robin','least_concurrency','random','priority'):
            self.assertEqual(RouteInput(name='route',model_name='unified',strategy=strategy,nodes=[{'mapping_id':1}]).strategy,strategy)
        for extra in ({'max_retries':8},{'max_concurrency':0},{'timeout_seconds':0},{'health_interval':0},{'nodes':[]},{'nodes':[{'mapping_id':1},{'mapping_id':1}]},{'nodes':[{'mapping_id':True}]},{'nodes':[{'mapping_id':1,'weight':0}]},{'strategy':'sticky'}):
            with self.assertRaises(ValidationError):RouteInput(**{'name':'route','model_name':'unified','nodes':[{'mapping_id':1}],**extra})
    def test_model_type_boundaries(self):
        self.assertTrue(matching_type('text','reasoning'));self.assertTrue(matching_type('multimodal','multimodal'))
        self.assertFalse(matching_type('multimodal','text'));self.assertFalse(matching_type('embedding','rerank'))

@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','isolated services only')
class BalancedAtomicTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        ident=os.environ.get('AUDIT_CONTAINER_ID','');self.assertGreaterEqual(len(ident),12);self.assertEqual(os.environ.get('HOSTNAME','')[:12],ident[:12])
        from redis.asyncio import Redis
        from app.core.config import get_settings
        self.redis=Redis(host='127.0.0.1',port=get_settings().redis.port,decode_responses=True)
        self.prefix='balanced-test:'+uuid4().hex;self.slots=[self.prefix+':'+str(i) for i in range(7)]
    async def asyncTearDown(self):
        keys=[k async for k in self.redis.scan_iter(match=self.prefix+'*')]
        if keys:await self.redis.delete(*keys)
        await self.redis.aclose()
    def nodes(self,strategy='round_robin'):
        return [{'id':i+1,'key':self.prefix+':account:'+str(i),'limit':100,'mapping_id':i+101,'node_id':i+11,
            'node_key':self.prefix+':node:'+str(i),'node_limit':100,'route_key':self.prefix+':route','route_limit':100,
            'state':self.prefix+':state','strategy':strategy,'weight':1 if i==0 else 3,'priority':i,'native':0} for i in range(2)]
    async def admit(self,nodes,seed=0,token=None,limit=100):
        token=token or uuid4().hex
        return token,await self.redis.eval(ADMIT,7,*self.slots,token,limit,limit,limit,1000,90,json.dumps(nodes),0,seed)
    async def release(self,token,nodes):
        keys=set(self.slots[:3]+[n['key'] for n in nodes]+[n['node_key'] for n in nodes]+[nodes[0]['route_key']])
        async with self.redis.pipeline(transaction=False) as pipe:
            for key in keys:pipe.zrem(key,token)
            await pipe.execute()
    async def test_round_robin_selects_mapping_not_just_shared_account(self):
        nodes=self.nodes();nodes[1]['id']=nodes[0]['id'];nodes[1]['key']=nodes[0]['key']
        actual=[]
        for _ in range(6):
            token,result=await self.admit(nodes);self.assertEqual(result[0],1);actual.append(result[2]);await self.release(token,nodes)
        self.assertEqual(actual,[101,102]*3)
    async def test_smooth_weighted_round_robin(self):
        nodes=self.nodes('weighted_round_robin');actual=[]
        for _ in range(40):
            token,result=await self.admit(nodes);actual.append(result[3]);await self.release(token,nodes)
        self.assertEqual(actual.count(11),10);self.assertEqual(actual.count(12),30)
    async def test_least_concurrency_random_and_priority(self):
        nodes=self.nodes('least_concurrency');t,a=await self.admit(nodes);u,b=await self.admit(nodes)
        self.assertNotEqual(a[3],b[3]);await self.release(t,nodes);await self.release(u,nodes)
        nodes=self.nodes('random')
        for seed,node in ((0,11),(1,12)):
            t,r=await self.admit(nodes,seed);self.assertEqual(r[3],node);await self.release(t,nodes)
        nodes=self.nodes('priority');nodes[0]['priority']=20
        t,r=await self.admit(nodes);self.assertEqual(r[3],12)
    async def test_route_and_shared_account_capacity_atomic(self):
        nodes=self.nodes()
        for n in nodes:n['route_limit']=3
        result=await asyncio.gather(*(self.admit(nodes) for _ in range(50)))
        admitted=[t for t,r in result if r[0]==1];self.assertEqual(len(admitted),3)
        for token in admitted:await self.release(token,nodes)
        for slot in self.slots:await self.redis.delete(slot)
        nodes=self.nodes()
        for n in nodes:n['key']=nodes[0]['key'];n['limit']=2
        result=await asyncio.gather(*(self.admit(nodes) for _ in range(50)))
        self.assertEqual(sum(r[0]==1 for t,r in result),2)
    async def test_node_capacity_native_preference_and_waiting_does_not_advance(self):
        nodes=self.nodes();nodes[0]['node_limit']=1;nodes[1]['native']=1
        t,a=await self.admit(nodes);self.assertEqual(a[3],11)
        u,b=await self.admit(nodes);self.assertEqual(b[3],12)
        await self.release(t,nodes);await self.release(u,nodes)
        t,r=await self.admit(nodes,limit=1);before=await self.redis.hgetall(self.prefix+':state')
        _,r=await self.admit(nodes,limit=1);self.assertEqual(r[0],0)
        self.assertEqual(await self.redis.hgetall(self.prefix+':state'),before)
