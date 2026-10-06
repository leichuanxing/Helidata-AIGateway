#!/usr/bin/env python3
"""Stage 1 acceptance against the deployed single container; run on Linux host."""
import json
import subprocess
import time
import urllib.request

NAME = 'helidata-ai-gateway'
IMAGE = 'helidata-ai-gateway:stage1'
DATA = '/opt/AIGateway/data'
BASE = 'http://127.0.0.1:18080'


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def execute(*args):
    return command('docker', 'exec', NAME, *args)


def wait_ready():
    for _ in range(90):
        try:
            with urllib.request.urlopen(BASE + '/health', timeout=5) as response:
                assert json.load(response) == {'status': 'ok'}
            return
        except Exception:
            time.sleep(1)
    raise AssertionError('Health check did not recover')


def sql(statement):
    return execute('runuser', '-u', 'postgres', '--', 'psql', '-d', 'helidata_gateway', '-Atc', statement)


def snapshot():
    return {
        'users': sql('SELECT id, username, password_hash, must_change_password FROM users ORDER BY id'),
        'migration': sql('SELECT version_num FROM alembic_version'),
        'config': execute('sha256sum', '/data/config/config.yaml').split()[0],
        'redis': execute('redis-cli', 'GET', 'stage1:persistence'),
        'uploads': execute('cat', '/data/uploads/stage1-check.txt'),
    }


wait_ready()
with urllib.request.urlopen(BASE + '/health/detail') as response:
    detail = json.load(response)
    assert all(x == 'ok' for x in detail['checks'].values())
with urllib.request.urlopen(BASE + '/') as response:
    assert '合力数据AI网关' in response.read().decode()
with urllib.request.urlopen(BASE + '/api/health') as response:
    assert json.load(response)['status'] == 'ok'
assert '$argon2id$' in sql("SELECT password_hash FROM users WHERE username='admin'")
assert sql("SELECT must_change_password FROM users WHERE username='admin'") == 't'
assert sql('SELECT COUNT(*) FROM users') == '1'
assert sql('SELECT version_num FROM alembic_version') == '0001'
assert sql('SHOW server_encoding') == 'UTF8'
for directory in ('postgres', 'redis', 'uploads', 'logs', 'backup', 'config'):
    execute('test', '-d', '/data/' + directory)
assert execute('stat', '-c', '%a', '/data/config/config.yaml') == '640'
assert execute('stat', '-c', '%a', '/data/postgres') == '700'
assert '0.0.0.0:18080' in command('docker', 'port', NAME)
assert '5432' not in command('docker', 'port', NAME)
assert '6379' not in command('docker', 'port', NAME)
assert len(execute('supervisorctl', 'status').splitlines()) == 4
execute('redis-cli', 'SET', 'stage1:persistence', 'preserved')
execute('sh', '-c', 'printf preserved > /data/uploads/stage1-check.txt')
before = snapshot()
command('docker', 'restart', '-t', '60', NAME)
wait_ready()
assert snapshot() == before, 'Restart changed persisted data'
print('PASS: container restart preserves PostgreSQL, Redis, config and uploads', flush=True)
command('docker', 'stop', '-t', '60', NAME)
command('docker', 'rm', NAME)
command('docker', 'run', '-d', '--name', NAME, '-p', '18080:80', '-v', DATA + ':/data:Z', '--restart', 'unless-stopped', IMAGE)
wait_ready()
assert snapshot() == before, 'Container recreation changed persisted data'
print('PASS: container recreation preserves PostgreSQL, Redis, config and uploads', flush=True)
for service in ('redis', 'postgresql', 'uvicorn', 'nginx'):
    line = next(x for x in execute('supervisorctl', 'status').splitlines() if x.split()[0] == service)
    old_pid = int(line.split('pid ')[1].split(',')[0])
    execute('sh', '-c', f'kill -9 {old_pid}')
    for _ in range(30):
        try:
            line = next(x for x in execute('supervisorctl', 'status').splitlines() if x.split()[0] == service)
            if 'RUNNING' in line and int(line.split('pid ')[1].split(',')[0]) != old_pid:
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        raise AssertionError(service + ' did not restart')
    wait_ready()
    print('PASS: Supervisor restarts ' + service, flush=True)
assert snapshot() == before
print('PASS: all stage 1 acceptance checks', flush=True)
