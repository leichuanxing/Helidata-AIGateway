"""Operation permissions stay unchanged when entry points move into settings."""
import os,unittest
from pathlib import Path
from uuid import uuid4
import httpx
@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','disposable container only')
class SettingsOperationPermissions(unittest.IsolatedAsyncioTestCase):
 async def test_super_admin_admin_and_user_boundaries(self):
  ident=os.environ.get('AUDIT_CONTAINER_ID','');self.assertGreaterEqual(len(ident),12);self.assertEqual(os.environ.get('HOSTNAME','')[:12],ident[:12])
  async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=25) as admin:
   login=await admin.post('/api/auth/login',json={'username':'admin','password':Path('/data/config/audit-password.txt').read_text().strip()});self.assertEqual(login.status_code,200)
   admin.headers['Authorization']='Bearer '+login.json()['data']['access_token']
   for path in ['/api/admin/backups','/api/admin/audit-logs','/api/admin/settings?include_assets=false']:
    self.assertEqual((await admin.get(path)).status_code,200)
   for role in ['admin','user']:
    name='ops-'+role+'-'+uuid4().hex[:8];password='Isolated-Operation26!Aa';new_password='Isolated-Operation26!Bb'
    created=await admin.post('/api/admin/users',json={'username':name,'password':password,'role':role});self.assertEqual(created.status_code,201,created.text[:150])
    async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=25) as client:
     login=await client.post('/api/auth/login',json={'username':name,'password':password});self.assertEqual(login.status_code,200)
     client.headers['Authorization']='Bearer '+login.json()['data']['access_token']
     changed=await client.post('/api/auth/change-password',json={'old_password':password,'new_password':new_password});self.assertEqual(changed.status_code,200)
     login=await client.post('/api/auth/login',json={'username':name,'password':new_password});self.assertEqual(login.status_code,200)
     client.headers['Authorization']='Bearer '+login.json()['data']['access_token']
     self.assertEqual((await client.get('/api/admin/audit-logs')).status_code,200 if role=='admin' else 403)
     for path in ['/api/admin/backups','/api/admin/settings?include_assets=false','/api/admin/settings/system-status']:
      self.assertEqual((await client.get(path)).status_code,403,(role,path))
   async with httpx.AsyncClient(base_url='http://127.0.0.1') as guest:
    for path in ['/api/admin/backups','/api/admin/audit-logs']:
     self.assertEqual((await guest.get(path)).status_code,401)
