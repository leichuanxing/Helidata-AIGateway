"""Shared account/mapping invariants for bundled and individual editors."""
from sqlalchemy import select
from app.models.user import Provider,ProviderModelMapping
from app.models.routing import RouteConfig
from app.schemas.models import protocol_category
from app.providers.operations import compatible
from app.core.exceptions import APIError

def category_mapping(account,item):
    actual=item.model_type if account.protocol_type=='multimodal' else protocol_category(item.model_type)
    if account.protocol_type and actual!=account.protocol_type:
        raise APIError(422,'PROVIDER_MODEL_TYPE_MISMATCH','模型映射类型须与账号协议类型一致')

async def protect_removed(db,account,names):
    if not names:return
    from app.services.operations_settings import vector
    if vector['provider_id']==account.id and vector['model'] in names:
        raise APIError(409,'PROVIDER_IN_USE','账号或向量模型正被共享向量服务引用，请先在系统配置中替换')
    referenced=set((await db.scalars(select(RouteConfig.embedding_model).where(RouteConfig.embedding_model.in_(names)))).all())
    for name in referenced:
        others=(await db.execute(select(ProviderModelMapping,Provider).join(Provider,Provider.id==ProviderModelMapping.provider_id)
            .where(ProviderModelMapping.logical_model==name,ProviderModelMapping.model_type=='embedding',
                ProviderModelMapping.status=='enabled',ProviderModelMapping.deleted_at.is_(None),
                Provider.id!=account.id,Provider.deleted_at.is_(None),Provider.status=='enabled'))).all()
        if not any(compatible('embeddings',p) for m,p in others):
            raise APIError(409,'PROVIDER_IN_USE','账号的向量模型 '+name+' 正被智能路由引用；请先替换向量服务或移除相关规则')

def protect_vector_mapping(account,previous,wanted):
    from app.services.operations_settings import vector
    if vector['provider_id']==account.id and vector['model']==previous.logical_model and wanted.upstream_model!=previous.upstream_model:
        raise APIError(409,'PROVIDER_IN_USE','共享向量服务正在使用此上游模型；请先替换向量服务账号，再修改映射')
