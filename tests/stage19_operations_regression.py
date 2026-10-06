"""Real isolated HTTP, PostgreSQL dump/restore, file permissions and audit history."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
import httpx
from sqlalchemy import select, text
from app.core.database import session_factory, engine
from app.core.security import hash_password
from app.models.user import User, Role, Provider, AuditLog
from app.models.backup import Backup
from app.services.provider_crypto import encrypt_secret, read_key
from app.services.backups import DIRECTORY

PASSWORD = 'Stage18!Isolated84925'


async def main():
    async with session_factory.begin() as db:
        roles = dict((code, ident) for ident, code in (await db.execute(select(Role.id, Role.code))).all())
        actors = []
        for role in ('super_admin', 'admin', 'user'):
            row = User(username='isolated-ops-'+role, role=role, role_id=roles[role],
                       password_hash=await hash_password(PASSWORD), must_change_password=False)
            db.add(row); actors.append(row)
        provider = Provider(name='backup-encrypted-provider', provider_type='custom_openai', protocol='openai',
            base_url='http://127.0.0.1:9/v1', api_key_encrypted=encrypt_secret('isolated-backup-secret'), status='disabled')
        db.add(provider)
    Path('/data/uploads/nested').mkdir()
    Path('/data/uploads/nested/example.txt').write_text('isolated-upload-恢复验证', encoding='utf-8')
    async with httpx.AsyncClient(base_url='http://127.0.0.1', timeout=30) as client:
        def check(response, status=200):
            assert response.status_code == status, (response.status_code, response.text[:300])
            return response.json().get('data')
        headers = []
        for actor in actors:
            login = check(await client.post('/api/auth/login', json={'username': actor.username, 'password': PASSWORD}))
            headers.append({'Authorization': 'Bearer '+login['access_token']})
        super_headers, admin_headers, normal_headers = headers
        check(await client.get('/api/admin/backups'), 401)
        for header in (admin_headers, normal_headers):
            check(await client.get('/api/admin/backups', headers=header), 403)
            check(await client.post('/api/admin/backups', headers=header), 403)
        check(await client.get('/api/admin/audit-logs', headers=normal_headers), 403)
        check(await client.get('/api/admin/audit-logs', headers=admin_headers))
        check(await client.get('/api/admin/audit-logs?start=2026-01-01T00:00:00&end=2026-01-02T00:00:00', headers=super_headers), 422)
        check(await client.delete('/api/admin/audit-logs/1', headers=super_headers), 405)
        print('PASS 1: backup super-admin restriction, administrator audit read, bounded timezone filters, no audit deletion', flush=True)
        # Pause only this disposable worker to deterministically test overlapping jobs.
        subprocess.run(['supervisorctl', 'stop', 'uvicorn'], check=True, stdout=subprocess.DEVNULL)
        async with session_factory.begin() as db:
            db.add(Backup(id='00000000-0000-0000-0000-000000000018', status='queued', actor_id=actors[0].id))
        try:
            async with session_factory.begin() as db:
                db.add(Backup(id='00000000-0000-0000-0000-000000000019', status='running', actor_id=actors[0].id))
        except Exception as exc:
            from sqlalchemy.exc import IntegrityError
            assert isinstance(exc, IntegrityError)
        else: raise AssertionError('queued and running were both allowed')
        async with session_factory.begin() as db:
            row = await db.get(Backup, '00000000-0000-0000-0000-000000000018'); row.status = 'running'
        orphan = DIRECTORY/'work-isolated-interrupted'; orphan.mkdir(mode=0o700)
        (orphan/'database.dump').write_bytes(b'isolated incomplete dump')
        import pwd
        service_user = pwd.getpwnam('gateway')
        for path in (orphan, orphan/'database.dump'):
            os.chown(path, service_user.pw_uid, service_user.pw_gid)
        subprocess.run(['supervisorctl', 'start', 'uvicorn'], check=True, stdout=subprocess.DEVNULL)
        for _ in range(100):
            async with session_factory() as db:
                row = await db.get(Backup, '00000000-0000-0000-0000-000000000018')
                if row.status == 'failed': break
            await asyncio.sleep(.2)
        assert row.error_code == 'BACKUP_INTERRUPTED'
        assert not orphan.exists()
        print('PASS 2: single active job enforced across queued/running states; interrupted worker records failure and removes its abandoned private work directory', flush=True)
        created = check(await client.post('/api/admin/backups', headers=super_headers), 202)
        ident = created['id']
        for _ in range(150):
            items = check(await client.get('/api/admin/backups', headers=super_headers))['items']
            row = next(r for r in items if r['id'] == ident)
            if row['status'] in ('ready', 'failed'): break
            await asyncio.sleep(.2)
        assert row['status'] == 'ready', row
        package = DIRECTORY/(ident+'.tar.gz')
        assert package.stat().st_mode & 0o777 == 0o600
        assert DIRECTORY.stat().st_mode & 0o777 == 0o700
        downloaded = await client.get('/api/admin/backups/'+ident+'/download', headers=super_headers)
        assert downloaded.status_code == 200
        assert hashlib.sha256(downloaded.content).hexdigest() == row['sha256']
        assert len(downloaded.content) == row['size_bytes']
        check(await client.get('/api/admin/backups/'+ident+'/download', headers=admin_headers), 403)
        check(await client.get('/api/admin/backups/invalid/download', headers=super_headers), 422)
        print('PASS 3: real pg_dump+config+Master Key+uploads archive; SHA256/size verified; 700 directory/600 file; protected download', flush=True)
        with tempfile.TemporaryDirectory() as directory:
            with tarfile.open(package) as tar:
                names = tar.getnames()
                assert set(names) == {'manifest.json', 'database.dump', 'config/config.yaml',
                                      'config/provider-encryption.key', 'uploads/nested/example.txt'}
                assert all(m.isfile() and m.mode == 0o600 for m in tar.getmembers())
                assert tar.extractfile('config/provider-encryption.key').read() == read_key()
                assert tar.extractfile('config/config.yaml').read() == Path('/data/config/config.yaml').read_bytes()
                assert tar.extractfile('uploads/nested/example.txt').read() == Path('/data/uploads/nested/example.txt').read_bytes()
                manifest = json.load(tar.extractfile('manifest.json')); assert manifest['contains_secrets'] is True
                dump = Path(directory)/'database.dump'; dump.write_bytes(tar.extractfile('database.dump').read()); os.chmod(dump, 0o644)
            os.chmod(directory, 0o755)
            subprocess.run(['runuser', '-u', 'postgres', '--', 'createdb', 'stage18_restore'], check=True)
            try:
                subprocess.run(['runuser', '-u', 'postgres', '--', 'pg_restore', '--no-owner', '--no-acl',
                                '--exit-on-error', '-d', 'stage18_restore', str(dump)], check=True, capture_output=True)
                def sql(query):
                    return subprocess.check_output(['runuser','-u','postgres','--','psql','-d','stage18_restore','-Atc',query], text=True).strip()
                assert sql('SELECT version_num FROM alembic_version') == '0016'
                assert sql("SELECT count(*) FROM users WHERE username LIKE 'isolated-ops-%'") == '3'
                ciphertext = sql("SELECT api_key_encrypted FROM providers WHERE name='backup-encrypted-provider'")
                import base64
                from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                encrypted = base64.b64decode(ciphertext[3:])
                assert AESGCM(read_key()).decrypt(encrypted[:12], encrypted[12:], b'helidata-provider-key:v1') == b'isolated-backup-secret'
            finally:
                subprocess.run(['runuser', '-u', 'postgres', '--', 'dropdb', 'stage18_restore'], check=True)
        print('PASS 4: archive pg_restore into a separate real database; users/version/provider ciphertext restored and decryptable with paired Master Key; config/uploads match', flush=True)
        # Filesystem failure must be explicit, never publish an incomplete package.
        link = Path('/data/uploads/forbidden-link'); link.symlink_to('/data/config/provider-encryption.key')
        bad = check(await client.post('/api/admin/backups', headers=super_headers), 202)['id']
        for _ in range(150):
            items = check(await client.get('/api/admin/backups', headers=super_headers))['items']
            failed = next(r for r in items if r['id'] == bad)
            if failed['status'] == 'failed': break
            await asyncio.sleep(.2)
        link.unlink()
        assert failed['error_code'] == 'BACKUP_UPLOAD_SYMLINK'
        assert not (DIRECTORY/(bad+'.tar.gz')).exists()
        assert not list(DIRECTORY.glob('work-*'))
        audits = check(await client.get('/api/admin/audit-logs?resource_type=backup', headers=super_headers))['items']
        assert {'create_backup','backup_ready','download_backup','backup_failed'} <= {r['action'] for r in audits}
        print('PASS 5: upload symlink rejected; failed job/audit persisted; no partial archive or temporary directory', flush=True)
        # Ensure identity is captured at event time, without passwords or full request bodies.
        login_audit = check(await client.get('/api/admin/audit-logs?action=login&actor_id='+str(actors[1].id), headers=super_headers))['items'][0]
        assert login_audit['actor_username'] == actors[1].username
        assert login_audit['actor_role'] == 'admin'
        assert login_audit['details']['request_id'].startswith('req_')
        async with session_factory.begin() as db:
            actor = await db.get(User, actors[1].id); actor.username = 'renamed-ops-admin'
        detail = check(await client.get('/api/admin/audit-logs/'+str(login_audit['id']), headers=super_headers))
        assert detail['actor_username'] == 'isolated-ops-admin'
        assert PASSWORD not in json.dumps(detail)
        async with session_factory.begin() as db:
            actor = await db.get(User, actors[1].id); await db.delete(actor)
        detail = check(await client.get('/api/admin/audit-logs/'+str(login_audit['id']), headers=super_headers))
        assert detail['actor_id'] is None and detail['actor_username'] == 'isolated-ops-admin'
        check(await client.post('/api/auth/login', json={'username':'unknown-user','password':PASSWORD}), 401)
        assert check(await client.get('/api/admin/audit-logs?action=login_failed&result=failure', headers=super_headers))['total'] >= 1
        print('PASS 6: identity/request ID snapshot survives rename and hard deletion; failed login visible; audit details exclude credentials', flush=True)
        user = check(await client.post('/api/admin/users', headers=super_headers,
            json={'username':'audit-created-user','password':PASSWORD}), 201)['user']
        check(await client.patch('/api/admin/users/'+str(user['id']), headers=super_headers, json={'status':'disabled'}))
        check(await client.delete('/api/admin/users/'+str(user['id']), headers=super_headers))
        group = check(await client.post('/api/admin/user-groups', headers=super_headers,
            json={'name':'audit-group'}), 201)
        check(await client.put('/api/admin/user-groups/'+str(group['id']), headers=super_headers,
            json={'name':'audit-group-updated'}))
        check(await client.delete('/api/admin/user-groups/'+str(group['id']), headers=super_headers))
        provider = check(await client.post('/api/admin/providers', headers=super_headers,
            json={'name':'audit-provider','provider_type':'custom_openai','protocol':'openai',
                  'base_url':'http://127.0.0.1:9/v1','status':'disabled','api_key':'isolated-audit-key'}), 201)
        check(await client.patch('/api/admin/providers/'+str(provider['id']), headers=super_headers,
            json={'remark':'updated'}))
        check(await client.delete('/api/admin/providers/'+str(provider['id']), headers=super_headers))
        group = check(await client.post('/api/admin/model-groups', headers=super_headers,
            json={'name':'audit-model-group','logical_models':[]}), 201)
        check(await client.put('/api/admin/model-groups/'+str(group['id']), headers=super_headers,
            json={'name':'audit-model-group-updated','logical_models':[]}))
        check(await client.delete('/api/admin/model-groups/'+str(group['id']), headers=super_headers))
        key = check(await client.post('/api/portal/api-keys', headers=super_headers, json={'name':'audit-admin-key'}), 201)
        check(await client.delete('/api/portal/api-keys/'+str(key['key']['id']), headers=super_headers))
        audited = check(await client.get('/api/admin/audit-logs?page_size=100', headers=super_headers))['items']
        expected = {'create_user','update_user','delete_user','create_user_group','update_user_group',
                    'delete_user_group','create_provider','update_provider','delete_provider',
                    'create_model_group','update_model_group','delete_model_group','create_api_key','delete_api_key'}
        assert expected <= {r['action'] for r in audited}
        assert all(r['actor_username']=='isolated-ops-super_admin' for r in audited if r['action'] in expected)
        assert 'isolated-audit-key' not in json.dumps(audited) and key['secret'] not in json.dumps(audited)
        print('PASS 7: actual user disable/delete, group update, Provider CRUD, model group CRUD, administrator API Key create/delete all audited without secrets', flush=True)
        if os.getenv('STAGE18_UI_HOLD') == '1':
            print('UI_READY: isolated operations fixture', flush=True)
            for _ in range(900):
                if Path('/tmp/stage18-ui-release').exists(): break
                await asyncio.sleep(1)
    await engine.dispose()


asyncio.run(main())
