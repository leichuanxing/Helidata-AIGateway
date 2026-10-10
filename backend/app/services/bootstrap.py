import asyncio
import secrets
import os
from pathlib import Path

from argon2 import PasswordHasher
from sqlalchemy import select

from app.core.database import engine, session_factory
from app.models.user import User, Role
from app.services.initial_admin import INITIAL_ADMIN_FILE,read_credentials


INITIAL_PASSWORD_FILE=Path('/data/config/initial-admin-password.txt')


def publish_initial_password(password):
    # Root-only bootstrap handoff; never put a reusable credential in container logs.
    fd=os.open(INITIAL_PASSWORD_FILE,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as handle:
        handle.write(password+'\n');handle.flush();os.fsync(handle.fileno())


async def bootstrap():
    written=False;committed=False
    try:
        async with session_factory.begin() as session:
            if await session.scalar(select(User.id).where(User.role == 'super_admin')):
                INITIAL_ADMIN_FILE.unlink(missing_ok=True)
                print('Administrator already exists; credentials unchanged.', flush=True)
                return
            supplied=INITIAL_ADMIN_FILE.exists()
            if supplied:
                username,password_hash=read_credentials(INITIAL_ADMIN_FILE)
                password=None
            else:
                username='admin';password=secrets.token_urlsafe(24)
                password_hash=PasswordHasher().hash(password)
                publish_initial_password(password)
                written=True
            session.add(User(username=username,password_hash=password_hash,
                             role='super_admin',role_id=await session.scalar(select(Role.id).where(Role.code=='super_admin')),status='enabled',must_change_password=not supplied))
        committed=True
        if supplied:
            INITIAL_ADMIN_FILE.unlink(missing_ok=True)
            print('Configured initial administrator created; password is not logged.',flush=True)
        else:
            print('INITIAL ADMIN: admin; read /data/config/initial-admin-password.txt as server administrator, then delete the file after changing the password.',flush=True)
    finally:
        if written and not committed:INITIAL_PASSWORD_FILE.unlink(missing_ok=True)
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(bootstrap())
