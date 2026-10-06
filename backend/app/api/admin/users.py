import secrets
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.dependencies import administrator
from app.core.exceptions import APIError
from app.core.security import hash_password, now,digest
from app.core.config import get_settings
from app.core.redis import redis_client
from redis.exceptions import RedisError
from app.models.user import User, Role, UserGroup
from app.schemas.auth import UserCreate, UserEdit, public_user,AdminPasswordReset
from app.services.sessions import audit, revoke_all

router=APIRouter(prefix='/api/admin',tags=['用户管理'])


async def public_rows(rows):
    data=[public_user(row) for row in rows]
    try:
        async with redis_client.pipeline(transaction=False) as pipe:
            for row in rows:
                key='login:account:'+digest(row.username.lower());pipe.get(key);pipe.ttl(key)
            values=await pipe.execute()
        for i,item in enumerate(data):
            item['login_locked']=int(values[i*2] or 0)>=get_settings().security.login_max_attempts
            item['lock_remaining_seconds']=max(0,int(values[i*2+1])) if item['login_locked'] else 0
    except RedisError:
        for item in data:item.update(login_locked=None,lock_remaining_seconds=None)
    return data


def allowed(actor,target):
    if actor.role=='admin' and target.role!='user':
        raise APIError(403,'FORBIDDEN','管理员仅可管理普通用户')


async def target_user(db,actor,user_id):
    if actor.role=='super_admin':
        await db.execute(text('SELECT pg_advisory_xact_lock(71003)'))
    target=await db.scalar(select(User).where(User.id==user_id,User.deleted_at.is_(None)).with_for_update())
    if not target:
        raise APIError(404,'USER_NOT_FOUND','用户不存在')
    allowed(actor,target)
    return target


async def role_and_group(db,actor,role,group):
    if actor.role=='admin' and role!='user':
        raise APIError(403,'FORBIDDEN','管理员不可提升用户角色')
    role_id=await db.scalar(select(Role.id).where(Role.code==role))
    if group is not None and not await db.get(UserGroup,group):
        raise APIError(400,'GROUP_NOT_FOUND','用户组不存在')
    return role_id


async def protect_super(db,target,new_role,new_status):
    if target.role=='super_admin' and target.status=='enabled' and (new_role!='super_admin' or new_status!='enabled'):
        ids=(await db.scalars(select(User.id).where(User.role=='super_admin',User.status=='enabled',User.deleted_at.is_(None)).with_for_update())).all()
        if len(ids)<=1:
            raise APIError(409,'LAST_SUPER_ADMIN','不能删除、禁用或降级最后一个超级管理员')


@router.get('/roles')
async def roles(actor: User=Depends(administrator),db: AsyncSession=Depends(get_session)):
    rows=(await db.scalars(select(Role).where(Role.code.in_(['super_admin','admin','user'])))).all()
    return {'data':[{'id':r.id,'code':r.code,'name':r.name} for r in rows if actor.role=='super_admin' or r.code=='user']}


@router.get('/users')
async def users(actor: User=Depends(administrator),db: AsyncSession=Depends(get_session),
                page: int=Query(1,ge=1),page_size: int=Query(20,ge=1,le=100),q: str=Query('',max_length=100),status: str=Query('',max_length=20)):
    query=select(User).where(User.deleted_at.is_(None))
    if actor.role=='admin':
        query=query.where(User.role=='user')
    if q:
        query=query.where(User.username.icontains(q,autoescape=True)|User.name.icontains(q,autoescape=True))
    if status:
        query=query.where(User.status==status)
    total=await db.scalar(select(func.count()).select_from(query.subquery()))
    rows=(await db.scalars(query.order_by(User.id).offset((page-1)*page_size).limit(page_size))).all()
    return {'data':{'items':await public_rows(rows),'total':total}}


@router.get('/users/{user_id}')
async def detail(user_id: int,actor: User=Depends(administrator),db: AsyncSession=Depends(get_session)):
    return {'data':(await public_rows([await target_user(db,actor,user_id)]))[0]}


@router.post('/users',status_code=201)
async def create(body: UserCreate,request: Request,actor: User=Depends(administrator),db: AsyncSession=Depends(get_session)):
    if body.user_group_id is None:
        from app.services.group_access import default_group
        group=await default_group(db)
        if not group:raise APIError(409,'DEFAULT_GROUP_MISSING','默认用户组不可用')
        body=body.model_copy(update={'user_group_id':group.id})
    role_id=await role_and_group(db,actor,body.role,body.user_group_id)
    password=body.password or secrets.token_urlsafe(24)
    target=User(**body.model_dump(exclude={'password','password_confirmation'}),role_id=role_id,password_hash=await hash_password(password),must_change_password=True)
    db.add(target)
    try:
        await db.flush()
        audit(db,actor.id,'create_user',target.id,request.client.host)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise APIError(409,'USERNAME_EXISTS','用户名已存在') from None
    return {'data':{'user':public_user(target),'initial_password':password}}


@router.patch('/users/{user_id}')
async def edit(user_id: int,body: UserEdit,request: Request,actor: User=Depends(administrator),db: AsyncSession=Depends(get_session)):
    target=await target_user(db,actor,user_id)
    values=body.model_dump(exclude_unset=True)
    role=values.get('role',target.role)
    status=values.get('status',target.status)
    group=values.get('user_group_id',target.user_group_id)
    if 'user_group_id' in values and group is None:
        from app.services.group_access import default_group
        fallback=await default_group(db)
        if not fallback:raise APIError(409,'DEFAULT_GROUP_MISSING','默认用户组不可用')
        group=values['user_group_id']=fallback.id
    if actor.id==target.id and (role!=target.role or status!='enabled'):
        raise APIError(409,'SELF_OPERATION','不能变更自己的角色或禁用自己')
    await protect_super(db,target,role,status)
    role_id=await role_and_group(db,actor,role,group)
    changed=(target.role!=role or target.status!=status or target.user_group_id!=group)
    for key,value in values.items():
        setattr(target,key,value)
    target.role_id=role_id
    if changed:
        await revoke_all(db,target)
    audit(db,actor.id,'update_user',target.id,request.client.host)
    await db.commit()
    return {'data':public_user(target)}


@router.delete('/users/{user_id}')
async def delete(user_id: int,request: Request,actor: User=Depends(administrator),db: AsyncSession=Depends(get_session)):
    target=await target_user(db,actor,user_id)
    if target.id==actor.id:
        raise APIError(409,'SELF_OPERATION','不能删除自己')
    await protect_super(db,target,target.role,'deleted')
    target.status='deleted'
    target.deleted_at=now()
    await revoke_all(db,target)
    audit(db,actor.id,'delete_user',target.id,request.client.host)
    await db.commit()
    return {'data':{'message':'用户已删除，历史记录保留'}}


@router.post('/users/{user_id}/reset-password')
async def reset(user_id: int,request: Request,body: AdminPasswordReset | None=None,actor: User=Depends(administrator),db: AsyncSession=Depends(get_session)):
    target=await target_user(db,actor,user_id)
    password=body.password if body else secrets.token_urlsafe(24)
    target.password_hash=await hash_password(password)
    target.must_change_password=True
    await revoke_all(db,target)
    audit(db,actor.id,'reset_password',target.id,request.client.host)
    await db.commit()
    return {'data':{'message':'密码已重置，用户下次登录需改密'}} if body else {'data':{'initial_password':password}}


@router.post('/users/{user_id}/unlock')
async def unlock(user_id: int,request: Request,actor: User=Depends(administrator),db: AsyncSession=Depends(get_session)):
    target=await target_user(db,actor,user_id)
    try:await redis_client.delete('login:account:'+digest(target.username.lower()))
    except RedisError:raise APIError(503,'AUTH_UNAVAILABLE','认证服务暂不可用，未完成解锁') from None
    audit(db,actor.id,'unlock_user',target.id,request.client.host);await db.commit()
    return {'data':{'message':'账号锁定已解除'}}
