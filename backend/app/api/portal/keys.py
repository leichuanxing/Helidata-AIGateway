import secrets
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.dependencies import active_user
from app.core.exceptions import APIError
from app.core.security import digest,now
from app.models.user import User,ApiKey
from app.schemas.access import KeyCreate,KeyEdit,public_key
from app.services.sessions import audit
router=APIRouter(prefix='/api/portal/api-keys',tags=['API Key'])


async def own_key(db,user,key_id):
    key=await db.scalar(select(ApiKey).where(ApiKey.id==key_id,ApiKey.user_id==user.id,ApiKey.deleted_at.is_(None)).with_for_update())
    if not key:
        raise APIError(404,'KEY_NOT_FOUND','API Key 不存在')
    return key


@router.get('')
async def keys(user: User=Depends(active_user),db: AsyncSession=Depends(get_session),page: int=Query(1,ge=1),page_size: int=Query(20,ge=1,le=100)):
    query=select(ApiKey).where(ApiKey.user_id==user.id,ApiKey.deleted_at.is_(None))
    total=await db.scalar(select(func.count()).select_from(query.subquery()))
    rows=(await db.scalars(query.order_by(ApiKey.id.desc()).offset((page-1)*page_size).limit(page_size))).all()
    return {'data':{'items':[public_key(k) for k in rows],'total':total}}


@router.get('/{key_id}')
async def detail(key_id: int,user: User=Depends(active_user),db: AsyncSession=Depends(get_session)):
    return {'data':public_key(await own_key(db,user,key_id))}


@router.post('',status_code=201)
async def create(body: KeyCreate,request: Request,user: User=Depends(active_user),db: AsyncSession=Depends(get_session)):
    raw='sk-hd-'+secrets.token_urlsafe(32)
    key=ApiKey(user_id=user.id,name=body.name,key_hash=digest(raw),prefix=raw[:12],suffix=raw[-4:])
    db.add(key)
    await db.flush()
    audit(db,user.id,'create_api_key',key.id,request.client.host,resource_type='api_key')
    await db.commit()
    return {'data':{'key':public_key(key),'secret':raw}}


@router.patch('/{key_id}')
async def edit(key_id: int,body: KeyEdit,request: Request,user: User=Depends(active_user),db: AsyncSession=Depends(get_session)):
    key=await own_key(db,user,key_id)
    for field,value in body.model_dump(exclude_unset=True).items():
        setattr(key,field,value)
    audit(db,user.id,'update_api_key',key.id,request.client.host,resource_type='api_key')
    await db.commit()
    return {'data':public_key(key)}


@router.delete('/{key_id}')
async def remove(key_id: int,request: Request,user: User=Depends(active_user),db: AsyncSession=Depends(get_session)):
    key=await own_key(db,user,key_id)
    key.status='deleted'
    key.deleted_at=now()
    audit(db,user.id,'delete_api_key',key.id,request.client.host,resource_type='api_key')
    await db.commit()
    return {'data':{'message':'API Key 已删除'}}
