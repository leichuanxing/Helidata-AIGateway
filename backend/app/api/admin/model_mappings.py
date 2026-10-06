from fastapi import APIRouter,Depends,Request
from sqlalchemy import select,text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from app.core.database import get_session
from app.core.dependencies import administrator
from app.core.exceptions import APIError
from app.core.security import now
from app.models.user import Provider,LogicalModel,ProviderModelMapping
from app.schemas.models import MappingInput,public_mapping
from app.providers.registry import build_adapter
from app.providers.base import ProviderFailure
from app.services.provider_crypto import decrypt_secret
from app.services.sessions import audit
router=APIRouter(prefix='/api/admin',tags=['模型映射'])


async def config_lock(db):
    await db.execute(text('SELECT pg_advisory_xact_lock(71006)'))


async def provider(db,provider_id,lock=False):
    query=select(Provider).where(Provider.id==provider_id,Provider.deleted_at.is_(None))
    if lock: query=query.with_for_update()
    row=await db.scalar(query)
    if not row: raise APIError(404,'PROVIDER_NOT_FOUND','账号不存在')
    return row


async def canonical(db,name,model_type):
    from app.models.routing import RouteConfig
    if await db.scalar(select(RouteConfig.id).where(RouteConfig.virtual_model==name)):
        raise APIError(409,'ROUTE_NAME_CONFLICT','虚拟模型不能配置上游映射')
    await db.execute(insert(LogicalModel).values(name=name,model_type=model_type).on_conflict_do_nothing(index_elements=['name']))
    row=await db.get(LogicalModel,name)
    if row.model_type!=model_type: raise APIError(409,'MODEL_TYPE_CONFLICT','同一逻辑模型的类型必须一致')


@router.post('/providers/{provider_id}/discover-models')
async def discover(provider_id: int,request: Request,actor=Depends(administrator),db=Depends(get_session)):
    row=await provider(db,provider_id)
    if row.status!='enabled': raise APIError(409,'PROVIDER_DISABLED','请先启用账号，再发现模型；禁用账号可手工配置映射')
    version=row.config_version
    adapter=build_adapter(row,decrypt_secret(row.api_key_encrypted))
    await db.commit()
    try:
        rows=await adapter.list_models()
        names=list(dict.fromkeys(r['id'] for r in rows))
        if any(not n.strip() or len(n)>200 or any(ord(c)<32 for c in n) for n in names):
            raise ProviderFailure('UPSTREAM_INVALID_RESPONSE',adapter.http_status,True,'unknown',adapter.latency_ms)
    except ProviderFailure as error:
        audit(db,actor.id,'discover_models',provider_id,request.client.host,result='failure',resource_type='provider')
        await db.commit()
        raise APIError(502,error.code,'上游模型发现失败，可检查连接或手工输入真实模型名') from None
    await db.refresh(row)
    if row.config_version!=version or row.status!='enabled' or row.deleted_at:
        raise APIError(409,'PROVIDER_CHANGED','发现期间账号配置已变化，请重新发现')
    audit(db,actor.id,'discover_models',provider_id,request.client.host,resource_type='provider')
    await db.commit()
    return {'data':{'models':[{'id':n} for n in names],'http_status':adapter.http_status,'latency_ms':adapter.latency_ms}}


@router.get('/logical-models')
async def logical_models(actor=Depends(administrator),db=Depends(get_session)):
    rows=(await db.scalars(select(LogicalModel).order_by(LogicalModel.name))).all()
    return {'data':[{'name':r.name,'model_type':r.model_type} for r in rows]}


@router.get('/providers/{provider_id}/model-mappings')
async def mappings(provider_id: int,actor=Depends(administrator),db=Depends(get_session)):
    await provider(db,provider_id)
    rows=(await db.scalars(select(ProviderModelMapping).where(ProviderModelMapping.provider_id==provider_id,ProviderModelMapping.deleted_at.is_(None)).order_by(ProviderModelMapping.id))).all()
    return {'data':[public_mapping(r) for r in rows]}


@router.post('/providers/{provider_id}/model-mappings',status_code=201)
async def create(provider_id: int,body: MappingInput,request: Request,actor=Depends(administrator),db=Depends(get_session)):
    await config_lock(db);account=await provider(db,provider_id,True)
    await canonical(db,body.logical_model,body.model_type)
    row=ProviderModelMapping(provider_id=provider_id,**body.model_dump());db.add(row)
    try:
        await db.flush();await db.refresh(row)
        account.config_version+=1
        audit(db,actor.id,'create_model_mapping',row.id,request.client.host,resource_type='model_mapping')
        await db.commit()
    except IntegrityError:
        await db.rollback();raise APIError(409,'MAPPING_EXISTS','该账号已有此逻辑模型映射') from None
    return {'data':public_mapping(row)}


async def mapping(db,provider_id,mapping_id):
    await config_lock(db);account=await provider(db,provider_id,True)
    row=await db.scalar(select(ProviderModelMapping).where(ProviderModelMapping.id==mapping_id,ProviderModelMapping.provider_id==provider_id,ProviderModelMapping.deleted_at.is_(None)).with_for_update())
    if not row: raise APIError(404,'MAPPING_NOT_FOUND','映射不存在')
    account.config_version+=1
    return row


@router.put('/providers/{provider_id}/model-mappings/{mapping_id}')
async def edit(provider_id: int,mapping_id: int,body: MappingInput,request: Request,actor=Depends(administrator),db=Depends(get_session)):
    row=await mapping(db,provider_id,mapping_id);await canonical(db,body.logical_model,body.model_type)
    for f,v in body.model_dump().items(): setattr(row,f,v)
    try:
        await db.flush();await db.refresh(row)
        audit(db,actor.id,'update_model_mapping',row.id,request.client.host,resource_type='model_mapping');await db.commit()
    except IntegrityError:
        await db.rollback();raise APIError(409,'MAPPING_EXISTS','该账号已有此逻辑模型映射') from None
    return {'data':public_mapping(row)}


@router.delete('/providers/{provider_id}/model-mappings/{mapping_id}')
async def remove(provider_id: int,mapping_id: int,request: Request,actor=Depends(administrator),db=Depends(get_session)):
    row=await mapping(db,provider_id,mapping_id);row.deleted_at=now();row.status='disabled'
    audit(db,actor.id,'delete_model_mapping',row.id,request.client.host,resource_type='model_mapping');await db.commit()
    return {'data':{'message':'映射已删除，历史记录保留'}}
