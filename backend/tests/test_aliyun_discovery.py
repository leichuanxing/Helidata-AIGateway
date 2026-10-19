"""Real loopback HTTP catalog regression; no commercial inference requests."""
import json,threading,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs
from app.providers.vendor_operations import AliyunProvider
from app.providers.base import ProviderFailure

class AliyunDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_pages_and_compatible_catalog(self):
        calls=[];mode=['native']
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                calls.append((self.path,self.headers.get('Authorization')))
                query=parse_qs(urlsplit(self.path).query);page=int(query.get('page_no',['1'])[0])
                if mode[0]=='compatible':body={'data':[{'id':'compatible-model'}]}
                elif mode[0]=='failed':body={'success':False,'output':{'models':[],'total':0}}
                elif mode[0]=='stalled':body={'output':{'models':[{'model':'same'}],'total':2}}
                elif mode[0]=='invalid':body={'output':{'models':[{'name':'missing-id'}],'total':1}}
                elif mode[0]=='oversized':body={'output':{'models':[],'total':10001}}
                else:body={'success':True,'output':{'models':[{'model':'page-'+str(page)}],'total':2,'page_no':page}}
                raw=json.dumps(body).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            origin=f'http://127.0.0.1:{server.server_port}'
            adapter=AliyunProvider(origin+'/api/v1','fixture-only')
            self.assertEqual(await adapter.list_models(),[{'id':'page-1'},{'id':'page-2'}])
            self.assertEqual([path for path,_ in calls],['/api/v1/models?page_no=1&page_size=100','/api/v1/models?page_no=2&page_size=100'])
            self.assertTrue(all(auth=='Bearer fixture-only' for _,auth in calls))
            self.assertEqual(adapter.base_url,origin+'/api/v1')
            for value in ('failed','stalled','invalid','oversized'):
                mode[0]=value
                with self.assertRaises(ProviderFailure):await adapter.list_models()
            mode[0]='compatible'
            self.assertEqual(await adapter.list_models(),[{'id':'compatible-model'}])
            legacy=AliyunProvider(origin+'/compatible-mode/v1','fixture-only')
            self.assertEqual(await legacy.list_models(),[{'id':'compatible-model'}])
            self.assertEqual(calls[-1][0],'/compatible-mode/v1/models')
        finally:server.shutdown();server.server_close();thread.join(timeout=2)
