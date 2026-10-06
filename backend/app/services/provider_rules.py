"""Shared account/mapping invariants for bundled and individual editors."""
from sqlalchemy import select
from app.models.user import Provider,ProviderModelMapping
from app.models.routing import RouteConfig
from app.schemas.models import protocol_category
from app.providers.operations import compatible
from app.core.exceptions import APIError

def category_mapping(account,item):
    if account.protocol_type and protocol_category(item.model_type)!=account.protocol_type:
        raise APIError(422,'PROVIDER_MODEL_TYPE_MISMATCH','模型映射类型须与账号协议类型一致')

async def protect_removed(db,account,names):
    if not names:return
    referenced=set((await db.scalars(select(RouteConfig.embedding_model).where(RouteConfig.embedding_model.in_(names)))).all())
    for name in referenced:
        others=(await db.execute(select(ProviderModelMapping,Provider).join(Provider,Provider.id==ProviderModelMapping.provider_id)
            .where(ProviderModelMapping.logical_model==name,ProviderModelMapping.model_type=='embedding',
                ProviderModelMapping.status=='enabled',ProviderModelMapping.deleted_at.is_(None),
                Provider.id!=account.id,Provider.deleted_at.is_(None),Provider.status=='enabled'))).all()
        if not any(compatible('embeddings',p) for m,p in others):
            raise APIError(409,'PROVIDER_IN_USE','账号的向量模型 '+name+' 正被智能路由引用；请先替换向量服务或移除相关规则')
