from fastapi import APIRouter,Depends,Request
from sqlalchemy import select,update
from app.core.database import get_session
from app.core.dependencies import super_administrator
from app.core.exceptions import APIError
from app.models.user import SystemSetting
from app.schemas.settings import SettingsPatch,Basic,GatewayOptions,SecurityOptions,LogOptions,VectorOptions,GovernanceOptions,ElasticsearchOptions
from app.services import operations_settings as operations
from app.services.sessions import audit

router=APIRouter(tags=['系统设置'])


@router.get('/api/admin/settings/system-status')
async def system_status(actor=Depends(super_administrator)):
    from app.services.system_status import snapshot
    return {'data':await snapshot()}


@router.get('/api/public/settings')
async def public():return {'data':operations.public()}


@router.get('/api/admin/settings')
async def read(actor=Depends(super_administrator),db=Depends(get_session)):
    return {'data':await operations.document(db)}


@router.patch('/api/admin/settings')
async def save(body:SettingsPatch,request:Request,actor=Depends(super_administrator),db=Depends(get_session)):
    from app.api.admin.model_mappings import config_lock
    await config_lock(db)
    row=await db.scalar(select(SystemSetting).where(SystemSetting.key=='operations').with_for_update())
    if row is None:raise APIError(503,'SETTINGS_UNAVAILABLE','系统设置尚未初始化')
    current=await operations.document(db,private=True)
    if current['revision']!=body.revision:raise APIError(409,'SETTINGS_CHANGED','配置已被更新，请重新加载')
    for name,model in [('basic',Basic),('gateway',GatewayOptions),('security',SecurityOptions),('logging',LogOptions),('governance',GovernanceOptions)]:
        section=getattr(body,name)
        if section is not None:current[name]=model.model_validate({**current[name],**section.model_dump(exclude_unset=True)}).model_dump()
    if body.vector is not None:
        from app.models.user import Provider,ProviderModelMapping
        from app.models.routing import RouteConfig,RouteSample
        from app.models.compliance import AuditSample
        from app.providers.operations import compatible
        chosen=body.vector.model_dump()
        if bool(chosen['provider_id'])!=bool(chosen['model']):raise APIError(400,'VECTOR_CONFIG_INVALID','向量账号与模型须同时填写或同时清空')
        if chosen['provider_id']:
            provider=await db.get(Provider,chosen['provider_id'])
            mapping=await db.scalar(select(ProviderModelMapping).where(ProviderModelMapping.provider_id==chosen['provider_id'],ProviderModelMapping.logical_model==chosen['model'],ProviderModelMapping.status=='enabled',ProviderModelMapping.deleted_at.is_(None),ProviderModelMapping.model_type=='embedding'))
            if not provider or provider.deleted_at or provider.status!='enabled' or not mapping or not compatible('embeddings',provider):raise APIError(400,'VECTOR_CONFIG_INVALID','请选择已启用且支持向量协议的账号和模型')
        if chosen!=current['vector']:
            if not chosen['model'] and current['vector'].get('model'):
                raise APIError(409,'VECTOR_IN_USE','共享向量服务已配置；请替换账号或模型，不可直接清空')
            if chosen['model']:
                for route in (await db.scalars(select(RouteConfig).with_for_update())).all():
                    if route.virtual_model==chosen['model']:raise APIError(409,'VECTOR_MODEL_CONFLICT','向量模型不可与虚拟模型重名')
                    route.embedding_model=chosen['model'];route.vector_generation+=1
                await db.execute(update(RouteSample).values(vector_status='stale',vector_requested=False,revision=RouteSample.revision+1,job_started_at=None,vector_error=None,vector_request_id=None))
                await db.execute(update(AuditSample).values(vector_status='failed',vector_error='VECTOR_CONFIG_CHANGED',revision=AuditSample.revision+1,job_started_at=None))
            current['vector']=chosen
    if body.elasticsearch is not None:
        from app.services.provider_crypto import encrypt_secret
        old=current['elasticsearch'];incoming=body.elasticsearch.model_dump()
        secret=incoming.pop('secret');encrypted=encrypt_secret(secret) if secret else old.get('secret_encrypted')
        if not secret and encrypted and any(incoming[k]!=old.get(k) for k in ('url','auth_type','username')):
            raise APIError(400,'ES_SECRET_REQUIRED','变更服务地址或认证方式时，请重新填写认证密钥')
        if incoming['enabled'] and (not incoming['url'] or not encrypted or incoming['auth_type']=='basic' and not incoming['username']):
            raise APIError(400,'ES_CONFIG_INVALID','启用 Elasticsearch 前请填写地址与认证信息')
        current['elasticsearch']={**incoming,'secret_encrypted':encrypted}
    current['revision']+=1
    row.value=current
    # Legacy seed keys stay in sync; assets are stored in the same database snapshot.
    for key in ('system_name','language','timezone'):
        legacy=await db.get(SystemSetting,key)
        if legacy:legacy.value=current['basic'][key]
    audit(db,actor.id,'update_system_settings','operations',request.client.host,resource_type='system_settings')
    await db.commit()
    operations.apply(current)
    return {'data':await operations.document(db)}


@router.get('/api/admin/settings/vector-options')
async def vector_options(actor=Depends(super_administrator),db=Depends(get_session)):
    from app.models.user import Provider,ProviderModelMapping
    from app.providers.operations import compatible
    rows=(await db.execute(select(ProviderModelMapping,Provider).join(Provider,Provider.id==ProviderModelMapping.provider_id).where(
        Provider.status=='enabled',Provider.deleted_at.is_(None),ProviderModelMapping.status=='enabled',ProviderModelMapping.deleted_at.is_(None),ProviderModelMapping.model_type=='embedding').order_by(Provider.id,ProviderModelMapping.id))).all()
    return {'data':[{'provider_id':p.id,'provider_name':p.name,'model':m.logical_model,'upstream_model':m.upstream_model} for m,p in rows if compatible('embeddings',p)]}


@router.get('/api/admin/settings/elasticsearch/status')
async def es_status(actor=Depends(super_administrator)):
    from app.services.external_logs import status
    return {'data':await status()}


@router.post('/api/admin/settings/elasticsearch/test')
async def es_test(request:Request,actor=Depends(super_administrator),db=Depends(get_session)):
    from app.services.external_logs import test_connection
    audit(db,actor.id,'test_elasticsearch','operations',request.client.host,resource_type='system_settings')
    await db.commit()
    return {'data':await test_connection()}


from pydantic import BaseModel,ConfigDict,Field
from typing import Literal
class VectorTest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    consent:Literal[True]
    revision:int=Field(ge=0)

@router.post('/api/admin/settings/vector-test')
async def vector_test(body:VectorTest,request:Request,actor=Depends(super_administrator),db=Depends(get_session)):
    current=await operations.document(db)
    if body.revision!=current['revision']:raise APIError(409,'SETTINGS_CHANGED','配置已更新，请重新加载')
    if not current['vector']['model']:raise APIError(400,'VECTOR_NOT_CONFIGURED','请先保存向量服务配置')
    from app.services.admin_embedding import embedding
    audit(db,actor.id,'test_vector_service','operations',request.client.host,resource_type='system_settings');await db.commit()
    vector,request_id=await embedding(actor.id,current['vector']['model'],'test',request.client.host)
    return {'data':{'dimensions':len(vector),'request_id':request_id,'success':True}}
