from sqlalchemy import select
from app.core.exceptions import APIError
from app.core.security import digest
from app.models.user import ApiKey, User, UserGroup


async def authenticate(request, db):
    # Only this exact, authenticated admin endpoint accepts a web session.
    # Revalidate the session again during queued admission, never trust a client flag.
    if request.scope['path'] == '/api/admin/chat-test/completions':
        from app.core.dependencies import current_user, active_user, administrator
        from app.services.group_access import resolve_group
        user = await current_user(request, db)
        await active_user(user)
        await administrator(user)
        group = await resolve_group(db, user.user_group_id)
        request.state.web_chat = True
        return None, user, group

    scheme, _, raw = request.headers.get('Authorization', '').partition(' ')
    if request.scope['path']=='/v1/messages':
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
