"""Final full-image public Nginx routing check, private disposable volume."""
from pathlib import Path
import subprocess,time,uuid,json,shutil
root=Path('/opt/AIGateway/.deployment').resolve();name='helidata-stage20-smoke-'+uuid.uuid4().hex[:8];data=root/name;data.mkdir(mode=0o700)
try:
    subprocess.check_call(['docker','run','-d','--name',name,'--network','none','-v',str(data)+':/data:Z','helidata-ai-gateway:stage20-release'],stdout=subprocess.DEVNULL)
    for _ in range(120):
        if subprocess.run(['docker','exec',name,'python','-c',"import urllib.request;assert urllib.request.urlopen('http://127.0.0.1/health').status==200"],capture_output=True).returncode==0:break
        time.sleep(1)
    else:raise AssertionError('release not ready')
    code="""import urllib.request,json
with urllib.request.urlopen('http://127.0.0.1/openapi.json') as r:
 assert r.headers['Content-Type'].startswith('application/json')
 assert \"script-src 'self'\" in r.headers['Content-Security-Policy']
 schema=json.load(r);assert schema['info']['version']=='0.20.0'
 assert '/api/admin/settings' in schema['paths'] and '/v1/responses' in schema['paths']
with urllib.request.urlopen('http://127.0.0.1/api/public/settings') as r:
 v=json.load(r)['data'];assert 'system_name' in v and 'security' not in v
with urllib.request.urlopen('http://127.0.0.1/health/detail') as r:
 v=json.load(r);assert v['phase']==20 and all(x=='ok' for x in v['checks'].values())
"""
    subprocess.check_call(['docker','exec',name,'python','-c',code])
    print('PASS: final full image Nginx returns real public OpenAPI JSON/version/schema with CSP; public settings allowlist; phase20 and all dependencies healthy',flush=True)
finally:
    if subprocess.run(['docker','inspect',name],capture_output=True).returncode==0:
        subprocess.check_call(['docker','stop','-t','60',name],stdout=subprocess.DEVNULL);subprocess.check_call(['docker','rm',name],stdout=subprocess.DEVNULL)
    assert data.resolve().parent==root and data.name==name
    if data.exists():shutil.rmtree(data)
