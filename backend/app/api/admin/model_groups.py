from fastapi import APIRouter,Depends,Query,Request
from sqlalchemy import select,delete,func
from sqlalchemy.exc import IntegrityError
from app.core.database import get_session
from app.core.dependencies import administrator
from app.core.exceptions import APIError
from app.models.user import ModelGroup,ModelGroupModel,LogicalModel,UserGroupModelGroup
from app.schemas.models import ModelGroupInput,protocol_category
from app.api.admin.model_mappings import config_lock
from app.services.sessions import audit
router=APIRouter(prefix='/api/admin/model-groups',tags=['模型组'])


async def group_data(db,row):
    members=(await db.scalars(select(ModelGroupModel.logical_model).where(ModelGroupModel.model_group_id==row.id).order_by(ModelGroupModel.position))).all()
    return {**{f:getattr(row,f) for f in ('id','name','description','status','protocol_type','created_at')},'logical_models':list(members)}


@router.get('')
async def listing(actor=Depends(administrator),db=Depends(get_session),page: int=Query(1,ge=1),page_size: int=Query(20,ge=1,le=100),q: str=Query('',max_length=80),protocol_type: str=Query('',pattern=r'^(text|image|vector)?$')):
    query=select(ModelGroup)
    if q: query=query.where(ModelGroup.name.icontains(q,autoescape=True))
    if protocol_type: query=query.where(ModelGroup.protocol_type==protocol_type)
    total=await db.scalar(select(func.count()).select_from(query.subquery()))
    rows=(await db.scalars(query.order_by(ModelGroup.id).offset((page-1)*page_size).limit(page_size))).all()
    return {'data':{'items':[await group_data(db,r) for r in rows],'total':total}}


async def target(db,group_id,lock=False):
    query=select(ModelGroup).where(ModelGroup.id==group_id)
    if lock: query=query.with_for_update()
    row=await db.scalar(query)
    if not row: raise APIError(404,'MODEL_GROUP_NOT_FOUND','模型组不存在')
    return row


@router.get('/{group_id}')
async def detail(group_id: int,actor=Depends(administrator),db=Depends(get_session)):
    return {'data':await group_data(db,await target(db,group_id))}


async def save(db,actor,request,body,row=None):
    names=body.logical_models
    found={m.name:m for m in (await db.scalars(select(LogicalModel).where(LogicalModel.name.in_(names)))).all()}
    category=body.protocol_type
    if category is None:
        if len(found)!=len(names): raise APIError(400,'LOGICAL_MODEL_NOT_FOUND','自定义模型名需要先选择协议类型')
        categories={protocol_category(m.model_type) for m in found.values()}
        category=next(iter(categories)) if len(categories)==1 else None
    else:
        if any(protocol_category(m.model_type)!=category for m in found.values()):
            raise APIError(409,'MODEL_GROUP_TYPE_CONFLICT','模型与分组协议类型不一致')
        for name in names:
            if name not in found:db.add(LogicalModel(name=name,model_type={'text':'text','image':'image','vector':'embedding'}[category]))
    if row and category not in (None,'text'):
        from app.models.routing import RouteConfig
        if await db.scalar(select(RouteConfig.id).where((RouteConfig.simple_model_group==row.id)|(RouteConfig.complex_model_group==row.id)).limit(1)):
            raise APIError(409,'MODEL_GROUP_IN_USE','智能模型选择引用的分组必须保持文本类型')
    action='update_model_group' if row else 'create_model_group'
    if row:
        for f,v in body.model_dump(exclude={'logical_models'}).items(): setattr(row,f,v)
    else:
        row=ModelGroup(**body.model_dump(exclude={'logical_models'}));db.add(row)
    row.protocol_type=category
    try:
        await db.flush()
        await db.execute(delete(ModelGroupModel).where(ModelGroupModel.model_group_id==row.id))
        db.add_all([ModelGroupModel(model_group_id=row.id,logical_model=name,position=i) for i,name in enumerate(names)])
        await db.flush()
        result=await group_data(db,row)
        audit(db,actor.id,action,row.id,request.client.host,resource_type='model_group');await db.commit()
    except IntegrityError:
        await db.rollback();raise APIError(409,'MODEL_GROUP_CONFLICT','模型组名称已存在或成员配置冲突') from None
    return {'data':result}


@router.post('',status_code=201)
async def create(body: ModelGroupInput,request: Request,actor=Depends(administrator),db=Depends(get_session)):
    await config_lock(db);return await save(db,actor,request,body)


@router.put('/{group_id}')
async def edit(group_id: int,body: ModelGroupInput,request: Request,actor=Depends(administrator),db=Depends(get_session)):
    await config_lock(db);return await save(db,actor,request,body,await target(db,group_id,True))


@router.delete('/{group_id}')
async def remove(group_id: int,request: Request,actor=Depends(administrator),db=Depends(get_session)):
    await config_lock(db);row=await target(db,group_id,True)
    from app.models.routing import RouteConfig
    if await db.scalar(select(RouteConfig.id).where((RouteConfig.simple_model_group==group_id)|(RouteConfig.complex_model_group==group_id)).limit(1)):
        raise APIError(409,'MODEL_GROUP_IN_USE','模型组已被智能模型选择引用，请先修改路由配置')
    if await db.scalar(select(UserGroupModelGroup.user_group_id).where(UserGroupModelGroup.model_group_id==group_id).limit(1)):
        raise APIError(409,'MODEL_GROUP_IN_USE','模型组已授权给用户组，请先取消关联')
    try:
        await db.delete(row);audit(db,actor.id,'delete_model_group',group_id,request.client.host,resource_type='model_group');await db.commit()
    except IntegrityError:
        await db.rollback();raise APIError(409,'MODEL_GROUP_IN_USE','模型组已被引用，无法删除') from None
    return {'data':{'message':'模型组已删除'}}
