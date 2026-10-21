import json,threading,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from app.providers.vendor_operations import AliyunProvider
from app.providers.base import ProviderFailure
class AliyunImagesTests(unittest.IsolatedAsyncioTestCase):
 async def test_native_translation_and_no_retry(self):
  calls=[];mode=['ok']
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append((self.path,body,self.headers.get('Authorization')))
    result={'output':{'choices':[{'finish_reason':'stop','message':{'content':[{'image':'https://fixture.invalid/a.png'}]}}]},'usage':{'output_image_count':1},'request_id':'native-fixture'}
    status=200
    if mode[0]=='error':status=500;result={'code':'InternalError'}
    if mode[0]=='invalid':result={'output':{'choices':[]}}
    if mode[0]=='compatible':result={'created':1,'data':[{'url':'https://fixture.invalid/b.png'}]}
    raw=json.dumps(result).encode();self.send_response(status);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   origin=f'http://127.0.0.1:{server.server_port}'
   adapter=AliyunProvider(origin+'/api/v1','fixture-only')
   payload={'model':'qwen-image-3.0-pro','prompt':'dog','n':1,'size':'1024x1024','seed':42}
   result=await adapter.image_generation(payload)
   self.assertEqual(result['data'],[{'url':'https://fixture.invalid/a.png'}]);self.assertEqual(result['usage'],{'output_image_count':1})
   self.assertEqual(calls[0],('/api/v1/services/aigc/multimodal-generation/generation',{'model':'qwen-image-3.0-pro','input':{'messages':[{'role':'user','content':[{'text':'dog'}]}]},'parameters':{'n':1,'seed':42,'size':'1024*1024'}},'Bearer fixture-only'))
   await adapter.image_generation({**payload,'size':'auto'});self.assertNotIn('size',calls[-1][1]['parameters'])
   before=len(calls)
   for patch in ({'n':7},{'n':True},{'response_format':'b64_json'},{'quality':'hd'},{'model':'wan-unknown'},{'size':'bad'}):
    with self.assertRaises(ProviderFailure):await adapter.image_generation({**payload,**patch})
   self.assertEqual(len(calls),before)
   for value in ('error','invalid'):
    mode[0]=value;before=len(calls)
    with self.assertRaises(ProviderFailure):await adapter.image_generation(payload)
    self.assertEqual(len(calls),before+1)
   mode[0]='compatible';legacy=AliyunProvider(origin+'/compatible-mode/v1','fixture-only')
   self.assertEqual((await legacy.image_generation(payload))['created'],1)
   self.assertEqual(calls[-1][0],'/compatible-mode/v1/images/generations');self.assertEqual(calls[-1][1],payload)
  finally:server.shutdown();server.server_close();thread.join(timeout=2)
