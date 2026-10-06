"""Pinned reproduction deployment with private cold backup and exact rollback.

Run only on the authorized host after isolated acceptance. No credential output.
The default is a read-only inspection. --deploy performs the reviewed upgrade.
"""
from pathlib import Path
import argparse,subprocess,json,hashlib,time,os,urllib.request
parser=argparse.ArgumentParser();parser.add_argument('--deploy',action='store_true');args=parser.parse_args()
root=Path('/opt/AIGateway').resolve();data=root/'data';work=root/'.deployment'
name='helidata-ai-gateway';expected='sha256:c0c485786bcc56cfe8874f689be93cd5cb9be7c543bee3dcf40a5f1ec4451204'
release='sha256:80d0db38273dcac09b6ba2c2a8338c053c111b5dfc0e12429f193be1ca21dcd7'
def run(*a):return subprocess.check_output(list(a),text=True).strip()
def sql(q):return run('docker','exec',name,'runuser','-u','postgres','--','psql','-v','ON_ERROR_STOP=1','-d','helidata_gateway','-Atc',q)
def protected():
    migrated=sql('SELECT version_num FROM alembic_version')=='0022'
    result={}
    tables=('users','user_groups','api_keys','providers','logical_models','provider_model_mappings','model_groups','user_group_model_groups','model_group_models','route_configs','route_samples','route_vectors','sensitive_words','review_samples','review_vectors','compliance_policies')
    for table in tables:
        rows=sql('SELECT to_jsonb(t)::text FROM '+table+' t')
        normalized=[]
        for line in rows.splitlines():
            row=json.loads(line)
            for key in ('updated_at','last_login_at','last_used_at','last_test_at','last_http_status','last_error_code','last_latency_ms','health_status','failure_count','cooldown_until'):row.pop(key,None)
            if migrated:
                if table=='user_groups':
                    if row['is_default']:
                        assert row['model_access']=='selected' and row['status']=='enabled' and row['max_concurrency']==0 and row['key_max_concurrency']==0
                        continue
                    assert row['model_access']=='selected'
                    row.pop('is_default');row.pop('model_access')
                if table=='users':assert row.pop('remark')==''
                if table=='model_groups':row.pop('protocol_type')
                if table=='providers':row['priority']=100000-row['priority'];row['config_version']-=1
                if table=='route_samples':
                    assert row.pop('similarity_threshold') is None
                    assert row.pop('remark')=='' and row.pop('vector_requested') is True
            normalized.append(json.dumps(row,sort_keys=True))
        result[table]=hashlib.sha256('\n'.join(sorted(normalized)).encode()).hexdigest()
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
assert data.is_dir() and not data.is_symlink() and data.resolve()==root/'data'
assert current['Image']==expected,'production image changed; re-inspect before deployment'
assert any(m['Source']==str(data) and m['Destination']=='/data' for m in current['Mounts'])
assert current['HostConfig']['PortBindings']['80/tcp'][0]['HostPort']=='18080'
assert run('docker','image','inspect','--format','{{.Id}}',release)==release
assert sql('SELECT version_num FROM alembic_version')=='0017'
assert sql("SELECT count(*) FROM providers WHERE id=117 AND status='enabled' AND deleted_at IS NULL")=='1'
before=protected();print('PASS read-only preflight: pinned0017 production; /data and18080; Provider117 retained; pinned0022 candidate image',flush=True)
if not args.deploy:raise SystemExit(0)
stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime());backup=work/('reproduction0022-before-'+stamp);backup.mkdir(mode=0o700)
previous=name+'-before-reproduction0022-'+stamp;renamed=False;started=False;cold=False
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
    manifest={'old_image':expected,'new_image':release,'migration_before':'0017','migration_after':'0022','data_tar_sha256':digest,'protected_before':before,'backup_contains_secrets':True}
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2));os.chmod(backup/'manifest.json',0o600)
    run('docker','rename',name,previous);renamed=True
    run('docker','run','-d','--name',name,'-p','18080:80','-v',str(data)+':/data:Z','--restart','unless-stopped',release);started=True
    health();assert sql('SELECT version_num FROM alembic_version')=='0022';assert sql('SELECT count(*) FROM user_groups WHERE is_default')=='1';assert protected()==before,'protected credentials/business configuration changed'
    assert sql("SELECT count(*) FROM users WHERE username LIKE 'isolated-%'")=='0'
    assert sql("SELECT count(*) FROM providers WHERE id=117 AND status='enabled' AND deleted_at IS NULL")=='1'
    assert sql("SELECT extversion FROM pg_extension WHERE extname='vector'")=='0.8.7'
    with urllib.request.urlopen('http://127.0.0.1:18080/openapi.json') as r:assert json.load(r)['info']['version']=='0.20.0'
    with urllib.request.urlopen('http://127.0.0.1:18080/api/public/settings') as r:
        assert "script-src 'self'" in r.headers['Content-Security-Policy'];assert 'data' in json.load(r)
    statuses=run('docker','exec',name,'supervisorctl','status');assert len(statuses.splitlines())==4 and all('RUNNING' in line for line in statuses.splitlines())
    manifest['protected_after']=protected();manifest['result']='success';(backup/'manifest.json').write_text(json.dumps(manifest,indent=2));os.chmod(backup/'manifest.json',0o600)
    print('PASS deployed:0.20.0/0022; normalized protected snapshots identical; Provider117 unchanged; four processes, health, pgvector, CSP and public settings verified',flush=True)
    print('PRIVATE_BACKUP='+str(backup));print('PREVIOUS_STOPPED_CONTAINER='+previous)
except Exception:
    if started:
        run('docker','stop','-t','90',name);run('docker','rename',name,name+'-failed-reproduction0022-'+stamp)
    if cold and renamed:
        assert data.resolve()==root/'data' and backup.parent==work
        os.rename(data,backup/'failed-data')
        run('tar','--numeric-owner','-xpf',str(backup/'data.tar'),'-C',str(root))
    if renamed:run('docker','rename',previous,name)
    run('docker','start' if renamed else 'restart',name);health()
    print('ROLLBACK: original service restored'+(' with matching cold data' if cold and renamed else ' before image replacement')+'; inspect private backup for diagnosis',flush=True)
    raise
