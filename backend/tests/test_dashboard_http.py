"""Read real dashboard periods through isolated Nginx and verify response invariants."""
import os,unittest
from pathlib import Path
from datetime import datetime
import httpx

@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','disposable container only')
class DashboardHTTPTests(unittest.IsolatedAsyncioTestCase):
 async def test_periods_permissions_and_resource_metrics(self):
  ident=os.environ.get('AUDIT_CONTAINER_ID','');self.assertGreaterEqual(len(ident),12);self.assertEqual(os.environ.get('HOSTNAME','')[:12],ident[:12])
  async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=30) as client:
   self.assertEqual((await client.get('/api/admin/dashboard')).status_code,401)
   r=await client.post('/api/auth/login',json={'username':'admin','password':Path('/data/config/audit-password.txt').read_text().strip()});self.assertEqual(r.status_code,200)
   client.headers['Authorization']='Bearer '+r.json()['data']['access_token']
   for period in ('1h','24h','7d','30d'):
    r=await client.get('/api/admin/dashboard',params={'period':period});self.assertEqual(r.status_code,200,r.text[:200]);d=r.json()['data']
    self.assertEqual(d['period'],period);self.assertEqual(d['summary']['requests'],sum(row['requests'] for row in d['series']))
    self.assertEqual(d['summary']['failure'],sum(row['failure'] for row in d['series']))
    self.assertEqual(d['summary']['requests'],d['summary']['success']+d['summary']['failure'])
    self.assertEqual(sum(row['requests'] for row in d['rankings']['provider']),d['summary']['requests'])
    self.assertTrue(d['live']['available']);self.assertGreaterEqual(d['live']['active'],d['live']['streaming'])
    self.assertEqual(datetime.fromisoformat(d['today_start']).hour,0)
    for p in d['providers']:
     self.assertIn('last_latency_ms',p);self.assertGreaterEqual(p['requests'],p['failure'])
    if period=='1h':self.assertEqual(d['concurrency_grain'],'minute')
   self.assertEqual((await client.get('/api/admin/dashboard',params={'period':'invalid'})).status_code,422)
