"""Root operator recovery: prints one random password, revokes existing sessions."""
import asyncio
import os
import secrets
from sqlalchemy import select
from app.core.database import engine, session_factory
from app.core.security import hash_password
from app.models.user import User
from app.services.sessions import audit, revoke_all


async def reset():
    if os.geteuid()!=0:
        raise SystemExit('Requires container root operator')
    try:
        async with session_factory.begin() as db:
            user=await db.scalar(select(User).where(User.username=='admin',User.deleted_at.is_(None)).with_for_update())
            if not user or user.role!='super_admin':
                raise SystemExit('Active bootstrap super administrator not found')
            password=secrets.token_urlsafe(24)
            user.password_hash=await hash_password(password)
            user.status='enabled'
            user.must_change_password=True
            await revoke_all(db,user)
            audit(db,user.id,'operator_recovery',user.id)
        print('用户名：admin\n临时密码：'+password+'\n首次登录必须改密。')
    finally:
        await engine.dispose()


if __name__=='__main__':
    asyncio.run(reset())
