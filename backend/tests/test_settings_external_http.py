"""Actual local HTTP responses validate ES bounds and stale configuration handling."""
import asyncio,json,threading,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from app.core.exceptions import APIError
from app.services import external_logs,operations_settings

class ExternalSettingsTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.mode='ok';self.started=threading.Event();self.release=threading.Event();outer=self
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    self.server.encoding=self.headers.get('Accept-Encoding')
    if outer.mode=='delay':outer.started.set();outer.release.wait(5)
    raw=b'x'*(2*1024*1024) if outer.mode=='large' else b'[]' if outer.mode=='array' else json.dumps({'version':{'number':'9.1.0'}}).encode()
    self.send_response(200);self.send_header('Content-Length',str(len(raw)))
    if outer.mode=='compressed':self.send_header('Content-Encoding','gzip')
    self.end_headers()
    try:self.wfile.write(raw)
    except (BrokenPipeError,ConnectionResetError):pass
  self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=self.server.serve_forever,daemon=True).start()
  self.cfg={'url':f'http://127.0.0.1:{self.server.server_port}','auth_type':'api_key','secret_encrypted':'fixture','enabled':False}
  self.patches=[patch.object(external_logs,'headers',lambda cfg:{}),patch.object(operations_settings,'elasticsearch',dict(self.cfg))]
  for p in self.patches:p.start()
 async def asyncTearDown(self):
  self.release.set();await asyncio.to_thread(self.server.shutdown);self.server.server_close()
  for p in reversed(self.patches):p.stop()
 async def test_version_check_uses_real_http_and_identity_encoding(self):
  self.assertTrue((await external_logs.test_connection())['success'])
  self.assertEqual(self.server.encoding,'identity')
 async def test_large_compressed_and_nonobject_responses_are_rejected(self):
  for mode in ['large','compressed','array']:
   self.mode=mode
   with self.assertRaises(APIError) as caught:await external_logs.request(self.cfg,'GET','/')
   self.assertEqual(caught.exception.detail['code'],'ES_RESPONSE_INVALID')
 async def test_configuration_change_during_real_response_returns_conflict(self):
  self.mode='delay';task=asyncio.create_task(external_logs.test_connection())
  for _ in range(100):
   if self.started.is_set():break
   await asyncio.sleep(.01)
  self.assertTrue(self.started.is_set())
  operations_settings.elasticsearch['url']+='/replacement';self.release.set()
  with self.assertRaises(APIError) as caught:await task
  self.assertEqual(caught.exception.status_code,409)
