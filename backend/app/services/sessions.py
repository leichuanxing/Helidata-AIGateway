from sqlalchemy import update
from app.models.user import AuditLog, RefreshSession


def audit(db, user_id, action, resource_id=None, client_ip=None, result='success', resource_type='user'):
    from app.models.user import User
    from app.gateway.request_id import request_id
    actor = next((row for row in db.identity_map.values() if isinstance(row, User) and row.id == user_id), None)
    details = {'request_id': request_id.get(), 'actor_username': actor.username if actor else None,
               'actor_role': actor.role if actor else None}
    db.add(AuditLog(actor_id=user_id,action=action,resource_type=resource_type,
                    resource_id=str(resource_id) if resource_id else None,
                    client_ip=client_ip,result=result,details=details))


async def revoke_all(db, user):
    user.auth_version += 1
    await db.execute(update(RefreshSession).where(RefreshSession.user_id==user.id).values(revoked=True))

