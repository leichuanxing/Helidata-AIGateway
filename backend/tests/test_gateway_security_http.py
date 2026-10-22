"""Real Nginx/HTTP/Redis security flows; only in an identified offline container."""
import asyncio,hashlib,os,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from uuid import uuid4
import httpx
@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','disposable container only')
class GatewaySecurityHTTPTests(unittest.IsolatedAsyncioTestCase):
 async def test_access_proxies_bindings_rate_login_and_logs(self):
  ident=os.environ.get('AUDIT_CONTAINER_ID','');self.assertGreaterEqual(len(ident),12);self.assertEqual(os.environ.get('HOSTNAME','')[:12],ident[:12])
  from redis.asyncio import Redis
  from app.core.config import get_settings
  redis=Redis(host='127.0.0.1',port=get_settings().redis.port,decode_responses=True)
  self.addAsyncCleanup(redis.aclose)
  async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=25) as admin, httpx.AsyncClient(base_url='http://127.0.0.1',transport=httpx.AsyncHTTPTransport(local_address='127.0.0.2'),timeout=25) as other:
   r=await admin.post('/api/auth/login',json={'username':'admin','password':Path('/data/config/audit-password.txt').read_text().strip()});self.assertEqual(r.status_code,200)
   admin.headers['Authorization']='Bearer '+r.json()['data']['access_token']
   async def api(method,path,body=None,status=200,params=None):
    r=await admin.request(method,'/api/'+path,json=body,params=params);self.assertEqual(r.status_code,status,(method,path,r.text[:200]));return r.json().get('data')
   initial=(await api('GET','admin/gateway-security'))['policy'];state=dict(initial)
   async def save(section,values):
    nonlocal state
    state=(await api('PATCH','admin/gateway-security',{'revision':state['revision'],'section':section,'values':values}))['policy']
   try:
    self.assertFalse(initial['admin_access']['enabled'])
    await api('PATCH','admin/gateway-security',{'revision':state['revision'],'section':'rate','values':{'admin_access':{'enabled':False}}},422)
    await api('PATCH','admin/gateway-security',{'revision':state['revision'],'section':'admin_access','values':{'admin_access':{'enabled':True,'mode':'whitelist','addresses':['192.0.2.0/24']}}},400)
    await api('PUT','admin/gateway-security',{**state,'unknown_security_option':True},422)
    await save('admin_access',{'admin_access':{'enabled':True,'mode':'blacklist','addresses':['127.0.0.2']}})
    for path in ['/admin','/admin/dashboard','/login','/api/admin/gateway-security']:
     self.assertEqual((await other.get(path)).status_code,403,path)
    self.assertEqual((await other.get('/v1/models')).status_code,401)
    await save('admin_access',{'admin_access':{'enabled':True,'mode':'whitelist','addresses':['127.0.0.1']}})
    self.assertEqual((await other.get('/api/auth/login')).status_code,403)
    await save('admin_access',{'admin_access':{'enabled':False}})
    await save('api_access',{'api_access':{'enabled':True,'addresses':['127.0.0.2']}})
    self.assertEqual((await other.get('/v1/models')).status_code,403)
    self.assertEqual((await other.get('/api/admin/gateway-security',headers=dict(admin.headers))).status_code,200)
    await save('api_access',{'api_access':{'enabled':False}})
    await save('global_access',{'global_access':{'enabled':True,'addresses':['127.0.0.2']}})
    self.assertEqual((await other.get('/v1/models')).status_code,403)
    self.assertEqual((await other.get('/api/auth/login')).status_code,403)
    await save('global_access',{'global_access':{'enabled':False}})
    await save('bans',{'bans':[{'address':'::ffff:127.0.0.2/128','reason':'fixture permanent'}]})
    self.assertEqual(state['bans'][0]['address'],'127.0.0.2/32')
    self.assertEqual((await other.get('/v1/models')).json()['error']['code'],'IP_BANNED')
    await save('bans',{'bans':[{'address':'127.0.0.2','expires_at':(datetime.now(timezone.utc)-timedelta(minutes=2)).isoformat()}]})
    self.assertEqual((await other.get('/v1/models')).status_code,401)
    await save('bans',{'bans':[{'address':f'192.0.2.{i}','reason':'pagination fixture'} for i in range(1,26)]})
    self.assertEqual(len((await api('GET','admin/gateway-security'))['policy']['bans']),25)
    await save('bans',{'bans':[]})
    key=await api('POST','portal/api-keys',{'name':'security-'+uuid4().hex[:8]},201)
    headers={'Authorization':'Bearer '+key['secret']}
    await save('api_access',{'key_bindings':[{'key_id':key['key']['id'],'addresses':['::ffff:127.0.0.2/128']}]})
    self.assertEqual((await other.get('/v1/models',headers=headers)).status_code,200)
    self.assertEqual((await admin.get('/v1/models',headers=headers)).status_code,403)
    await save('api_access',{'key_bindings':[{'key_id':key['key']['id'],'addresses':['203.0.113.9']}]})
    forged={**headers,'X-Forwarded-For':'203.0.113.9','X-Real-IP':'203.0.113.9','X-Gateway-Peer-IP':'203.0.113.9'}
    self.assertEqual((await other.get('/v1/models',headers=forged)).status_code,403)
    await save('proxies',{'trusted_proxies':['127.0.0.2']})
    self.assertEqual((await other.get('/v1/models',headers=forged)).status_code,200)
    self.assertEqual((await other.get('/v1/models',headers={**headers,'X-Real-IP':'203.0.113.9'})).status_code,200)
    self.assertEqual((await other.get('/v1/models',headers={**headers,'X-Forwarded-For':'203.0.113.9, 192.0.2.3'})).status_code,403)
    self.assertEqual((await other.get('/v1/models',headers={**headers,'X-Forwarded-For':'invalid'})).status_code,403)
    await api('POST','admin/gateway-security/validate-addresses',{'addresses':['::ffff:0.0.0.0/96'],'purpose':'proxies'},422)
    changed=await other.patch('/api/admin/gateway-security',json={'revision':state['revision'],'section':'proxies','values':{'trusted_proxies':[]}},headers={**dict(admin.headers),'X-Forwarded-For':'203.0.113.9'})
    self.assertEqual(changed.status_code,200,changed.text[:150]);state=changed.json()['data']['policy']
    self.assertEqual(changed.json()['data']['current_ip'],'127.0.0.2')
    await save('api_access',{'key_bindings':[]})
    await save('rate',{'ip_rpm':1})
    self.assertEqual((await other.get('/v1/models')).status_code,401)
    limited=await other.get('/v1/models');self.assertEqual(limited.status_code,429);self.assertGreater(int(limited.headers['retry-after']),0)
    await save('rate',{'ip_rpm':0})
    await save('rate',{'key_rpm':1})
    self.assertEqual((await other.get('/v1/models',headers=headers)).status_code,200)
    self.assertEqual((await other.get('/v1/models',headers=headers)).status_code,429)
    await save('rate',{'key_rpm':0})
    await save('login',{'login_max_attempts':2,'login_lock_seconds':30})
    name='lock-'+uuid4().hex[:8];password='Isolated-Lock26!Aa'
    await api('POST','admin/users',{'username':name,'password':password},201)
    for _ in range(2):self.assertEqual((await other.post('/api/auth/login',json={'username':name,'password':'wrong'})).status_code,401)
    self.assertEqual((await other.post('/api/auth/login',json={'username':name,'password':password})).status_code,429)
    await redis.expire('login:account:'+hashlib.sha256(name.lower().encode()).hexdigest(),1);await asyncio.sleep(1.1)
    self.assertEqual((await other.post('/api/auth/login',json={'username':name,'password':password})).status_code,200)
    logs=(await api('GET','admin/gateway-security/logs',params={'ip':'::ffff:127.0.0.2'}))
    self.assertGreater(logs['total'],0);self.assertTrue(all(x['ip']=='127.0.0.2' for x in logs['items']))
    for event in ['IP_BANNED','BLACKLIST_HIT','WHITELIST_REJECTED','API_KEY_IP_MISMATCH','RATE_LIMITED','LOGIN_FAILED','ACCOUNT_LOCKED']:
     result=await api('GET','admin/gateway-security/logs',params={'event':event});self.assertGreater(result['total'],0,event)
     self.assertTrue(all(x['event']==event for x in result['items']))
    item=logs['items'][0];end=datetime.fromisoformat(item['created_at']);bounded=await api('GET','admin/gateway-security/logs',params={'ip':'127.0.0.2','start':(end-timedelta(days=1)).isoformat(),'end':end.isoformat()})
    self.assertNotIn(item['id'],[x['id'] for x in bounded['items']])
    await api('GET','admin/gateway-security/logs',status=422,params={'ip':'invalid'})
    await api('PATCH','admin/gateway-security',{'revision':0,'section':'rate','values':{'ip_rpm':0}},409)
    detail=await api('GET','admin/gateway-security/logs/'+str(item['id']));self.assertEqual(detail['id'],item['id'])
    print('PASS security real Nginx/HTTP/Redis: access scopes, mapped CIDR, bans, binding, trusted chain, forged headers, IP/Key RPM, login lock/recovery, logs and lockout guard')
   finally:
    limited_keys=[k async for k in redis.scan_iter(match='gateway:security:rpm:*')]
    if limited_keys:await redis.delete(*limited_keys)
    await api('PUT','admin/gateway-security',{**initial,'revision':state['revision']})
