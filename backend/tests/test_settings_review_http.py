"""Full settings and actual backup/restore in an explicitly disposable container."""
import asyncio,hashlib,io,json,os,subprocess,tarfile,tempfile,threading,unittest
from pathlib import Path
from uuid import uuid4
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import httpx

@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','disposable container only')
class SettingsReviewHTTPTests(unittest.IsolatedAsyncioTestCase):
 async def test_save_linkage_status_backup_and_isolated_restore(self):
  ident=os.environ.get('AUDIT_CONTAINER_ID','');self.assertGreaterEqual(len(ident),12);self.assertEqual(os.environ.get('HOSTNAME','')[:12],ident[:12])
  from sqlalchemy import select,update
  from app.models.routing import RouteConfig
  from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
  from sqlalchemy.pool import NullPool
  from app.core.database import connect_database,settings
  from app.models.user import SystemSetting
  from app.services.operations_settings import document
  engine=create_async_engine(settings.url(),poolclass=NullPool,async_creator=lambda:connect_database(settings));self.addAsyncCleanup(engine.dispose)
  factory=async_sessionmaker(engine,expire_on_commit=False)
  async with factory() as db:original=json.loads(json.dumps(await document(db,private=True)))
  async with factory() as db:route_vectors=[(r.id,r.embedding_model,r.vector_generation) for r in (await db.scalars(select(RouteConfig))).all()]
  seen=[]
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    seen.append(self.headers.get('Authorization'));raw=json.dumps({'version':{'number':'9.1.0'}}).encode()
    self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
   def do_POST(self):
    self.rfile.read(int(self.headers['Content-Length']));raw=json.dumps({'object':'list','data':[{'object':'embedding','index':0,'embedding':[1.,0.]}],'usage':{'prompt_tokens':1,'total_tokens':1}}).encode()
    self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
  prefix='settings-'+uuid4().hex[:9];upload=Path('/data/uploads')/(prefix+'.txt');upload.parent.mkdir(parents=True,exist_ok=True);upload.write_text('isolated settings backup fixture')
  self.addCleanup(upload.unlink,missing_ok=True)
  async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=40) as client:
   login=await client.post('/api/auth/login',json={'username':'admin','password':Path('/data/config/audit-password.txt').read_text().strip()});self.assertEqual(login.status_code,200)
   client.headers['Authorization']='Bearer '+login.json()['data']['access_token'];client.headers['X-CSRF-Token']=client.cookies.get('hd_csrf','')
   async def api(method,path,body=None,status=200):
    r=await client.request(method,'/api/'+path,json=body);self.assertEqual(r.status_code,status,(path,r.text[:200]));return r.json().get('data')
   current=await api('GET','admin/settings?include_assets=false')
   async def save(section,values):
    nonlocal current
    current=await api('PATCH','admin/settings?include_assets=false',{'revision':current['revision'],section:values});return current
   provider=None
   try:
    await api('PATCH','admin/settings',{'revision':current['revision']},422)
    await api('PATCH','admin/settings',{'revision':current['revision'],'gateway':{'max_concurrency':True}},422)
    await api('PATCH','admin/settings',{'revision':current['revision'],'basic':{'public_api_base_url':'https://example.com'}},422)
    before=current['revision'];await save('gateway',{'queue_timeout':31})
    self.assertEqual(current['gateway']['queue_timeout'],31);self.assertEqual(current['basic']['system_name'],original['basic']['system_name'])
    await api('PATCH','admin/settings',{'revision':before,'gateway':{'queue_timeout':32}},409)
    png='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='
    await save('basic',{'system_name':prefix,'timezone':'UTC','logo':png,'public_api_base_url':'https://gateway.example/v1'})
    public=await api('GET','public/settings');self.assertEqual(public['system_name'],prefix);self.assertNotIn('data:image',json.dumps(public))
    asset=await client.get(public['logo']);self.assertEqual(asset.status_code,200)
    self.assertEqual((await client.get(public['logo'],headers={'If-None-Match':asset.headers['etag']})).status_code,304)
    await save('logging',{'retention_days':90,'save_request_body':False,'redaction_rules':['fixture_secret']})
    await save('governance',{'smart_route_enabled':False,'semantic_threshold':.9})
    self.assertFalse(current['governance']['smart_route_enabled'])
    provider=await api('POST','admin/providers',{'name':prefix,'provider_type':'custom_openai','protocol':'openai','protocol_type':'vector','base_url':f'http://127.0.0.1:{server.server_port}/v1','api_key':'fixture-only','protocol_config':{'openai-embeddings':{}},'model_mappings':[{'logical_model':prefix,'upstream_model':'embedding','model_type':'embedding'}]},201)
    options=await api('GET','admin/settings/vector-options');self.assertTrue(any(o['provider_id']==provider['id'] for o in options))
    await save('vector',{'provider_id':provider['id'],'model':prefix})
    await api('POST','admin/settings/vector-test',{'revision':current['revision'],'consent':False},422)
    tested=await api('POST','admin/settings/vector-test',{'revision':current['revision'],'consent':True});self.assertEqual(tested['dimensions'],2)
    await api('POST','admin/settings/vector-test',{'revision':current['revision']-1,'consent':True},409)
    await save('elasticsearch',{'enabled':False,'url':f'http://127.0.0.1:{server.server_port}','secret':'fixture-only'})
    self.assertTrue(current['elasticsearch']['secret_configured']);self.assertEqual(current['elasticsearch']['secret'],'')
    self.assertTrue((await api('POST','admin/settings/elasticsearch/test'))['success']);self.assertEqual(seen[-1],'ApiKey fixture-only')
    await api('PATCH','admin/settings',{'revision':current['revision'],'elasticsearch':{'url':f'http://127.0.0.1:{server.server_port}/changed'}},400)
    self.assertIn('queue_count',await api('GET','admin/settings/elasticsearch/status'))
    status=await api('GET','admin/settings/system-status');self.assertGreaterEqual(len(status['components']),5);self.assertIn('container_used_bytes',status['memory'])
    backup=await api('POST','admin/backups',status=202)
    await api('POST','admin/backups',status=409)
    for _ in range(120):
     backups=await api('GET','admin/backups');item=next(r for r in backups['items'] if r['id']==backup['id'])
     if item['status'] not in ('queued','running'):break
     await asyncio.sleep(.25)
    self.assertEqual(item['status'],'ready',item)
    response=await client.get('/api/admin/backups/'+item['id']+'/download');self.assertEqual(response.status_code,200)
    self.assertEqual(hashlib.sha256(response.content).hexdigest(),item['sha256']);self.assertEqual(response.headers['cache-control'],'no-store')
    with tarfile.open(fileobj=io.BytesIO(response.content),mode='r:gz') as tar:
     names=tar.getnames();self.assertTrue({'manifest.json','database.dump','config/config.yaml','config/provider-encryption.key','uploads/'+upload.name}.issubset(names))
     self.assertTrue(all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in names))
     self.assertEqual(tar.extractfile('uploads/'+upload.name).read(),upload.read_bytes())
     self.assertTrue(hashlib.sha256(tar.extractfile('config/provider-encryption.key').read()).digest()==hashlib.sha256(Path('/data/config/provider-encryption.key').read_bytes()).digest())
     with tempfile.TemporaryDirectory(prefix='settings-restore-') as folder:
      dump=Path(folder)/'database.dump';dump.write_bytes(tar.extractfile('database.dump').read());os.chmod(folder,0o755);dump.chmod(0o644)
      scratch='settings_restore_'+uuid4().hex
      def command(*args):return subprocess.run(['runuser','-u','postgres','--',*args],check=True,capture_output=True)
      command('createdb',scratch)
      try:
       command('pg_restore','--no-owner','--no-acl','-d',scratch,str(dump))
       count=command('psql','-d',scratch,'-Atc',"SELECT count(*) FROM system_settings WHERE key='operations'").stdout.strip();self.assertEqual(count,b'1')
      finally:command('dropdb',scratch)
    audit=await api('GET','admin/audit-logs?action=download_backup&resource_id='+item['id']);self.assertGreaterEqual(audit['total'],1)
    await api('GET','admin/audit-logs?start=2026-10-22T00:00:00',status=422)
   finally:
    # Restore only this guarded disposable container, including encrypted config.
    async with factory.begin() as db:
     (await db.get(SystemSetting,'operations')).value=original
     for rid,model,generation in route_vectors:await db.execute(update(RouteConfig).where(RouteConfig.id==rid).values(embedding_model=model,vector_generation=generation))
    latest=await api('GET','admin/settings?include_assets=false')
    await api('PATCH','admin/settings?include_assets=false',{'revision':latest['revision'],'basic':{'system_name':original['basic']['system_name']}})
    if provider:await api('DELETE','admin/providers/'+str(provider['id']))
    await api('POST','auth/logout',{})
  print('PASS settings actual HTTP/SQL/Redis: section saves, revision, assets, vector, ES, status, backup hash and scratch PostgreSQL restore')
