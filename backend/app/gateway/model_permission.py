from sqlalchemy import select, exists
from app.core.exceptions import APIError
from app.models.user import ModelGroupModel,LogicalModel
from app.services.model_catalog import allowed_groups


async def check(db, ctx):
    groups = await allowed_groups(db, ctx.group.id)
    ctx.authorized_groups=[{'id':g.id,'name':g.name} for g in groups]
    if ctx.group.model_access=='all' and await db.get(LogicalModel,ctx.original_model or ctx.logical_model):
        return
    allowed = await db.scalar(select(exists().where(
        ModelGroupModel.model_group_id.in_([g.id for g in groups]),
        ModelGroupModel.logical_model == (ctx.original_model or ctx.logical_model))))
    if not allowed:
        raise APIError(403, 'MODEL_FORBIDDEN', '用户组无权访问该逻辑模型')
