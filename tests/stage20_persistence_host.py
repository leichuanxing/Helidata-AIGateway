"""Create business data; restart/delete/recreate the container on its SAME private /data."""
from pathlib import Path
import subprocess,time,uuid,hashlib,shutil,os,re
root=Path('/opt/AIGateway/.deployment').resolve();name='helidata-stage20-persistence-'+uuid.uuid4().hex[:8];data=root/name;data.mkdir(mode=0o700)
image=os.environ.get('STAGE20_IMAGE','helidata-ai-gateway:stage20-candidate')
def run(*args):return subprocess.check_output(list(args),text=True).strip()
def start():
    net=['-p','18081:80'] if os.getenv('STAGE20_UI')=='1' else ['--network','none']
    run('docker','run','-d','--name',name,*net,'-v',str(data)+':/data:Z',image)
    for _ in range(120):
        if subprocess.run(['docker','exec',name,'python','-c',"import urllib.request;assert urllib.request.urlopen('http://127.0.0.1/health',timeout=5).status==200"],capture_output=True).returncode==0:break
        time.sleep(1)
    else:raise AssertionError('candidate not ready')
def stop():run('docker','stop','-t','60',name);run('docker','rm',name)
def sql(q):return run('docker','exec',name,'runuser','-u','postgres','--','psql','-v','ON_ERROR_STOP=1','-d','helidata_gateway','-Atc',q)
def snapshot():
    tables=('users','user_groups','api_keys','providers','logical_models','provider_model_mappings','system_settings','call_logs','usage_hourly','usage_daily')
    values={table:hashlib.sha256(sql('SELECT row_to_json(t)::text FROM '+table+' t ORDER BY '+'row_to_json(t)::text').encode()).hexdigest() for table in tables}
    for path in ('config/config.yaml','config/provider-encryption.key','uploads/stage20-persistence.txt'):
        values[path]=run('docker','exec',name,'sha256sum','/data/'+path).split()[0]
    values['redis']=run('docker','exec',name,'redis-cli','GET','stage20:persistence')
    return values
try:
    start();print('ISOLATED_CONTAINER='+name,flush=True);run('docker','cp','tests/.',name+':/tmp/')
    subprocess.check_call(['docker','exec','-e','PYTHONPATH=/app/backend',name,'python','/tmp/stage20_settings.py'])
    run('docker','exec',name,'python','-c',"from pathlib import Path;Path('/data/uploads/stage20-persistence.txt').write_text('isolated-persistence')")
    run('docker','exec',name,'redis-cli','SET','stage20:persistence','retained')
    time.sleep(3);before=snapshot();assert sql('SELECT version_num FROM alembic_version')=='0017'
    run('docker','restart','-t','60',name)
    for _ in range(120):
        if subprocess.run(['docker','exec',name,'python','-c',"import urllib.request;assert urllib.request.urlopen('http://127.0.0.1/health',timeout=5).status==200"],capture_output=True).returncode==0:break
        time.sleep(1)
    assert snapshot()==before,'Restart changed persistent snapshots'
    print('PASS: restart preserves users/passwords, Providers/encryption, mappings, API Keys, settings/PNG, calls/usage, config/Master Key, Redis and uploads',flush=True)
    stop();start();assert snapshot()==before,'Recreation changed persistent snapshots'
    print('PASS: actual stop/remove/recreate on same /data preserves all snapshots and0017; public branding reloads from database',flush=True)
    check=run('docker','exec',name,'python','-c',"import urllib.request,json;v=json.load(urllib.request.urlopen('http://127.0.0.1/api/public/settings'))['data'];assert v['system_name']=='隔离最终验收' and v['timezone']=='UTC' and v['logo'].startswith('data:image/png;base64,')")
    run('docker','cp','tests/.',name+':/tmp/')
    subprocess.check_call(['docker','exec','-e','PYTHONPATH=/app/backend',name,'python','/tmp/stage19_ui_probe.py'])
    if os.getenv('STAGE20_UI')=='1':
        print('UI_READY: '+name,flush=True)
        for _ in range(1800):
            if (root/'stage20-ui-finish').exists():break
            time.sleep(1)
finally:
    if subprocess.run(['docker','inspect',name],capture_output=True).returncode==0:stop()
    target=data.resolve();assert target.parent==root and target.name==name
    if target.exists():shutil.rmtree(target)
