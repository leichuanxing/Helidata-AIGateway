from datetime import timedelta
from typing import Literal
from fastapi import APIRouter,Depends,Query,Request
from sqlalchemy import select,delete,func,text
from sqlalchemy.exc import IntegrityError
from app.core.database import get_session
from app.core.dependencies import administrator
from app.core.exceptions import APIError
from app.core.security import now
from app.models.balance import BalancedRoute,BalancedNode
from app.models.user import LogicalModel,ProviderModelMapping,Provider,ModelGroupModel
from app.schemas.balance import RouteInput,matching_type
from app.api.admin.model_mappings import config_lock
from app.services.sessions import audit
from app.services.balance_capabilities import operation_for

router=APIRouter(prefix='/api/admin/balance-routes',tags=['负载均衡路由'])

def public(row):return {c.name:getattr(row,c.name) for c in row.__table__.columns}

async def target(db,ident,lock=False):
    query=select(BalancedRoute).where(BalancedRoute.id==ident)
    row=await db.scalar(query.with_for_update() if lock else query)
    if not row:raise APIError(404,'BALANCE_NOT_FOUND','路由组不存在')
    return row

@router.get('/options')
async def options(actor=Depends(administrator),db=Depends(get_session)):
    rows=(await db.execute(select(ProviderModelMapping,Provider).join(Provider).where(
        ProviderModelMapping.deleted_at.is_(None),Provider.deleted_at.is_(None)).order_by(Provider.name,ProviderModelMapping.id))).all()
    return {'data':[{'mapping_id':m.id,'provider_id':p.id,'provider_name':p.name,'logical_model':m.logical_model,
        'upstream_model':m.upstream_model,'model_type':m.model_type,'status':m.status,'provider_status':p.status,'provider_max_concurrency':p.max_concurrency,
        'usable':m.status=='enabled' and p.status=='enabled' and operation_for(m.model_type,p) is not None} for m,p in rows]}

@router.get('')
async def listing(q:str=Query('',max_length=100),page:int=Query(1,ge=1,le=10000),page_size:int=Query(20,ge=1,le=100),status:Literal['','enabled','disabled']='',model_type:Literal['','text','reasoning','multimodal','embedding','rerank','image']='',strategy:Literal['','round_robin','weighted_round_robin','least_concurrency','random','priority']='',actor=Depends(administrator),db=Depends(get_session)):
    query=select(BalancedRoute,LogicalModel.model_type).join(LogicalModel,LogicalModel.name==BalancedRoute.model_name)
    if q:query=query.where(BalancedRoute.name.icontains(q,autoescape=True)|BalancedRoute.model_name.icontains(q,autoescape=True))
    if status:query=query.where(BalancedRoute.status==status)
    if model_type:query=query.where(LogicalModel.model_type==model_type)
    if strategy:query=query.where(BalancedRoute.strategy==strategy)
    total=await db.scalar(select(func.count()).select_from(query.subquery()))
    rows=(await db.execute(query.order_by(BalancedRoute.id).offset((page-1)*page_size).limit(page_size))).all()
    counts=dict((await db.execute(select(BalancedNode.route_id,func.count()).group_by(BalancedNode.route_id))).all())
    return {'data':{'items':[{**public(r),'model_type':kind,'node_count':counts.get(r.id,0)} for r,kind in rows],'total':total}}

async def detail_data(db,row,hours=24):
    from app.core.redis import redis_client
    from app.gateway.provider_concurrency import LOAD,key
    from app.gateway.balanced_routing import node_key,route_key
    model=await db.get(LogicalModel,row.model_name)
    rows=(await db.execute(select(BalancedNode,ProviderModelMapping,Provider).join(ProviderModelMapping,ProviderModelMapping.id==BalancedNode.mapping_id)
        .join(Provider,Provider.id==ProviderModelMapping.provider_id).where(BalancedNode.route_id==row.id).order_by(BalancedNode.id))).all()
    from redis.exceptions import RedisError
    try:
        async with redis_client.pipeline(transaction=False) as pipe:
            pipe.eval(LOAD,1,route_key(row.id))
            for n,m,p in rows:pipe.eval(LOAD,1,node_key(n.id));pipe.eval(LOAD,1,key(p.id))
            loads=await pipe.execute()
    except RedisError:loads=[None]*(1+len(rows)*2)
    metrics=(await db.execute(text("""
        SELECT a->>'balance_node_id' AS node_id,count(*) AS requests,
          count(*) FILTER (WHERE a->>'status'='success') AS successes,
          count(*) FILTER (WHERE a->>'status'='failure') AS failures,
          count(*) FILTER (WHERE a->>'status'='client_cancelled') AS cancellations,
          avg(CASE WHEN jsonb_typeof(a->'elapsed_ms')='number' THEN (a->>'elapsed_ms')::double precision END) AS latency
        FROM call_logs l CROSS JOIN LATERAL jsonb_array_elements(
          CASE WHEN jsonb_typeof(trace->'attempts')='array' THEN trace->'attempts' ELSE '[]'::jsonb END) a
        WHERE l.created_at>=now()-(:hours * interval '1 hour') AND a->>'balance_route_id'=:route_id
          AND a->>'status' IN ('success','failure','client_cancelled') AND a->>'elapsed_ms' IS NOT NULL
        GROUP BY a->>'balance_node_id'
    """),{'hours':hours,'route_id':str(row.id)})).mappings().all()
    stats={r['node_id']:r for r in metrics};nodes=[]
    for i,(n,m,p) in enumerate(rows):
        metric=stats.get(str(n.id),{});requests=metric.get('requests',0)
        disabled=n.status!='enabled' or p.status!='enabled' or m.status!='enabled' or p.deleted_at or m.deleted_at
        from app.schemas.balance import matching_type
        invalid=not matching_type(model.model_type,m.model_type) or operation_for(model.model_type,p) is None
        state='disabled' if disabled else 'invalid' if invalid else 'unavailable' if p.health_status=='unhealthy' else 'cooling' if (n.cooldown_until and n.cooldown_until>now() or p.cooldown_until and p.cooldown_until>now()) else 'probe' if n.cooldown_until else n.health_status
        nodes.append({**public(n),'provider_id':p.id,'provider_name':p.name,'logical_model':m.logical_model,'upstream_model':m.upstream_model,
            'model_type':m.model_type,'state':state,'provider_health':p.health_status,'provider_max_concurrency':p.max_concurrency,
            'current_concurrency':loads[1+i*2],'provider_concurrency':loads[2+i*2],'requests':requests,
            'successes':metric.get('successes',0),'failures':metric.get('failures',0),'cancellations':metric.get('cancellations',0),
            'effective_max_concurrency':min(1 if n.cooldown_until else n.max_concurrency,p.max_concurrency,row.max_concurrency),
            'success_rate':round(metric.get('successes',0)/requests*100,2) if requests else None,
            'average_latency_ms':round(metric['latency'],2) if metric.get('latency') is not None else None})
    return {**public(row),'model_type':model.model_type,'nodes':nodes,'current_concurrency':loads[0],'hours':hours}

@router.get('/{ident}')
async def detail(ident:int,hours:int=Query(24,ge=1,le=168),actor=Depends(administrator),db=Depends(get_session)):
    return {'data':await detail_data(db,await target(db,ident),hours)}

async def save(body,request,actor,db,row=None):
    await config_lock(db)
    if row:
        row=await target(db,row.id,True)
        if body.expected_config_version is None or body.expected_config_version!=row.config_version:raise APIError(409,'BALANCE_CHANGED','配置已变化，请重新加载')
        if row.model_name!=body.model_name:raise APIError(409,'BALANCE_NAME_IMMUTABLE','统一模型名称不可修改，请新建路由组')
        alias=await db.get(LogicalModel,row.model_name)
        if alias.model_type!=body.model_type:raise APIError(409,'BALANCE_TYPE_IMMUTABLE','统一模型类型不可修改，请新建路由组')
    else:
        if await db.get(LogicalModel,body.model_name):raise APIError(409,'MODEL_NAME_CONFLICT','统一模型名称已被占用')
        if (await db.scalar(select(func.count()).select_from(BalancedRoute)))>=100:raise APIError(422,'BALANCE_LIMIT','最多100个路由组')
    ids=[n.mapping_id for n in body.nodes]
    retained=set((await db.scalars(select(BalancedNode.mapping_id).where(BalancedNode.route_id==row.id))).all()) if row else set()
    mappings=(await db.execute(select(ProviderModelMapping,Provider).join(Provider).where(ProviderModelMapping.id.in_(ids)))).all()
    if len(mappings)!=len(ids):raise APIError(422,'BALANCE_MAPPING_INVALID','存在已删除或无效的模型实例')
    if any((m.deleted_at or p.deleted_at) and m.id not in retained for m,p in mappings):
        raise APIError(422,'BALANCE_MAPPING_INVALID','不能添加已删除的模型实例')
    enabled_ids={n.mapping_id for n in body.nodes if n.status=='enabled'}
    relevant=[(m,p) for m,p in mappings if not m.deleted_at and not p.deleted_at and (m.id not in retained or body.status=='enabled' and m.id in enabled_ids)]
    if any(not matching_type(body.model_type,m.model_type) for m,p in relevant):raise APIError(422,'BALANCE_TYPE_CONFLICT','节点模型类型与统一模型类型不一致')
    if any(m.id in enabled_ids and operation_for(body.model_type,p) is None for m,p in relevant):
        raise APIError(422,'BALANCE_PROTOCOL_UNSUPPORTED','存在协议不支持当前模型类型的节点，请修正供应商配置或停用节点')
    values=body.model_dump(exclude={'nodes','model_type','expected_config_version'})
    action='update_balance_route' if row else 'create_balance_route'
    try:
        if row:
            for field,value in values.items():setattr(row,field,value)
            row.config_version+=1
        else:
            db.add(LogicalModel(name=body.model_name,model_type=body.model_type));await db.flush()
            row=BalancedRoute(**values);db.add(row);await db.flush()
        existing={n.mapping_id:n for n in (await db.scalars(select(BalancedNode).where(BalancedNode.route_id==row.id))).all()}
        for mapping_id,node in existing.items():
            if mapping_id not in ids:await db.delete(node)
        for wanted in body.nodes:
            node=existing.get(wanted.mapping_id)
            if node is None:
                node=BalancedNode(route_id=row.id,**wanted.model_dump());db.add(node)
            else:
                for field,value in wanted.model_dump().items():setattr(node,field,value)
            node.next_check_at=now()+timedelta(seconds=body.health_interval)
        await db.flush();await db.refresh(row)
        result={**public(row),'model_type':body.model_type}
        audit(db,actor.id,action,row.id,request.client.host,resource_type='balance_route');await db.commit()
        return {'data':result}
    except IntegrityError:
        await db.rollback();raise APIError(409,'BALANCE_CONFLICT','路由组名称或模型配置冲突') from None

@router.post('',status_code=201)
async def create(body:RouteInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
    return await save(body,request,actor,db)

@router.put('/{ident}')
async def edit(ident:int,body:RouteInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
    return await save(body,request,actor,db,await target(db,ident))

@router.delete('/{ident}')
async def remove(ident:int,request:Request,actor=Depends(administrator),db=Depends(get_session)):
    await config_lock(db);row=await target(db,ident,True)
    if await db.scalar(select(ModelGroupModel.model_group_id).where(ModelGroupModel.logical_model==row.model_name).limit(1)):
        raise APIError(409,'BALANCE_IN_USE','请先从模型组中移除统一模型授权关联')
    name=row.model_name;await db.execute(delete(BalancedNode).where(BalancedNode.route_id==ident));await db.delete(row);await db.flush()
    await db.execute(delete(LogicalModel).where(LogicalModel.name==name))
    audit(db,actor.id,'delete_balance_route',ident,request.client.host,resource_type='balance_route');await db.commit()
    return {'data':{'message':'已删除，历史调用日志保留'}}

@router.post('/{ident}/nodes/{node_id}/check')
async def check(ident:int,node_id:int,request:Request,actor=Depends(administrator),db=Depends(get_session)):
    await target(db,ident)
    node=await db.get(BalancedNode,node_id)
    if not node or node.route_id!=ident:raise APIError(404,'BALANCE_NODE_NOT_FOUND','节点不存在')
    await db.commit()
    from app.services.balance_health import probe
    result=await probe(ident,node_id)
    audit(db,actor.id,'check_balance_node',node_id,request.client.host,result='success' if result['success'] else 'failure',resource_type='balance_node');await db.commit()
    return {'data':result}
