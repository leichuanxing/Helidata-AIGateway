from app.core.exceptions import APIError
from app.services.model_catalog import candidates,allowed_groups
from sqlalchemy import select
from app.models.user import ModelGroupModel,LogicalModel
from app.providers.operations import KINDS,TEXT,compatible


async def routes(db,ctx):
    groups=await allowed_groups(db,ctx.group.id)
    if ctx.route_group_id is not None:
        from app.models.routing import RouteConfig
        from app.gateway.smart_routing import authorize
        from app.api.admin.smart_route import real_members
        cfg=await db.get(RouteConfig,ctx.route_config_id)
        if not cfg or cfg.status!='enabled' or cfg.virtual_model!=ctx.original_model or ctx.route_group_id not in (cfg.simple_model_group,cfg.complex_model_group):
            raise APIError(409,'ROUTE_CHANGED','路由规则已变化')
        await authorize(db,ctx,cfg)
        group,names=await real_members(db,ctx.route_group_id,ctx.operation)
        result=[];incompatible=False
        for name in names:
            rows=list(await candidates(db,name))
            incompatible=incompatible or any(not compatible(ctx.operation,p) for m,p in rows)
            result.append((name,[(m,p) for m,p in rows if compatible(ctx.operation,p)]))
        return result,incompatible
    members=(await db.execute(select(ModelGroupModel,LogicalModel).join(LogicalModel,LogicalModel.name==ModelGroupModel.logical_model)
        .where(ModelGroupModel.model_group_id.in_([group.id for group in groups]))
        .order_by(ModelGroupModel.model_group_id,ModelGroupModel.position))).all()
    origins=[(member,model) for member,model in members if model.name==ctx.logical_model]
    model=origins[0][1] if origins else await db.get(LogicalModel,ctx.logical_model)
    if not origins and not (ctx.group.model_access=='all' and model):
        raise APIError(403,'MODEL_FORBIDDEN','用户组无权访问该逻辑模型')
    kind=model.model_type
    if ctx.operation in KINDS and kind not in KINDS[ctx.operation]:
        raise APIError(400,'MODEL_TYPE_UNSUPPORTED','该逻辑模型类型不支持请求的操作')
    names=[ctx.logical_model]
    if ctx.operation in TEXT:
        for origin,_ in origins:
            for member,model in members:
                if member.model_group_id==origin.model_group_id and member.position>origin.position and model.model_type==kind and model.name not in names:
                    names.append(model.name)
    result=[];incompatible=False
    for name in names:
        rows=list(await candidates(db,name))
        if ctx.operation in KINDS:
            incompatible=incompatible or any(not compatible(ctx.operation,provider) for mapping,provider in rows)
            rows=[(mapping,provider) for mapping,provider in rows if compatible(ctx.operation,provider)]
        result.append((name,rows))
    return result,incompatible

async def select_model(db,ctx):
    ctx.routes,ctx.incompatible=await routes(db,ctx)
    ctx.candidates=[pair for name,pairs in ctx.routes for pair in pairs]
    if not ctx.candidates:
        raise APIError(503,'NO_COMPATIBLE_PROVIDER' if ctx.incompatible else 'NO_AVAILABLE_PROVIDER','该模型及授权后继模型没有可用上游映射')
