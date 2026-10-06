"""Live catalog permission checks and eligible mapping query shared with future scheduler."""
from sqlalchemy import select,exists,or_
from app.core.exceptions import APIError
from app.core.security import now
from app.models.user import LogicalModel,ProviderModelMapping,Provider,ModelGroup,ModelGroupModel,UserGroupModelGroup,UserGroup


def eligible_query():
    return select(ProviderModelMapping,Provider).join(Provider,Provider.id==ProviderModelMapping.provider_id).where(
        ProviderModelMapping.status=='enabled',ProviderModelMapping.deleted_at.is_(None),Provider.status=='enabled',Provider.deleted_at.is_(None),
        Provider.health_status!='unhealthy',or_(Provider.cooldown_until.is_(None),Provider.cooldown_until<=now()))


async def candidates(db,logical_model):
    return (await db.execute(eligible_query().where(ProviderModelMapping.logical_model==logical_model).order_by(Provider.priority.asc(),Provider.id))).all()


async def allowed_groups(db,user_group_id):
    from app.services.group_access import resolve_group
    group=await resolve_group(db,user_group_id)
    if not group or group.status!='enabled': return []
    if group.model_access=='all':
        return (await db.scalars(select(ModelGroup).where(ModelGroup.status=='enabled').order_by(ModelGroup.id))).all()
    return (await db.scalars(select(ModelGroup).join(UserGroupModelGroup,UserGroupModelGroup.model_group_id==ModelGroup.id)
        .where(UserGroupModelGroup.user_group_id==group.id,ModelGroup.status=='enabled').order_by(ModelGroup.id))).all()


async def authorized_candidates(db,user_group_id,logical_model):
    from app.services.group_access import resolve_group
    group=await resolve_group(db,user_group_id)
    groups=await allowed_groups(db,user_group_id)
    ids=[g.id for g in groups]
    authorized=await db.scalar(select(exists().where(ModelGroupModel.model_group_id.in_(ids),ModelGroupModel.logical_model==logical_model)))
    if not authorized and not (group and group.status=='enabled' and group.model_access=='all' and await db.get(LogicalModel,logical_model)):
        raise APIError(403,'MODEL_FORBIDDEN','用户组无权访问该逻辑模型')
    rows=await candidates(db,logical_model)
    if not rows: raise APIError(503,'NO_AVAILABLE_PROVIDER','该模型暂时没有可用的上游映射')
    return rows


async def catalog(db,user_group_id):
    from app.services.group_access import resolve_group
    access=await resolve_group(db,user_group_id)
    unrestricted=bool(access and access.status=='enabled' and access.model_access=='all')
    extra=[]
    if unrestricted:
        rows=(await db.execute(eligible_query())).all()
        names={mapping.logical_model for mapping,provider in rows}
        models=(await db.scalars(select(LogicalModel).where(LogicalModel.name.in_(names)).order_by(LogicalModel.name))).all()
        extra=[{'id':0,'name':'全部模型','description':'','models':[{'logical_model':model.name,'model_type':model.model_type,'position':i,'configured':True,'virtual':False} for i,model in enumerate(models)]}]
    groups=await allowed_groups(db,user_group_id)
    ids=[g.id for g in groups]
    if not ids: return extra
    members=(await db.execute(select(ModelGroupModel,LogicalModel).join(LogicalModel,LogicalModel.name==ModelGroupModel.logical_model)
        .where(ModelGroupModel.model_group_id.in_(ids)).order_by(ModelGroupModel.model_group_id,ModelGroupModel.position))).all()
    eligible=(await db.execute(eligible_query().where(ProviderModelMapping.logical_model.in_([m.logical_model for m,l in members])))).all()
    available={m.logical_model for m,p in eligible}
    if unrestricted:available.update(model['logical_model'] for model in extra[0]['models'])
    from app.models.routing import RouteConfig,RouteSample,RouteVector
    virtual_query=select(RouteConfig)
    if not unrestricted:virtual_query=virtual_query.where(RouteConfig.virtual_model.in_([m.logical_model for m,l in members]))
    virtual_rows=(await db.scalars(virtual_query)).all()
    virtual_names={cfg.virtual_model for cfg in virtual_rows}
    from app.api.admin.smart_route import real_members
    from app.services.operations_settings import governance
    for cfg in virtual_rows:
        if not governance['smart_route_enabled'] or cfg.status!='enabled':continue
        if cfg.embedding_model not in available or not {cfg.simple_model_group,cfg.complex_model_group}.issubset(set(ids)):continue
        from app.services.vector_service import pin
        from app.providers.operations import compatible
        if not any(compatible('embeddings',p) for m,p in pin(await candidates(db,cfg.embedding_model),cfg.embedding_model)):continue
        try:
            for ident in (cfg.simple_model_group,cfg.complex_model_group):await real_members(db,ident)
        except APIError:continue
        ready=await db.scalar(select(RouteSample.id).join(RouteVector,RouteVector.sample_id==RouteSample.id).where(
            RouteSample.config_id==cfg.id,RouteSample.vector_status=='ready',RouteSample.revision==RouteVector.sample_revision,
            RouteVector.vector_generation==cfg.vector_generation,RouteVector.embedding_model==cfg.embedding_model).limit(1))
        if ready or cfg.fallback!='error':available.add(cfg.virtual_model)
    if unrestricted:
        for cfg in virtual_rows:
            if cfg.virtual_model in available and await db.get(LogicalModel,cfg.virtual_model):
                extra[0]['models'].append({'logical_model':cfg.virtual_model,'model_type':'text','position':len(extra[0]['models']),'configured':True,'virtual':True})
    return extra+[{'id':g.id,'name':g.name,'description':g.description,'models':[{'logical_model':m.logical_model,'model_type':l.model_type,'position':m.position,
        'configured':m.logical_model in available,'virtual':m.logical_model in virtual_names} for m,l in members if m.model_group_id==g.id]} for g in groups]

