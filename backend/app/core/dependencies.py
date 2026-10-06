from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.exceptions import APIError
from app.core.security import decode_token, now
from app.models.user import User, RefreshSession


async def current_user(request: Request, db: AsyncSession = Depends(get_session)):
    authorization = request.headers.get('authorization','')
    if not authorization.startswith('Bearer '):
        raise APIError(401,'LOGIN_REQUIRED','请先登录')
    claims = decode_token(authorization[7:])
    user = await db.get(User,int(claims['sub']))
    if not user or user.deleted_at:
        raise APIError(401,'SESSION_INVALID','登录已失效')
    if user.status != 'enabled':
        raise APIError(403,'USER_DISABLED','用户已被禁用')
    session = await db.get(RefreshSession,claims['sid'])
    if (not session or session.user_id != user.id or session.revoked or session.expires_at <= now()
            or user.auth_version != claims['ver'] or session.auth_version != user.auth_version):
        raise APIError(401,'SESSION_INVALID','登录已失效')
    request.state.session_id = session.id
    return user


async def active_user(user: User = Depends(current_user)):
    if user.must_change_password:
        raise APIError(403,'PASSWORD_CHANGE_REQUIRED','首次登录必须修改密码')
    return user


async def administrator(user: User = Depends(active_user)):
    if user.role not in ('super_admin','admin'):
        raise APIError(403,'FORBIDDEN','无管理权限')
    return user


async def super_administrator(user: User = Depends(administrator)):
    if user.role != 'super_admin':
        raise APIError(403, 'FORBIDDEN', '仅超级管理员可执行此操作')
    return user
