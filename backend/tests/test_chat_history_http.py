"""History CRUD/auth/retention against disposable PostgreSQL and real HTTP only."""
import asyncio,json,os,unittest
from pathlib import Path
from uuid import uuid4
import httpx
@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','disposable container only')
class ChatHistoryHTTPTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  identity=os.environ.get('AUDIT_CONTAINER_ID','');self.assertGreaterEqual(len(identity),12);self.assertEqual(os.environ.get('HOSTNAME','')[:12],identity[:12])
  self.admin=httpx.AsyncClient(base_url='http://127.0.0.1',timeout=30)
  r=await self.admin.post('/api/auth/login',json={'username':'admin','password':Path('/data/config/audit-password.txt').read_text().strip()});self.assertEqual(r.status_code,200)
  self.admin.headers['Authorization']='Bearer '+r.json()['data']['access_token']
  self.prefix='history-'+uuid4().hex[:8]
  self.clients=[self.admin]
 async def asyncTearDown(self):
  for client in self.clients:await client.aclose()
 def payload(self,prompt='test'):
  return {'model':'fixture-model','model_type':'multimodal','parameters':{'system':'be helpful','max_tokens':5000},'turns':[{'prompt':prompt,'answer':'stored answer','reasoning':'stored reasoning','status':'done','elapsed':12,'attachments':[{'name':'example.pdf','size':100,'kind':'pdf'}],'images':['https://fixture.invalid/image.png'],'requestId':'req_fixture','usage':{'total_tokens':8}}]}
 async def request(self,method,path,body=None,status=200,client=None):
  r=await (client or self.admin).request(method,'/api/admin/chat-test/history'+path,json=body);self.assertEqual(r.status_code,status,r.text[:300]);return r.json().get('data')
 async def test_crud_validation_owner_isolation_and_no_inference(self):
  from app.core.database import session_factory
  from app.core.security import hash_password
  from app.models.user import User,Role
  from app.models.call_log import CallLog
  from sqlalchemy import select,func
  async with session_factory() as db:
   before=await db.scalar(select(func.count()).select_from(CallLog))
   for role in ('admin','user'):
    name=self.prefix+'-'+role;db.add(User(username=name,name=name,password_hash=await hash_password('HistoryTest26!Aa'),role=role,role_id=await db.scalar(select(Role.id).where(Role.code==role)),status='enabled',must_change_password=False))
   await db.commit()
  other=httpx.AsyncClient(base_url='http://127.0.0.1',timeout=30);normal=httpx.AsyncClient(base_url='http://127.0.0.1',timeout=30);anon=httpx.AsyncClient(base_url='http://127.0.0.1',timeout=30);self.clients.extend([other,normal,anon])
  for client,role in ((other,'admin'),(normal,'user')):
   r=await client.post('/api/auth/login',json={'username':self.prefix+'-'+role,'password':'HistoryTest26!Aa'});self.assertEqual(r.status_code,200);client.headers['Authorization']='Bearer '+r.json()['data']['access_token']
  ident='/'+str(uuid4());body=self.payload(self.prefix)
  await self.request('PUT',ident,body)
  detail=await self.request('GET',ident);self.assertEqual(detail['turns'][0]['answer'],'stored answer');self.assertEqual(detail['parameters']['max_tokens'],5000)
  self.assertEqual((await self.request('GET','?q='+self.prefix))['total'],1)
  await self.request('GET',ident,status=404,client=other);await self.request('PUT',ident,body,status=404,client=other);await self.request('DELETE',ident,status=404,client=other)
  self.assertEqual((await self.request('GET','',client=other))['total'],0)
  for client,status in ((normal,403),(anon,401)):
   for method,path,payload in [('GET','',None),('GET',ident,None),('PUT',ident,body),('DELETE',ident,None)]:await self.request(method,path,payload,status,client)
  for patch in ({'images':['javascript:alert(1)']},{'attachments':[{'name':'file','size':1,'kind':'text','data':'forbidden bytes'}]},{'status':'pending'},{'images':['data:image/png;base64,eA==']}):
   bad={**body,'turns':[{**body['turns'][0],**patch}]};await self.request('PUT',ident,bad,422)
  huge={**body,'turns':[{**body['turns'][0],'answer':'x'*1048576} for _ in range(5)]};await self.request('PUT',ident,huge,422)
  body['turns'][0]['answer']='updated';await self.request('PUT',ident,body);self.assertEqual((await self.request('GET',ident))['turns'][0]['answer'],'updated')
  await self.request('DELETE',ident);await self.request('GET',ident,status=404)
  async with session_factory() as db:self.assertEqual(await db.scalar(select(func.count()).select_from(CallLog)),before,'history must not create inference requests')
 async def test_concurrent_retention_and_pagination(self):
  # All real SQL writes serialize by owner, even across concurrent HTTP requests.
  async def save(index):await self.request('PUT','/'+str(uuid4()),self.payload('retention-'+str(index)))
  for batch in range(0,55,5):await asyncio.gather(*(save(i) for i in range(batch,batch+5)))
  result=await self.request('GET','?page_size=15');self.assertEqual(result['total'],50);self.assertEqual(len(result['items']),15)
  self.assertTrue(all('transcript' not in item and 'turns' not in item for item in result['items']))
  self.assertEqual(len((await self.request('GET','?page=4&page_size=15'))['items']),5)
  self.assertEqual((await self.request('GET','?q=%25'))['total'],0)
