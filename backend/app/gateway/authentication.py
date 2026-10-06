from sqlalchemy import select
from app.core.exceptions import APIError
from app.core.security import digest
from app.models.user import ApiKey, User, UserGroup


async def authenticate(request, db):
    scheme, _, raw = request.headers.get('Authorization', '').partition(' ')
    if request.url.path=='/v1/messages':
        alternate=request.headers.get('x-api-key','')
        if alternate and raw and alternate!=raw:raise APIError(401,'INVALID_API_KEY','认证凭证不一致')
        if alternate:scheme,raw='bearer',alternate
    if scheme.lower() != 'bearer' or not raw.startswith('sk-hd-') or len(raw) != 49:
        raise APIError(401, 'INVALID_API_KEY', 'API Key 无效')
    row = (await db.execute(select(ApiKey, User, UserGroup).join(User, User.id == ApiKey.user_id)
        .outerjoin(UserGroup, UserGroup.id == User.user_group_id).where(ApiKey.key_hash == digest(raw)))).first()
    if not row or row[0].deleted_at or row[0].status != 'enabled':
        raise APIError(401, 'INVALID_API_KEY', 'API Key 无效')
    if row[2] is None:
        from app.services.group_access import default_group
        return row[0],row[1],await default_group(db)
    return row
