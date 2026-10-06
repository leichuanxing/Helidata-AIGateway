import secrets
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.core.dependencies import current_user
from app.core.exceptions import APIError
from app.core.redis import redis_client
from app.core.security import access_token, digest, dummy_hash, hash_password, now, verify_password
from app.models.user import User, RefreshSession
from app.schemas.auth import Login, PasswordChange, public_user
from app.services.sessions import audit, revoke_all

router = APIRouter(prefix='/api/auth', tags=['认证'])


def same_origin(request):
    origin = request.headers.get('origin')
    rejected = request.headers.get('sec-fetch-site') == 'cross-site'
    if origin:
        try:
            parsed = urlsplit(origin)
            expected = urlsplit(str(request.url))
            rejected = rejected or parsed.scheme not in ('http','https') or parsed.scheme != expected.scheme or parsed.netloc.lower() != expected.netloc.lower() or bool(parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment)
        except ValueError:
            rejected = True
    if rejected:
        raise APIError(403,'CSRF_REJECTED','请求来源校验失败')


def csrf(request, session):
    header = request.headers.get('x-csrf-token','')
    cookie = request.cookies.get('hd_csrf','')
    if not header or not secrets.compare_digest(header,cookie) or not secrets.compare_digest(digest(header),session.csrf_hash):
        raise APIError(403,'CSRF_REJECTED','会话校验失败')


def tokens(response, user, session, refresh, nonce):
    cfg = get_settings().security
    seconds = max(1,int((session.expires_at-now()).total_seconds()))
    response.set_cookie('hd_refresh',refresh,max_age=seconds,path='/api/auth',httponly=True,secure=cfg.cookie_secure,samesite='strict')
    response.set_cookie('hd_csrf',nonce,max_age=seconds,path='/',httponly=False,secure=cfg.cookie_secure,samesite='strict')
    response.headers['Cache-Control'] = 'no-store'
    return {'data':{'access_token':access_token(user,session.id),'token_type':'bearer',
                    'expires_in':cfg.jwt_expire,'user':public_user(user)}}


def clear(response):
    response.delete_cookie('hd_refresh',path='/api/auth')
    response.delete_cookie('hd_csrf',path='/')
    response.headers['Cache-Control']='no-store'


@router.post('/login')
async def login(body: Login, request: Request, response: Response, db: AsyncSession=Depends(get_session)):
    same_origin(request)
    cfg = get_settings().security
    key = 'login:account:'+digest(body.username.lower())
    ipkey = 'login:ip:'+digest(request.client.host)
    reserve = """local a=tonumber(redis.call('GET',KEYS[1]) or '0'); local i=tonumber(redis.call('GET',KEYS[2]) or '0'); if a>=tonumber(ARGV[1]) or i>=tonumber(ARGV[2]) then return 0 end; for k=1,2 do local n=redis.call('INCR',KEYS[k]); if n==1 then redis.call('EXPIRE',KEYS[k],ARGV[3]) end end; return 1"""
    try:
        permitted=await redis_client.eval(reserve,2,key,ipkey,cfg.login_max_attempts,max(30,cfg.login_max_attempts*6),cfg.login_lock_seconds)
        if not permitted:
            raise APIError(429,'LOGIN_LIMITED','尝试次数过多，请稍后重试')
    except APIError:
        raise
    except Exception:
        raise APIError(503,'AUTH_UNAVAILABLE','认证服务暂不可用') from None
    user = await db.scalar(select(User).where(User.username==body.username).with_for_update())
    valid = await verify_password(user.password_hash if user else dummy_hash,body.password)
    if not user or not valid or user.status!='enabled' or user.deleted_at:
        audit(db,None,'login_failed',client_ip=request.client.host,result='failure')
        await db.commit()
        raise APIError(401,'INVALID_CREDENTIALS','用户名或密码错误')
    try:
        await redis_client.eval("redis.call('DEL',KEYS[1]); local n=tonumber(redis.call('GET',KEYS[2]) or '0'); if n>0 then redis.call('DECR',KEYS[2]) end; return 1",2,key,ipkey)
    except Exception:
        raise APIError(503,'AUTH_UNAVAILABLE','认证服务暂不可用') from None
    refresh,nonce = secrets.token_urlsafe(48),secrets.token_urlsafe(32)
    session = RefreshSession(id=str(uuid.uuid4()),user_id=user.id,token_hash=digest(refresh),csrf_hash=digest(nonce),
                             auth_version=user.auth_version,expires_at=now()+timedelta(days=cfg.refresh_days),revoked=False)
    user.last_login_at=now()
    db.add(session)
    audit(db,user.id,'login',user.id,request.client.host)
    await db.commit()
    return tokens(response,user,session,refresh,nonce)


@router.post('/refresh')
async def refresh(request: Request,response: Response,db: AsyncSession=Depends(get_session)):
    same_origin(request)
    token=request.cookies.get('hd_refresh','')
    initial=await db.scalar(select(RefreshSession).where(RefreshSession.token_hash==digest(token)))
    if not token or not initial:
        raise APIError(401,'SESSION_INVALID','请重新登录')
    user=await db.scalar(select(User).where(User.id==initial.user_id).with_for_update())
    session=await db.scalar(select(RefreshSession).where(RefreshSession.token_hash==digest(token)).with_for_update().execution_options(populate_existing=True))
    if not session or session.revoked or session.expires_at<=now() or not user or user.status!='enabled' or user.deleted_at or session.auth_version!=user.auth_version:
        raise APIError(401,'SESSION_INVALID','请重新登录')
    csrf(request,session)
    new_token,nonce=secrets.token_urlsafe(48),secrets.token_urlsafe(32)
    session.token_hash=digest(new_token)
    session.csrf_hash=digest(nonce)
    await db.commit()
    return tokens(response,user,session,new_token,nonce)


@router.get('/me')
async def me(response: Response,user: User=Depends(current_user)):
    response.headers['Cache-Control']='no-store'
    return {'data':public_user(user)}


@router.post('/logout')
async def logout(request: Request,response: Response,db: AsyncSession=Depends(get_session)):
    same_origin(request)
    initial=await db.scalar(select(RefreshSession).where(RefreshSession.token_hash==digest(request.cookies.get('hd_refresh',''))))
    if initial:
        await db.scalar(select(User).where(User.id==initial.user_id).with_for_update())
    session=await db.scalar(select(RefreshSession).where(RefreshSession.token_hash==digest(request.cookies.get('hd_refresh',''))).with_for_update().execution_options(populate_existing=True))
    if session:
        csrf(request,session)
        session.revoked=True
        audit(db,session.user_id,'logout',session.user_id,request.client.host)
        await db.commit()
    clear(response)
    return {'data':{'message':'已退出'}}


@router.post('/change-password')
async def change_password(body: PasswordChange,request: Request,response: Response,
                          user: User=Depends(current_user),db: AsyncSession=Depends(get_session)):
    await db.refresh(user,with_for_update=True)
    if not await verify_password(user.password_hash,body.old_password):
        raise APIError(400,'PASSWORD_INCORRECT','原密码错误')
    if await verify_password(user.password_hash,body.new_password):
        raise APIError(400,'PASSWORD_UNCHANGED','新密码不能与原密码相同')
    user.password_hash=await hash_password(body.new_password)
    user.must_change_password=False
    await revoke_all(db,user)
    audit(db,user.id,'change_password',user.id,request.client.host)
    await db.commit()
    clear(response)
    return {'data':{'message':'密码已修改，请重新登录'}}
