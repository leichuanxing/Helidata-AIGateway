import asyncio
import secrets

from argon2 import PasswordHasher
from sqlalchemy import select

from app.core.database import engine, session_factory
from app.models.user import User, Role
from app.services.initial_admin import INITIAL_ADMIN_FILE,read_credentials


async def bootstrap():
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
            session.add(User(username=username,password_hash=password_hash,
                             role='super_admin',role_id=await session.scalar(select(Role.id).where(Role.code=='super_admin')),status='enabled',must_change_password=not supplied))
        if supplied:
            INITIAL_ADMIN_FILE.unlink(missing_ok=True)
            print('Configured initial administrator created; password is not logged.',flush=True)
        else:
            print(f'INITIAL ADMIN: admin / {password} (password change required)',flush=True)
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(bootstrap())
