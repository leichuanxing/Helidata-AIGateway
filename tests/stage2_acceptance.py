"""Stage2 deployment checks. Run prepare on stage1, then run verify after upgrade."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

NAME = 'helidata-ai-gateway'
BASE = 'http://127.0.0.1:18080'
BASELINE = Path('/opt/AIGateway/.deployment/stage2-baseline.json')


def execute(*args):
    return subprocess.check_output(['docker','exec',NAME,*args], text=True).strip()


def sql(statement):
    return execute('runuser','-u','postgres','--','psql','-d','helidata_gateway','-Atc',statement)


def snapshot():
    text = sql('SELECT id,username,password_hash,role,status,must_change_password,created_at FROM users ORDER BY id')
    return {'users':hashlib.sha256(text.encode()).hexdigest(),
            'config':execute('sha256sum','/data/config/config.yaml').split()[0]}


def health(expect=200):
    try:
        with urllib.request.urlopen(BASE+'/health/detail',timeout=10) as response:
            assert response.status == expect
            return json.load(response)
    except urllib.error.HTTPError as error:
        assert error.code == expect
        return json.load(error)


def ready():
    for _ in range(90):
        try:
            if health()['status'] == 'ok':
                return
        except Exception:
            pass
        time.sleep(1)
    raise AssertionError('Service not ready')


if len(sys.argv)>1 and sys.argv[1]=='prepare':
    BASELINE.parent.mkdir(exist_ok=True)
    BASELINE.write_text(json.dumps(snapshot()))
    BASELINE.chmod(0o600)
    print('PASS: stage1 user/config digests saved before upgrade')
    sys.exit(0)

ready()
assert snapshot() == json.loads(BASELINE.read_text()), 'Existing user/config changed during upgrade'
assert sql('SELECT version_num FROM alembic_version') == '0002'
assert sql('SELECT r.code FROM users u JOIN roles r ON r.id=u.role_id WHERE u.username=\'admin\'') == 'super_admin'
assert sql("SELECT COUNT(*) FROM pg_tables WHERE schemaname='public' AND tablename IN ('users','roles','user_groups','system_settings','audit_logs')") == '5'
assert health()['phase'] == 2
redacted = execute('python','-m','app.services.config_check')
assert json.loads(redacted)['database']['password'] == '**********'
assert json.loads(redacted)['security']['jwt_secret'] == '**********'
print('PASS: stage1 -> stage2 upgrade preserves user and config, all five tables present')

subprocess.check_call(['docker','cp','tests/test_config.py',NAME+':/tmp/test_config.py'])
print(execute('env','PYTHONPATH=/app/backend','python','/tmp/test_config.py'))
subprocess.check_call(['docker','cp','tests/test_migrations.py',NAME+':/tmp/test_migrations.py'])
print(execute('env','PYTHONPATH=/app/backend','python','/tmp/test_migrations.py'))

for service in ('postgresql','redis'):
    execute('supervisorctl','stop',service)
    try:
        assert health(503)['checks'][service] == 'error'
        logs = subprocess.check_output(['docker','logs','--tail','80',NAME],stderr=subprocess.STDOUT,text=True)
        expected = 'PostgreSQL health check failed' if service=='postgresql' else 'Redis health check failed'
        assert expected in logs
        print('PASS: '+service+' outage returns 503 and explicit log')
    finally:
        execute('supervisorctl','start',service)
        ready()

# Preserve the original configuration byte-for-byte after runtime edit verification.
execute('sh','-c','cp /data/config/config.yaml /data/config/stage2-original.yaml && chmod 600 /data/config/stage2-original.yaml')
try:
    execute('python','-c',"from pathlib import Path; import yaml; p=Path('/data/config/config.yaml'); v=yaml.safe_load(p.read_text()); v['server']['port']=8010; v['redis']['port']=6380; v['gateway']['max_concurrency']=123; p.write_text(yaml.safe_dump(v))")
    subprocess.check_call(['docker','restart','-t','60',NAME])
    ready()
    cfg = json.loads(execute('python','-m','app.services.config_check'))
    assert cfg['server']['port']==8010 and cfg['redis']['port']==6380
    assert cfg['gateway']['max_concurrency']==123
    assert '127.0.0.1:8010' in execute('cat','/run/nginx.conf')
    assert 'port 6380' in execute('cat','/run/redis.conf')
    print('PASS: edited config read after restart; API and Redis listener changes work')
finally:
    execute('sh','-c','cp /data/config/stage2-original.yaml /data/config/config.yaml && chmod 640 /data/config/config.yaml && rm /data/config/stage2-original.yaml')
    subprocess.check_call(['docker','restart','-t','60',NAME])
    ready()
assert snapshot() == json.loads(BASELINE.read_text())
print('PASS: original configuration restored; restart retains all baseline data')
print('PASS: all stage2 acceptance checks')
