"""Host-side isolated first boot + real Stage15 volume upgrade + migration round trip.

Does not stop, alter or mount the production application volume.
"""
from pathlib import Path
import hashlib
import re
import shutil
import subprocess
import time
import uuid

ROOT = Path('/opt/AIGateway/.deployment').resolve()
IDENTITY = uuid.uuid4().hex[:8]
NAME = 'helidata-stage17-migration-' + IDENTITY
DATA = ROOT / ('stage17-migration-' + IDENTITY)
DATA.mkdir(mode=0o700)


def run(*args, **kw):
    return subprocess.check_output(list(args), text=True, **kw).strip()


def sql(query):
    return run('docker', 'exec', NAME, 'runuser', '-u', 'postgres', '--', 'psql', '-v', 'ON_ERROR_STOP=1', '-d', 'helidata_gateway', '-Atc', query)


def start(image):
    run('docker', 'run', '-d', '--name', NAME, '--network', 'none', '-v', str(DATA) + ':/data:Z', image)
    for _ in range(120):
        ready = subprocess.run(['docker', 'exec', NAME, 'python', '-c', "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1/health',timeout=5).status==200"], capture_output=True)
        if ready.returncode == 0:
            return
        if run('docker', 'inspect', '-f', '{{.State.Running}}', NAME) != 'true':
            log = run('docker', 'logs', NAME, stderr=subprocess.STDOUT)
            raise AssertionError(re.sub(r'INITIAL ADMIN:.*', 'INITIAL ADMIN: [REDACTED]', log))
        time.sleep(1)
    raise AssertionError('isolated container not ready')


def stop():
    run('docker', 'stop', '-t', '60', NAME)
    run('docker', 'rm', NAME)


def protected_digest():
    users = sql('SELECT id,username,password_hash,role,status,must_change_password,auth_version FROM users ORDER BY id')
    # Digest only; original password hashes and Master Key never printed.
    key = run('docker', 'exec', NAME, 'sha256sum', '/data/config/provider-encryption.key').split()[0]
    return hashlib.sha256(users.encode()).hexdigest(), key


try:
    start('helidata-ai-gateway:stage16')
    assert sql('SELECT version_num FROM alembic_version') == '0013'
    assert sql("SELECT count(*) FROM pg_extension WHERE extname='vector'") == '1'
    original = protected_digest()
    seed = '''import asyncio
from app.gateway.context import GatewayContext
from app.gateway.call_log import write
from app.core.database import session_factory
from app.models.user import LogicalModel,ModelGroup
from app.models.routing import RouteConfig,RouteSample,RouteDecision
from sqlalchemy import text
async def main():
 for operation in ('chat','responses','messages','embeddings','rerank','images'):
  ctx=GatewayContext('req_route_legacy_'+operation,operation,'legacy-only',{})
  ctx.usage_snapshot={'prompt_tokens':4,'completion_tokens':2,'total_tokens':6}
  await write(ctx,'success')
 async with session_factory.begin() as db:
  db.add_all([LogicalModel(name='migration-legacy-auto',model_type='text'),LogicalModel(name='migration-legacy-embed',model_type='embedding')])
  simple=ModelGroup(name='migration-legacy-simple');complex=ModelGroup(name='migration-legacy-complex');db.add_all([simple,complex]);await db.flush()
  cfg=RouteConfig(virtual_model='migration-legacy-auto',embedding_model='migration-legacy-embed',simple_model_group=simple.id,complex_model_group=complex.id);db.add(cfg);await db.flush()
  sample=RouteSample(config_id=cfg.id,prompt='legacy synthetic sample',prompt_hash='1'*64,classification='simple',vector_status='ready');db.add(sample);await db.flush()
  await db.execute(text("INSERT INTO route_vectors(sample_id,embedding,dimensions,embedding_model,vector_generation,sample_revision) VALUES (:id,'[1,0]',2,'migration-legacy-embed',1,1)"),{'id':sample.id})
  db.add(RouteDecision(request_id='req_migration_legacy_route',config_id=cfg.id,virtual_model=cfg.virtual_model,top_k=5,status='classified',classification='simple',similarity=1,selected_model_group=simple.id,selected_group_name=simple.name,elapsed_ms=1,evidence=[{'sample_id':sample.id,'classification':'simple','similarity':1}]))
asyncio.run(main())'''
    subprocess.run(['docker', 'exec', '-e', 'PYTHONPATH=/app/backend', NAME, 'python', '-c', seed], check=True, stdout=subprocess.DEVNULL)
    legacy = [sql('SELECT row_to_json(t)::text FROM '+table+' t ORDER BY '+key) for table,key in [('route_configs','id'),('route_samples','id'),('route_vectors','sample_id'),('route_decisions','id')]]
    stop()
    start('helidata-ai-gateway:stage17-candidate')
    assert sql('SELECT version_num FROM alembic_version') == '0014'
    assert protected_digest() == original
    assert sql("SELECT extversion FROM pg_extension WHERE extname='vector'") == '0.8.7'
    print('PASS: actual Stage16 volume upgrade installs0014; user credential states and Master Key unchanged')
    subprocess.run(['docker', 'cp', 'tests/stage16_vectors.py', NAME + ':/tmp/stage16_vectors.py'], check=True)
    subprocess.run(['docker', 'cp', 'tests/stage16_inputs.py', NAME + ':/tmp/stage16_inputs.py'], check=True)
    assert [sql('SELECT row_to_json(t)::text FROM '+table+' t ORDER BY '+key) for table,key in [('route_configs','id'),('route_samples','id'),('route_vectors','sample_id'),('route_decisions','id')]] == legacy
    for target in ('0013', 'head', 'head'):
        subprocess.run(['docker', 'exec', NAME, 'alembic', 'downgrade' if target == '0013' else 'upgrade', target], check=True, stdout=subprocess.DEVNULL)
        assert sql('SELECT version_num FROM alembic_version') == ('0013' if target=='0013' else '0014')
        assert sql('SELECT count(*) FROM call_logs') == '6'
        for table in ('usage_hourly', 'usage_daily'):
            assert sql(f'SELECT sum(requests),sum(total_tokens_sum),count(DISTINCT operation) FROM {table}') == '6|36|6'
        assert protected_digest() == original
        assert [sql('SELECT row_to_json(t)::text FROM '+table+' t ORDER BY '+key) for table,key in [('route_configs','id'),('route_samples','id'),('route_vectors','sample_id'),('route_decisions','id')]] == legacy
        assert sql("SELECT extversion FROM pg_extension WHERE extname='vector'") == '0.8.7'
    print('PASS: 0014 downgrade/re-upgrade/idempotency preserves actual Stage16 rules/samples/vectors/decision snapshots, six-operation call/usage facts, credentials and extension')
    subprocess.run(['docker', 'exec', NAME, 'runuser', '-u', 'postgres', '--', 'python', '-m', 'app.services.provision_database'], check=True)
    assert sql('SELECT count(*) FROM route_configs') == '1'
    assert sql('SELECT count(*) FROM route_samples') == '1'
    assert sql('SELECT count(*) FROM route_vectors') == '1'
    assert sql('SELECT count(*) FROM route_decisions') == '1'
    stop()
    resolved = DATA.resolve()
    assert resolved.parent == ROOT and resolved.name == 'stage17-migration-' + IDENTITY
    shutil.rmtree(resolved)
    DATA.mkdir(mode=0o700)
    start('helidata-ai-gateway:stage17-candidate')
    assert sql('SELECT version_num FROM alembic_version') == '0014'
    assert sql("SELECT extversion FROM pg_extension WHERE extname='vector'") == '0.8.7'
    for path, mode in [('/data/config/provider-encryption.key', '640'), ('/data/postgres', '700'), ('/data/logs/call-log-outbox', '700'), ('/data/logs/compliance-outbox', '700')]:
        assert run('docker', 'exec', NAME, 'stat', '-c', '%a', path) == mode
    subprocess.run(['docker', 'exec', NAME, 'runuser', '-u', 'gateway', '--', 'test', '-w', '/data/logs/call-log-outbox'], check=True)
    print('PASS: fresh mode-0700 host volume bootstraps non-superuser DB, protected secrets, pgvector and all migrations')
finally:
    exists = subprocess.run(['docker', 'inspect', NAME], capture_output=True).returncode == 0
    if exists:
        stop()
    resolved = DATA.resolve()
    assert resolved.parent == ROOT and resolved.name == 'stage17-migration-' + IDENTITY
    if resolved.exists():
        shutil.rmtree(resolved)
