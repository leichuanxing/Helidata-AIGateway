"""Bounded manual snapshots. Credentials never enter command arguments or logs."""
import asyncio
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import tempfile
from sqlalchemy import select, text
from app.core.config import get_settings
from app.core.database import session_factory
from app.models.backup import Backup
from app.services.sessions import audit

DIRECTORY = Path('/data/backup/manual')
UPLOADS = Path('/data/uploads')
MAX_UPLOAD_BYTES = 1024 * 1024 * 1024
MAX_UPLOAD_FILES = 10000


class BackupFailure(Exception):
    pass


def cleanup_interrupted():
    # Called only while holding the worker lock, before starting another dump.
    for path in DIRECTORY.glob('work-*'):
        if path.is_symlink() or not path.is_dir(): continue
        target = path.resolve()
        if target.parent == DIRECTORY.resolve(): shutil.rmtree(target)


def archive(ident):
    DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(DIRECTORY, 0o700)
    if shutil.disk_usage(DIRECTORY).free < 128 * 1024 * 1024:
        raise BackupFailure('BACKUP_DISK_SPACE')
    destination = DIRECTORY / (ident + '.tar.gz')
    with tempfile.TemporaryDirectory(prefix='work-', dir=DIRECTORY) as work:
        dump = Path(work) / 'database.dump'
        cfg = get_settings().database
        env = {**os.environ, 'PGPASSWORD': cfg.password.get_secret_value(), 'PGSSLMODE': 'disable'}
        try:
            result = subprocess.run(['pg_dump', '-h', cfg.host, '-p', str(cfg.port), '-U', cfg.username,
                '-d', cfg.database, '--format=custom', '--no-owner', '--no-acl', '--file', str(dump)],
                env=env, capture_output=True, timeout=300)
        except subprocess.TimeoutExpired:
            raise BackupFailure('BACKUP_DATABASE_TIMEOUT') from None
        if result.returncode: raise BackupFailure('BACKUP_DATABASE_FAILED')
        package = Path(work) / 'package.tar.gz'
        count = 0; total = 0; files = []
        for folder, dirs, names in os.walk(UPLOADS, followlinks=False):
            for name in [*dirs, *names]:
                if (Path(folder)/name).is_symlink(): raise BackupFailure('BACKUP_UPLOAD_SYMLINK')
            for name in names:
                path = Path(folder)/name
                info = path.stat(follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode): raise BackupFailure('BACKUP_UPLOAD_TYPE')
                count += 1; total += info.st_size
                if count > MAX_UPLOAD_FILES or total > MAX_UPLOAD_BYTES:
                    raise BackupFailure('BACKUP_UPLOAD_LIMIT')
                files.append(path)
        if shutil.disk_usage(DIRECTORY).free < dump.stat().st_size + total + 128 * 1024 * 1024:
            raise BackupFailure('BACKUP_DISK_SPACE')
        manifest = {'format': 'helidata-manual-backup-v1', 'id': ident,
            'created_at': datetime.now(timezone.utc).isoformat(), 'database': cfg.database,
            'database_format': 'pg_dump_custom', 'upload_files': count,
            'contains_secrets': True, 'filesystem_consistency': 'quiesce uploads/config writers during snapshot'}
        with tarfile.open(package, 'w:gz') as tar:
            raw = json.dumps(manifest, ensure_ascii=False).encode()
            info = tarfile.TarInfo('manifest.json'); info.size = len(raw); info.mode = 0o600
            tar.addfile(info, io.BytesIO(raw))
            for source, target in [(dump, 'database.dump'),
                (Path('/data/config/config.yaml'), 'config/config.yaml'),
                (Path('/data/config/provider-encryption.key'), 'config/provider-encryption.key'),
                *[(path, 'uploads/' + path.relative_to(UPLOADS).as_posix()) for path in files]]:
                fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, 'rb') as handle:
                    info = tar.gettarinfo(str(source), arcname=target)
                    if not info.isfile(): raise BackupFailure('BACKUP_FILE_TYPE')
                    info.mode = 0o600; info.uid = info.gid = 0; info.uname = info.gname = ''
                    tar.addfile(info, handle)
        os.chmod(package, 0o600)
        with package.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest(); os.fsync(handle.fileno())
        size = package.stat().st_size
        os.replace(package, destination)
        fd = os.open(DIRECTORY, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)
        return size, digest


async def run_once(recover=False):
    # The session-level lock spans pg_dump and publication, including cancellation.
    async with session_factory() as lock_db:
        locked = await lock_db.scalar(text('SELECT pg_try_advisory_lock(71018)'))
        if not locked: return
        try:
            if recover: await asyncio.to_thread(cleanup_interrupted)
            async with session_factory.begin() as db:
                if recover:
                    rows = (await db.scalars(select(Backup).where(Backup.status == 'running'))).all()
                    for row in rows:
                        row.status = 'failed'; row.error_code = 'BACKUP_INTERRUPTED'
                        row.finished_at = datetime.now(timezone.utc)
                        audit(db, row.actor_id, 'backup_failed', row.id, result='failure', resource_type='backup')
                row = await db.scalar(select(Backup).where(Backup.status == 'queued').with_for_update())
                if row is None: return
                row.status = 'running'; ident = row.id
            try:
                # Complete the filesystem thread before releasing the lock on cancellation.
                task = asyncio.create_task(asyncio.to_thread(archive, ident))
                try: size, digest = await asyncio.shield(task)
                except asyncio.CancelledError:
                    await task
                    raise
                status, error = 'ready', None
            except BackupFailure as exc:
                status, error, size, digest = 'failed', str(exc), None, None
            except Exception:
                status, error, size, digest = 'failed', 'BACKUP_FILE_FAILED', None, None
            async with session_factory.begin() as db:
                row = await db.get(Backup, ident)
                row.status = status; row.error_code = error; row.size_bytes = size; row.sha256 = digest
                row.finished_at = datetime.now(timezone.utc)
                audit(db, row.actor_id, 'backup_ready' if status == 'ready' else 'backup_failed', ident,
                      result='success' if status == 'ready' else 'failure', resource_type='backup')
        finally:
            await lock_db.execute(text('SELECT pg_advisory_unlock(71018)'))


async def loop():
    recover = True
    while True:
        try:
            await run_once(recover); recover = False
        except Exception:
            import logging
            logging.getLogger(__name__).warning('Backup worker pending')
        await asyncio.sleep(2)
