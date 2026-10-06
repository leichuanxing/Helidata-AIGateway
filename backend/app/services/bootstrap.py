import asyncio
import secrets

from argon2 import PasswordHasher
from sqlalchemy import select

from app.core.database import engine, session_factory
from app.models.user import User, Role


async def bootstrap():
    try:
        async with session_factory.begin() as session:
            if await session.scalar(select(User.id).where(User.username == 'admin')):
                print('Administrator already exists; credentials unchanged.', flush=True)
                return
            password = secrets.token_urlsafe(24)
            session.add(User(username='admin', password_hash=PasswordHasher().hash(password),
                             role='super_admin', role_id=await session.scalar(select(Role.id).where(Role.code == 'super_admin')), status='enabled', must_change_password=True))
        print(f'INITIAL ADMIN: admin / {password} (password change required)', flush=True)
    finally:
        await engine.dispose()


if __name__ == '__main__':
    asyncio.run(bootstrap())
