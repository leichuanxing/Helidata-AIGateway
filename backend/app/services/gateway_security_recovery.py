"""Server-only emergency access recovery; never exposed over HTTP."""
import argparse, asyncio
from sqlalchemy import select
from app.core.database import session_factory
from app.models.user import SystemSetting, AuditLog
from app.schemas.gateway_security import SecurityPolicy

async def reset():
    from app.api.admin.model_mappings import config_lock
    async with session_factory() as db:
        await config_lock(db)
        row=await db.get(SystemSetting,'gateway_security',with_for_update=True)
        if row:
            old=SecurityPolicy.model_validate(row.value)
            new=SecurityPolicy(revision=old.revision+1,login_max_attempts=old.login_max_attempts,login_lock_seconds=old.login_lock_seconds)
            row.value=new.model_dump(mode='json')
        db.add(AuditLog(action='gateway_security_recovered',resource_type='gateway_security',result='success',details={'method':'server_cli'}))
        await db.commit()
    print('Access restrictions reset. Restart the application to reload. Account passwords are unchanged.')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Reset gateway IP, Key binding, ban, proxy and RPM restrictions')
    parser.add_argument('--confirm-reset-access',action='store_true',required=True)
    parser.parse_args()
    asyncio.run(reset())
