"""Linux host script regressions using a fake Docker CLI; no real containers."""
import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MOCK=r'''import json,os,sys
from pathlib import Path
p=Path(os.environ['MOCK_DOCKER_STATE']);s=json.loads(p.read_text());a=sys.argv[1:]
s.setdefault('calls',[]).append(a)
def finish(code=0,value=''):
 p.write_text(json.dumps(s))
 if value:print(value)
 sys.exit(code)
if a==['info']:finish(0 if s.get('daemon',True) else 1)
if a[:2]==['container','inspect']:
 if not s.get('exists',True):finish(1)
 if '--format' not in a:finish(value='[]')
 f=a[a.index('--format')+1]
 if f=='{{.State.Status}}':finish(value=s.get('status','running'))
 if '.Mounts' in f:finish(value=s.get('source',os.environ['APP_DATA_DIR']))
 if 'PortBindings' in f:finish(value=s.get('port','18080'))
 finish(2)
if a[:2]==['image','inspect']:finish(0 if s.get('image_available',True) else 1)
if a[0]=='run':s['exists']=True;s['status']='running';finish(value='fixture-container')
if a[0]=='start':s['status']='running';finish(value=a[1])
if a[0]=='stop':s['status']='exited';finish(value=a[-1])
if a[0]=='exec':finish(0 if s.get('ready',True) else 1)
finish(2)
'''

@unittest.skipUnless(sys.platform.startswith('linux'),'Linux Bash host scripts')
class ApplicationScriptsTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='aigateway-script-test-');self.addCleanup(self.temp.cleanup)
  base=Path(self.temp.name);self.state=base/'state.json';self.data=base/'data with space'
  docker=base/'docker';docker.write_text('#!'+sys.executable+'\n'+MOCK);docker.chmod(0o755)
  self.env={**os.environ,'PATH':str(base)+os.pathsep+os.environ['PATH'],'MOCK_DOCKER_STATE':str(self.state),'APP_DATA_DIR':str(self.data),'APP_CONTAINER_NAME':'helidata-ai-gateway','APP_PORT':'18080','APP_START_TIMEOUT':'2','APP_STOP_TIMEOUT':'90'}
 def run_script(self,name,state=None,**env):
  self.state.write_text(json.dumps(state or {}));return subprocess.run(['bash',str(ROOT/name)],env={**self.env,**env},cwd='/',capture_output=True,text=True,timeout=15)
 def calls(self):return json.loads(self.state.read_text())['calls']
 def test_existing_running_only_checks_health(self):
  r=self.run_script('start.sh');self.assertEqual(r.returncode,0,r.stderr)
  self.assertFalse(any(a[0] in ('run','start','stop') for a in self.calls()));self.assertIn('已就绪',r.stdout)
 def test_existing_stopped_is_started(self):
  r=self.run_script('start.sh',{'status':'exited'});self.assertEqual(r.returncode,0,r.stderr)
  self.assertIn(['start','helidata-ai-gateway'],self.calls())
 def test_first_start_uses_local_image_and_preserves_spaces(self):
  r=self.run_script('start.sh',{'exists':False});self.assertEqual(r.returncode,0,r.stderr)
  run=next(a for a in self.calls() if a[0]=='run');self.assertIn(str(self.data)+':/data:Z',run);self.assertEqual(run[-1],'helidata-ai-gateway:v1.0.1');self.assertIn('unless-stopped',run)
 def test_missing_image_does_not_create_container(self):
  r=self.run_script('start.sh',{'exists':False,'image_available':False});self.assertNotEqual(r.returncode,0);self.assertFalse(self.data.exists());self.assertFalse(any(a[0]=='run' for a in self.calls()))
 def test_mount_and_port_mismatch_block_changes(self):
  for name in ('start.sh','stop.sh'):
   for state in ({'source':'/unrelated/data'},{'port':'18081'}):
    with self.subTest(name=name,state=state):
     r=self.run_script(name,state);self.assertNotEqual(r.returncode,0);self.assertFalse(any(a[0] in ('start','stop','run') for a in self.calls()))
 def test_stop_retains_container_and_uses_timeout(self):
  r=self.run_script('stop.sh');self.assertEqual(r.returncode,0,r.stderr);self.assertIn(['stop','--time','90','helidata-ai-gateway'],self.calls());self.assertEqual(json.loads(self.state.read_text())['status'],'exited')
 def test_repeated_stop_and_missing_container_are_noops(self):
  for state in ({'status':'exited'},{'exists':False}):
   r=self.run_script('stop.sh',state);self.assertEqual(r.returncode,0,r.stderr);self.assertFalse(any(a[0] in ('stop','rm') for a in self.calls()))
 def test_unavailable_daemon_and_invalid_parameters(self):
  r=self.run_script('start.sh',{'daemon':False});self.assertNotEqual(r.returncode,0);self.assertEqual(self.calls(),[['info']])
  for env in ({'APP_PORT':'0'},{'APP_PORT':'65536'},{'APP_CONTAINER_NAME':'bad/name'},{'APP_STOP_TIMEOUT':'0'},{'APP_DATA_DIR':'/'}):
   with self.subTest(env=env):self.assertNotEqual(self.run_script('stop.sh',**env).returncode,0)
 def test_unready_health_returns_failure(self):
  r=self.run_script('start.sh',{'ready':False},APP_START_TIMEOUT='1');self.assertNotEqual(r.returncode,0);self.assertIn('超时',r.stderr)
 def test_paused_state_is_not_changed(self):
  for name in ('start.sh','stop.sh'):
   r=self.run_script(name,{'status':'paused'});self.assertNotEqual(r.returncode,0);self.assertFalse(any(a[0] in ('start','stop','run') for a in self.calls()))
