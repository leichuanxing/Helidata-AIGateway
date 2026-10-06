"""Host-side first boot acceptance, including restrictive host volume permissions."""
from pathlib import Path
import re
import subprocess
import time
import uuid

NAME='helidata-stage3-startup'
DATA=Path('/opt/AIGateway/.deployment')/('stage3-startup-'+uuid.uuid4().hex[:8])
DATA.mkdir(mode=0o700)
subprocess.check_call(['docker','run','-d','--name',NAME,'--network','none','-v',str(DATA)+':/data:Z','helidata-ai-gateway:stage3'])
try:
    for _ in range(90):
        result=subprocess.run(['docker','exec',NAME,'python','-c',"import urllib.request; assert urllib.request.urlopen('http://127.0.0.1/health',timeout=5).status==200"],capture_output=True)
        if result.returncode==0:
            break
        if subprocess.check_output(['docker','inspect','-f','{{.State.Running}}',NAME],text=True).strip()!='true':
            log=subprocess.check_output(['docker','logs',NAME],stderr=subprocess.STDOUT,text=True)
            raise AssertionError(re.sub(r'INITIAL ADMIN:.*','INITIAL ADMIN: [REDACTED]',log))
        time.sleep(1)
    else:
        raise AssertionError('Fresh container not ready')
    log=subprocess.check_output(['docker','logs',NAME],stderr=subprocess.DEVNULL,text=True)
    password=re.search(r'INITIAL ADMIN: admin / (\S+)',log).group(1)
    code="""import sys,httpx
password=sys.stdin.read()
c=httpx.Client(base_url='http://127.0.0.1')
r=c.post('/api/auth/login',json={'username':'admin','password':password})
assert r.status_code==200
v=r.json()['data']
assert v['user']['must_change_password'] and v['user']['role']=='super_admin'
c.headers['Authorization']='Bearer '+v['access_token']
assert c.get('/api/admin/users').status_code==403
print('PASS: random admin password printed once; login succeeds; first change enforced')
"""
    subprocess.run(['docker','exec','-i',NAME,'python','-c',code],input=password,text=True,check=True)
    for path,permission in [('/data','711'),('/data/postgres','700'),('/data/config/config.yaml','640')]:
        assert subprocess.check_output(['docker','exec',NAME,'stat','-c','%a',path],text=True).strip()==permission
    assert subprocess.check_output(['docker','exec',NAME,'runuser','-u','postgres','--','psql','-d','helidata_gateway','-Atc','SELECT version_num FROM alembic_version'],text=True).strip()=='0003'
    print('PASS: mode-0700 host volume initializes all migrations with protected subdirectories')
finally:
    subprocess.run(['docker','stop','-t','60',NAME],check=True)
    subprocess.run(['docker','rm',NAME],check=True)
