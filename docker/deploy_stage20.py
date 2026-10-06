"""Pinned final deployment with private cold backup and exact rollback.

Run only on the authorized host after isolated acceptance. No credential output.
The default is a read-only inspection. --deploy performs the reviewed upgrade.
"""
from pathlib import Path
import argparse,subprocess,json,hashlib,time,os,urllib.request
parser=argparse.ArgumentParser();parser.add_argument('--deploy',action='store_true');args=parser.parse_args()
root=Path('/opt/AIGateway').resolve();data=root/'data';work=root/'.deployment'
name='helidata-ai-gateway';expected='sha256:63810483a3e2da0ef6045d35aff996545eeef52217a9af21651535fe020905c6'
release='sha256:c0c485786bcc56cfe8874f689be93cd5cb9be7c543bee3dcf40a5f1ec4451204'
def run(*a):return subprocess.check_output(list(a),text=True).strip()
def sql(q):return run('docker','exec',name,'runuser','-u','postgres','--','psql','-v','ON_ERROR_STOP=1','-d','helidata_gateway','-Atc',q)
def protected():
    result={}
    tables=('users','user_groups','api_keys','providers','logical_models','provider_model_mappings','model_groups','user_group_model_groups','model_group_models')
    # Ignore only operational timestamps/health; retain all authentication and business fields.
    ignored="ARRAY['updated_at','last_login_at','last_used_at','last_test_at','last_http_status','last_error_code','last_latency_ms','health_status','failure_count','cooldown_until']"
    for table in tables:
        rows=sql('SELECT (to_jsonb(t)-'+ignored+')::text FROM '+table+' t ORDER BY (to_jsonb(t)-'+ignored+')::text')
        result[table]=hashlib.sha256(rows.encode()).hexdigest()
    result['settings']=hashlib.sha256(sql("SELECT row_to_json(t)::text FROM system_settings t WHERE key<>'operations' ORDER BY key").encode()).hexdigest()
    for file in ('config.yaml','provider-encryption.key'):
        result[file]=run('docker','exec',name,'sha256sum','/data/config/'+file).split()[0]
    return result
def health():
    for _ in range(120):
        try:
            with urllib.request.urlopen('http://127.0.0.1:18080/health',timeout=5) as r:
                if r.status==200:return
        except Exception:pass
        time.sleep(1)
    raise RuntimeError('release not ready')
current=json.loads(run('docker','inspect',name))[0]
assert current['Image']==expected,'production image changed; re-inspect before deployment'
assert any(m['Source']==str(data) and m['Destination']=='/data' for m in current['Mounts'])
assert current['HostConfig']['PortBindings']['80/tcp'][0]['HostPort']=='18080'
assert run('docker','image','inspect','--format','{{.Id}}','helidata-ai-gateway:stage20-release')==release
assert sql('SELECT version_num FROM alembic_version')=='0014'
assert sql("SELECT count(*) FROM providers WHERE id=117 AND status='enabled' AND deleted_at IS NULL")=='1'
before=protected();print('PASS read-only preflight: pinned0014 production; /data and18080; Provider117 retained; pinned0017 final image',flush=True)
if not args.deploy:raise SystemExit(0)
stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime());backup=work/('stage20-before-'+stamp);backup.mkdir(mode=0o700)
previous=name+'-before-stage20-'+stamp;renamed=False;started=False;cold=False
try:
    run('docker','exec',name,'supervisorctl','stop','nginx');run('docker','exec',name,'supervisorctl','stop','uvicorn')
    before=protected()
    dump=backup/'database.dump'
    with dump.open('wb') as f:
        os.chmod(dump,0o600);subprocess.check_call(['docker','exec',name,'runuser','-u','postgres','--','pg_dump','--format=custom','--no-owner','--no-acl','-d','helidata_gateway'],stdout=f);f.flush();os.fsync(f.fileno())
    run('docker','stop','-t','90',name)
    package=backup/'data.tar'
    run('tar','--numeric-owner','-cpf',str(package),'-C',str(root),'data');os.chmod(package,0o600);cold=True
    hasher=hashlib.sha256()
    with package.open('rb') as handle:
        for chunk in iter(lambda:handle.read(1048576),b''):hasher.update(chunk)
    digest=hasher.hexdigest()
    manifest={'old_image':expected,'new_image':release,'migration_before':'0014','migration_after':'0017','data_tar_sha256':digest,'protected_before':before,'backup_contains_secrets':True}
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2));os.chmod(backup/'manifest.json',0o600)
    run('docker','rename',name,previous);renamed=True
    run('docker','run','-d','--name',name,'-p','18080:80','-v',str(data)+':/data:Z','--restart','unless-stopped',release);started=True
    health();assert sql('SELECT version_num FROM alembic_version')=='0017';assert protected()==before,'protected credentials/business configuration changed'
    assert sql("SELECT count(*) FROM users WHERE username LIKE 'isolated-%'")=='0'
    assert sql("SELECT count(*) FROM providers WHERE id=117 AND status='enabled' AND deleted_at IS NULL")=='1'
    assert sql("SELECT extversion FROM pg_extension WHERE extname='vector'")=='0.8.7'
    with urllib.request.urlopen('http://127.0.0.1:18080/openapi.json') as r:assert json.load(r)['info']['version']=='0.20.0'
    with urllib.request.urlopen('http://127.0.0.1:18080/api/public/settings') as r:
        assert "script-src 'self'" in r.headers['Content-Security-Policy'];assert 'data' in json.load(r)
    statuses=run('docker','exec',name,'supervisorctl','status');assert len(statuses.splitlines())==4 and all('RUNNING' in line for line in statuses.splitlines())
    manifest['protected_after']=protected();manifest['result']='success';(backup/'manifest.json').write_text(json.dumps(manifest,indent=2));os.chmod(backup/'manifest.json',0o600)
    print('PASS deployed:0.20.0/0017; all protected snapshots identical; Provider117 unchanged; four processes, health, pgvector, CSP and public settings verified',flush=True)
    print('PRIVATE_BACKUP='+str(backup));print('PREVIOUS_STOPPED_CONTAINER='+previous)
except Exception:
    if started:
        run('docker','stop','-t','90',name);run('docker','rename',name,name+'-failed-stage20-'+stamp)
    if cold and renamed:
        assert data.resolve()==root/'data' and backup.parent==work
        os.rename(data,backup/'failed-data')
        run('tar','--numeric-owner','-xpf',str(backup/'data.tar'),'-C',str(root))
    if renamed:run('docker','rename',previous,name)
    run('docker','start',name);health()
    print('ROLLBACK: original service restored'+(' with matching cold data' if cold and renamed else ' before image replacement')+'; inspect private backup for diagnosis',flush=True)
    raise
