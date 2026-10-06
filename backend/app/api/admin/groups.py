from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import delete, func, select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session
from app.core.dependencies import administrator
from app.core.exceptions import APIError
from app.models.user import User,UserGroup,ModelGroup,UserGroupModelGroup
from app.schemas.access import GroupInput
from app.services.sessions import audit
from app.gateway.quota import snapshot
router=APIRouter(prefix='/api/admin',tags=['用户组'])


async def group_data(db,group):
    ids=(await db.scalars(select(UserGroupModelGroup.model_group_id).where(UserGroupModelGroup.user_group_id==group.id))).all()
    membership=or_(User.user_group_id==group.id,User.user_group_id.is_(None)) if group.is_default else User.user_group_id==group.id
    count=await db.scalar(select(func.count(User.id)).where(membership,User.deleted_at.is_(None)))
    from app.services.group_access import concurrency_limits
    from app.core.config import get_settings
    group_limit,key_limit=concurrency_limits(group,get_settings().gateway.max_concurrency)
    return {**{f:getattr(group,f) for f in ('id','name','description','status','quota_limit','quota_period','max_concurrency','key_max_concurrency','created_at','model_access','is_default')},'effective_max_concurrency':group_limit,'effective_key_max_concurrency':key_limit,'model_group_ids':ids,'user_count':count,'quota_usage':await snapshot(group,recover_expired=False,db=db)}


@router.get('/model-group-options')
async def model_options(actor: User=Depends(administrator),db: AsyncSession=Depends(get_session)):
    rows=(await db.scalars(select(ModelGroup).order_by(ModelGroup.id))).all()
    return {'data':[{'id':r.id,'name':r.name,'status':r.status} for r in rows]}


@router.get('/user-groups')
async def groups(actor: User=Depends(administrator),db: AsyncSession=Depends(get_session),
                 page: int=Query(1,ge=1),page_size: int=Query(20,ge=1,le=100),q: str=Query('',max_length=80),status: str=Query('',pattern='^(enabled|disabled)?$')):
    query=select(UserGroup)
    if status:query=query.where(UserGroup.status==status)
    if q:
        query=query.where(UserGroup.name.icontains(q,autoescape=True))
    total=await db.scalar(select(func.count()).select_from(query.subquery()))
    rows=(await db.scalars(query.order_by(UserGroup.id).offset((page-1)*page_size).limit(page_size))).all()
    return {'data':{'items':[await group_data(db,r) for r in rows],'total':total}}


@router.get('/user-group-options')
async def options(actor: User=Depends(administrator),db: AsyncSession=Depends(get_session)):
    rows=(await db.scalars(select(UserGroup).order_by(UserGroup.id))).all()
    return {'data':[{'id':r.id,'name':r.name,'status':r.status,'is_default':r.is_default} for r in rows]}


@router.get('/user-groups/{group_id}')
async def detail(group_id: int,actor: User=Depends(administrator),db: AsyncSession=Depends(get_session)):
    group=await db.get(UserGroup,group_id)
    if not group:
        raise APIError(404,'GROUP_NOT_FOUND','用户组不存在')
    return {'data':await group_data(db,group)}


async def save_group(db,actor,body,request,group=None):
    ids=sorted(set(body.model_group_ids))
    if len(ids)>100 and (not group or ids!=sorted((await db.scalars(select(UserGroupModelGroup.model_group_id).where(UserGroupModelGroup.user_group_id==group.id))).all())):
        raise APIError(422,'GROUP_MODEL_LIMIT','最多选择100个模型组')
    if len(body.description)>255 and (not group or body.description!=group.description):
        raise APIError(422,'GROUP_REMARK_LIMIT','备注最多255字；旧备注可原样保留')
    if ids:
        found=(await db.scalars(select(ModelGroup.id).where(ModelGroup.id.in_(ids)).with_for_update())).all()
        if len(found)!=len(ids):
            raise APIError(400,'MODEL_GROUP_NOT_FOUND','所选模型组不存在')
    values=body.model_dump(exclude={'model_group_ids'})
    values['model_access']=body.model_access or (group.model_access if group and not ids else 'selected' if ids else 'all')
    if values['model_access']=='all' and ids:
        raise APIError(422,'GROUP_ACCESS_CONFLICT','全部模型授权不能同时选择模型组')
    if group and group.is_default and body.status!='enabled':
        raise APIError(409,'DEFAULT_GROUP_PROTECTED','默认用户组不能禁用')
    action='update_user_group' if group else 'create_user_group'
    if group:
        for field,value in values.items():
            setattr(group,field,value)
    else:
        group=UserGroup(**values)
        db.add(group)
    try:
        await db.flush()
        await db.execute(delete(UserGroupModelGroup).where(UserGroupModelGroup.user_group_id==group.id))
        db.add_all([UserGroupModelGroup(user_group_id=group.id,model_group_id=i) for i in ids])
        await db.flush()
        result=await group_data(db,group)
        audit(db,actor.id,action,group.id,request.client.host,resource_type='user_group')
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise APIError(409,'GROUP_CONFLICT','用户组名称已存在或关联数据已变化') from None
    return {'data':result}


@router.post('/user-groups',status_code=201)
async def create(body: GroupInput,request: Request,actor: User=Depends(administrator),db: AsyncSession=Depends(get_session)):
    return await save_group(db,actor,body,request)


@router.put('/user-groups/{group_id}')
async def edit(group_id: int,body: GroupInput,request: Request,actor: User=Depends(administrator),db: AsyncSession=Depends(get_session)):
    group=await db.scalar(select(UserGroup).where(UserGroup.id==group_id).with_for_update())
    if not group:
        raise APIError(404,'GROUP_NOT_FOUND','用户组不存在')
    return await save_group(db,actor,body,request,group)


@router.delete('/user-groups/{group_id}')
async def remove(group_id: int,request: Request,actor: User=Depends(administrator),db: AsyncSession=Depends(get_session)):
    group=await db.scalar(select(UserGroup).where(UserGroup.id==group_id).with_for_update())
    if not group:
        raise APIError(404,'GROUP_NOT_FOUND','用户组不存在')
    if group.is_default:
        raise APIError(409,'DEFAULT_GROUP_PROTECTED','默认用户组不能删除')
    if await db.scalar(select(User.id).where(User.user_group_id==group_id).limit(1)):
        raise APIError(409,'GROUP_IN_USE','用户组仍被用户引用，请先调整归属；历史用户也会保留引用')
    try:
        await db.delete(group)
        audit(db,actor.id,'delete_user_group',group_id,request.client.host,resource_type='user_group')
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise APIError(409,'GROUP_IN_USE','用户组已被引用，无法删除') from None
    return {'data':{'message':'用户组已删除'}}
