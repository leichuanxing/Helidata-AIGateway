from fastapi import APIRouter,Depends,Query,Request
from sqlalchemy import select,delete,func,text
from sqlalchemy.exc import IntegrityError
from app.core.database import get_session
from app.core.dependencies import administrator
from app.core.exceptions import APIError
from app.models.user import ModelGroup,ModelGroupModel,LogicalModel,UserGroupModelGroup,Provider,ProviderModelMapping
from app.schemas.models import ModelGroupInput,protocol_category
from app.api.admin.model_mappings import config_lock
from app.services.sessions import audit
router=APIRouter(prefix='/api/admin/model-groups',tags=['模型组'])


async def group_data(db,row):
    members=(await db.scalars(select(ModelGroupModel.logical_model).where(ModelGroupModel.model_group_id==row.id).order_by(ModelGroupModel.position))).all()
    return {**{f:getattr(row,f) for f in ('id','name','description','status','protocol_type','created_at','balancing_strategy','max_retries','attempt_timeout','retry_uncertain','node_weights')},'logical_models':list(members)}


@router.get('')
async def listing(actor=Depends(administrator),db=Depends(get_session),page: int=Query(1,ge=1),page_size: int=Query(20,ge=1,le=100),q: str=Query('',max_length=80),protocol_type: str=Query('',pattern=r'^(text|multimodal|image|vector)?$')):
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


@router.get('/{group_id}/nodes')
async def nodes(group_id:int,hours:int=Query(24,ge=1,le=168),actor=Depends(administrator),db=Depends(get_session)):
    row=await target(db,group_id)
    members=select(ModelGroupModel.logical_model).where(ModelGroupModel.model_group_id==group_id)
    pairs=(await db.execute(select(ProviderModelMapping,Provider).join(Provider).where(
        ProviderModelMapping.logical_model.in_(members),ProviderModelMapping.deleted_at.is_(None),Provider.deleted_at.is_(None)
    ).order_by(Provider.id,ProviderModelMapping.id))).all()
    from app.gateway.provider_concurrency import loads
    from app.gateway.provider_health import state
    counts=await loads([p for m,p in pairs])
    # Historical attempts include failed nodes, unlike the final provider_id column.
    stats=(await db.execute(text("""
        SELECT a->>'provider_id' AS provider_id,a->>'logical_model' AS logical_model,
          count(*) AS requests,count(*) FILTER (WHERE a->>'status'='success') AS successes,
          avg(CASE WHEN jsonb_typeof(a->'elapsed_ms')='number' THEN (a->>'elapsed_ms')::double precision END) AS avg_ms
        FROM call_logs l CROSS JOIN LATERAL jsonb_array_elements(
          CASE WHEN jsonb_typeof(l.trace->'attempts')='array' THEN l.trace->'attempts' ELSE '[]'::jsonb END) a
        WHERE l.created_at>=now()-(:hours * interval '1 hour')
          AND a->>'status' IN ('success','failure','client_cancelled')
          AND a->>'elapsed_ms' IS NOT NULL
          AND (a->>'logical_model') IN (SELECT logical_model FROM model_group_models WHERE model_group_id=:group_id)
        GROUP BY a->>'provider_id',a->>'logical_model'
    """),{'hours':hours,'group_id':group_id})).mappings().all()
    metrics={(r['provider_id'],r['logical_model']):r for r in stats}
    items=[]
    for m,p in pairs:
        stat=metrics.get((str(p.id),m.logical_model),{})
        requests=stat.get('requests',0);successes=stat.get('successes',0)
        items.append({'mapping_id':m.id,'provider_id':p.id,'provider_name':p.name,'logical_model':m.logical_model,
            'upstream_model':m.upstream_model,'mapping_status':m.status,'status':p.status,'health':state(p),
            'weight':(row.node_weights or {}).get(str(p.id),1),'priority':p.priority,'max_concurrency':p.max_concurrency,
            'current_concurrency':counts[p.id],'failure_count':p.failure_count,'cooldown_until':p.cooldown_until,
            'last_error_code':p.last_error_code,'requests':requests,'success_rate':round(successes/requests*100,2) if requests else None,
            'average_latency_ms':round(stat['avg_ms'],2) if stat.get('avg_ms') is not None else None})
    return {'data':{'items':items,'hours':hours,'strategy':row.balancing_strategy}}


async def save(db,actor,request,body,row=None):
    referenced=False
    names=body.logical_models
    if body.node_weights:
        valid=set(str(x) for x in (await db.scalars(select(ProviderModelMapping.provider_id).join(Provider).where(
            ProviderModelMapping.logical_model.in_(names),ProviderModelMapping.deleted_at.is_(None),Provider.deleted_at.is_(None)))).all())
        if set(body.node_weights)-valid:raise APIError(422,'INVALID_BALANCING_NODE','权重只能配置当前模型组已有的供应商节点')
    found={m.name:m for m in (await db.scalars(select(LogicalModel).where(LogicalModel.name.in_(names)))).all()}
    category=body.protocol_type
    if category is None:
        if len(found)!=len(names): raise APIError(400,'LOGICAL_MODEL_NOT_FOUND','自定义模型名需要先选择协议类型')
        categories={protocol_category(m.model_type) for m in found.values()}
        category=next(iter(categories)) if len(categories)==1 else None
    else:
        # Preserve existing text groups containing multimodal Chat models.
        # Explicit multimodal groups must contain multimodal models only.
        if any((m.model_type!='multimodal' if category=='multimodal' else protocol_category(m.model_type)!=category) for m in found.values()):
            raise APIError(409,'MODEL_GROUP_TYPE_CONFLICT','模型与分组协议类型不一致')
        for name in names:
            if name not in found:db.add(LogicalModel(name=name,model_type={'text':'text','multimodal':'multimodal','image':'image','vector':'embedding'}[category]))
    if row:
        from app.models.routing import RouteConfig
        referenced=bool(await db.scalar(select(RouteConfig.id).where((RouteConfig.simple_model_group==row.id)|(RouteConfig.complex_model_group==row.id)).limit(1)))
        if referenced:
            if category not in (None,'text','multimodal'):
                raise APIError(409,'MODEL_GROUP_IN_USE','智能路由引用的分组必须保持文本或多模态对话类型')
            virtual=set((await db.scalars(select(RouteConfig.virtual_model))).all())
            if virtual.intersection(names):
                raise APIError(409,'ROUTE_RECURSION','路由目标模型组不能加入虚拟路由模型')
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
        if referenced:
            # Apply the same target invariants as route creation, including
            # enabled status and at least one usable real Chat mapping.
            from app.api.admin.smart_route import real_members
            await real_members(db,row.id)
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
        raise APIError(409,'MODEL_GROUP_IN_USE','模型组已被智能路由引用，请先修改路由配置')
    if await db.scalar(select(UserGroupModelGroup.user_group_id).where(UserGroupModelGroup.model_group_id==group_id).limit(1)):
        raise APIError(409,'MODEL_GROUP_IN_USE','模型组已授权给用户组，请先取消关联')
    try:
        await db.delete(row);audit(db,actor.id,'delete_model_group',group_id,request.client.host,resource_type='model_group');await db.commit()
    except IntegrityError:
        await db.rollback();raise APIError(409,'MODEL_GROUP_IN_USE','模型组已被引用，无法删除') from None
    return {'data':{'message':'模型组已删除'}}
