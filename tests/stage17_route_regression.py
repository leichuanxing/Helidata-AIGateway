"""Isolated core acceptance orchestration; production volume is never mounted."""
from pathlib import Path
import subprocess,time,uuid,shutil,re,os
root=Path('/opt/AIGateway/.deployment').resolve()
name='helidata-stage17-route-'+uuid.uuid4().hex[:8]
data=root/name;data.mkdir(mode=0o700)
try:
 ui=os.getenv('STAGE16_UI')=='1'
 network=['-p','18081:80'] if ui else ['--network','none']
 subprocess.check_call(['docker','run','-d','--name',name,*network,'-v',str(data)+':/data:Z','helidata-ai-gateway:stage17-candidate'],stdout=subprocess.DEVNULL)
 print('ISOLATED_CONTAINER='+name,flush=True)
 for _ in range(120):
  r=subprocess.run(['docker','exec',name,'python','-c',"import urllib.request; assert urllib.request.urlopen('http://127.0.0.1/health',timeout=5).status==200"],capture_output=True)
  if r.returncode==0:break
  if subprocess.check_output(['docker','inspect','-f','{{.State.Running}}',name],text=True).strip()!='true':
   log=subprocess.check_output(['docker','logs',name],stderr=subprocess.STDOUT,text=True)
   raise AssertionError(re.sub(r'INITIAL ADMIN:.*','INITIAL ADMIN: [REDACTED]',log))
  time.sleep(1)
 else:raise AssertionError('candidate not ready')
 subprocess.check_call(['docker','cp','tests/.',name+':/tmp/'])
 extra=['-e','STAGE16_UI_HOLD=1'] if ui else []
 subprocess.check_call(['docker','exec','-e','PYTHONPATH=/app/backend',*extra,name,'python','/tmp/stage16_core.py'])
except Exception:
 log=subprocess.check_output(['docker','logs',name],stderr=subprocess.STDOUT,text=True)
 for line in log.splitlines():
  if 'Request failed [' in line:print(line)
 raise
finally:
 if subprocess.run(['docker','inspect',name],capture_output=True).returncode==0:
  subprocess.run(['docker','stop','-t','60',name],check=True,stdout=subprocess.DEVNULL)
  subprocess.run(['docker','rm',name],check=True,stdout=subprocess.DEVNULL)
 target=data.resolve();assert target.parent==root and target.name==name
 if target.exists():shutil.rmtree(target)
