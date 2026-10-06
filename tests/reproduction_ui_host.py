"""Launch or clean up a UI-only isolated preview; production /data is never mounted."""
import argparse,json,subprocess,time,uuid,shutil
from pathlib import Path
root=Path('/opt/AIGateway/.deployment').resolve()
state=root/'reproduction-ui-active.json'
parser=argparse.ArgumentParser();parser.add_argument('--cleanup',action='store_true');args=parser.parse_args()
if args.cleanup:
    info=json.loads(state.read_text());name=info['name'];data=Path(info['data']).resolve()
    assert name.startswith('helidata-reproduction-ui-') and data.parent==root and data.name==name
    subprocess.run(['docker','stop','-t','30',name],check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['docker','rm',name],check=True,stdout=subprocess.DEVNULL)
    shutil.rmtree(data);state.unlink()
    print('PASS: own isolated preview container and data removed.')
else:
    assert not state.exists(),'Existing preview must be reused or cleaned first'
    name='helidata-reproduction-ui-'+uuid.uuid4().hex[:8];data=root/name;data.mkdir(mode=0o700)
    (data/'.reproduction-ui-isolated').write_text('reproduction-ui-isolated')
    state.write_text(json.dumps({'name':name,'data':str(data)}));state.chmod(0o600)
    subprocess.run(['docker','run','-d','--name',name,'-p','18081:80','-v',str(data)+':/data:Z',
                    'helidata-ai-gateway:reproduction-preview'],check=True,stdout=subprocess.DEVNULL)
    for _ in range(120):
        result=subprocess.run(['docker','exec',name,'python','-c',
            "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1/health',timeout=5).status==200"],capture_output=True)
        if result.returncode==0:break
        time.sleep(1)
    else:raise AssertionError('Isolated preview did not become healthy; cleanup with --cleanup')
    subprocess.run(['docker','cp',str(root/'reproduction-ui-candidate/seed.py'),name+':/tmp/seed.py'],check=True)
    subprocess.run(['docker','exec','-e','PYTHONPATH=/app/backend',name,'python','/tmp/seed.py'],check=True)
    print('ISOLATED_PREVIEW='+name,flush=True)
