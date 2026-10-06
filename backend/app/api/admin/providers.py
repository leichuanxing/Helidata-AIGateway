from fastapi import APIRouter,Depends,Query,Request
from pydantic import ValidationError,BaseModel,ConfigDict,Field,field_validator
from typing import Literal
from sqlalchemy import select,func,update,or_,and_
from sqlalchemy.exc import IntegrityError
from app.core.database import get_session
from app.core.dependencies import administrator
from app.core.exceptions import APIError
from app.core.security import now
from app.models.user import Provider,ProviderModelMapping
from app.providers.registry import PROVIDER_TYPES,build_adapter
from app.providers.base import ProviderFailure
from app.schemas.provider import ProviderCreate,ProviderEdit,ProviderDiscovery,public_provider
from app.services.provider_crypto import encrypt_secret,decrypt_secret
from app.services.sessions import audit
from app.gateway.provider_concurrency import loads
router=APIRouter(prefix='/api/admin/providers',tags=['模型供应商'])
FIELDS=('name','provider_type','protocol','protocol_type','account_type','base_url','protocol_config','default_test_model','proxy','priority','max_concurrency','status','remark')
ERROR_MESSAGES={
    'UPSTREAM_AUTH_FAILED':'上游拒绝鉴权，请检查Key和权限',
    'UPSTREAM_HTTP_ERROR':'上游返回非成功HTTP状态',
    'UPSTREAM_TIMEOUT':'上游请求超时',
    'UPSTREAM_NETWORK_ERROR':'无法连接上游，请检查地址、网络或代理',
    'UPSTREAM_INVALID_RESPONSE':'上游模型列表格式不符合所选协议',
    'UPSTREAM_RESPONSE_TOO_LARGE':'上游响应超过连接测试大小限制',
}


async def public_rows(rows,db):
    try: counts=await loads(rows)
    except APIError: counts={}
    from app.schemas.models import protocol_category,public_mapping
    mappings=(await db.scalars(select(ProviderModelMapping).where(ProviderModelMapping.provider_id.in_([r.id for r in rows]),ProviderModelMapping.deleted_at.is_(None)).order_by(ProviderModelMapping.id))).all() if rows else []
    grouped={r.id:[] for r in rows}
    for m in mappings:grouped[m.provider_id].append(m)
    result=[]
    for row in rows:
        items=grouped[row.id];categories=sorted({protocol_category(m.model_type) for m in items})
        result.append({**public_provider(row),'current_concurrency':counts.get(row.id),'models':[public_mapping(m) for m in items],
            'effective_protocol_type':row.protocol_type or (categories[0] if len(categories)==1 else 'mixed' if categories else None)})
    return result


async def target(db,provider_id,lock=False):
    query=select(Provider).where(Provider.id==provider_id,Provider.deleted_at.is_(None))
    if lock: query=query.with_for_update()
    row=await db.scalar(query)
    if not row: raise APIError(404,'PROVIDER_NOT_FOUND','账号不存在')
    return row


def validate_input(body,has_key):
    plans=PROVIDER_TYPES[body.provider_type].get('account_types',{'standard':{'name':'标准账号'}})
    if body.account_type not in plans:raise APIError(422,'PROVIDER_ACCOUNT_TYPE_MISMATCH','供应商与账号类型不匹配')
    if body.protocol_config is None and body.protocol not in PROVIDER_TYPES[body.provider_type]['protocols']:
        raise APIError(422,'PROVIDER_PROTOCOL_MISMATCH','供应商与协议不匹配')
    if PROVIDER_TYPES[body.provider_type]['key_required'] and not has_key:
        raise APIError(422,'PROVIDER_KEY_REQUIRED','该供应商需要API Key')


async def validate_test_model(db,row,submitted=None):
    if not row.default_test_model:return
    if submitted is not None:
        valid=any(m.logical_model==row.default_test_model and m.status=='enabled' for m in submitted)
    else:
        valid=await db.scalar(select(ProviderModelMapping.id).where(ProviderModelMapping.provider_id==row.id,
            ProviderModelMapping.logical_model==row.default_test_model,ProviderModelMapping.status=='enabled',ProviderModelMapping.deleted_at.is_(None)))
    if not valid:raise APIError(422,'INVALID_TEST_MODEL','默认测试模型必须是本账号已启用的模型映射')


async def sync_mappings(db,row,submitted):
    from app.api.admin.model_mappings import canonical
    from app.services.provider_rules import category_mapping,protect_removed
    for item in submitted:category_mapping(row,item);await canonical(db,item.logical_model,item.model_type)
    rows=(await db.scalars(select(ProviderModelMapping).where(ProviderModelMapping.provider_id==row.id,
        ProviderModelMapping.deleted_at.is_(None)).with_for_update())).all()
    previous={m.logical_model:m for m in rows};wanted={m.logical_model:m for m in submitted}
    await protect_removed(db,row,set(previous)-set(wanted))
    for name,mapping in previous.items():
        if name not in wanted:mapping.deleted_at=now();mapping.status='disabled'
    await db.flush()
    for name,item in wanted.items():
        mapping=previous.get(name)
        if mapping:
            for field,value in item.model_dump().items():setattr(mapping,field,value)
        else:db.add(ProviderModelMapping(provider_id=row.id,**item.model_dump()))
    await db.flush()


@router.get('/types')
async def types(actor=Depends(administrator)):
    return {'data':[{'code':k,**v} for k,v in PROVIDER_TYPES.items()]}


@router.post('/discover-models')
async def discover_draft(body: ProviderDiscovery,request: Request,actor=Depends(administrator),db=Depends(get_session)):
    saved=await target(db,body.provider_id) if body.provider_id else None
    key=body.api_key.get_secret_value() if body.api_key else decrypt_secret(saved.api_key_encrypted) if saved else None
    validate_input(body,bool(key))
    draft=Provider(**body.model_dump(exclude={'api_key','model_mappings','provider_id'}))
    adapter=build_adapter(draft,key)
    await db.commit()
    try:
        models=await adapter.list_models()
        names=list(dict.fromkeys(m['id'] for m in models))
        if any(not n.strip() or len(n)>200 or any(ord(c)<32 or ord(c)==127 for c in n) for n in names):
            raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
    except ProviderFailure as error:
        audit(db,actor.id,'discover_provider_draft',body.provider_id,request.client.host,result='failure',resource_type='provider')
        await db.commit()
        raise APIError(502,error.code,'模型发现失败，请检查账号连接信息') from None
    audit(db,actor.id,'discover_provider_draft',body.provider_id,request.client.host,resource_type='provider')
    await db.commit()
    return {'data':{'models':[{'id':n} for n in names],'latency_ms':adapter.latency_ms,'http_status':adapter.http_status}}


@router.get('')
async def listing(actor=Depends(administrator),db=Depends(get_session),page: int=Query(1,ge=1),page_size: int=Query(20,ge=1,le=100),q: str=Query('',max_length=100),status: str=Query('',max_length=20),provider_type: str=Query('',max_length=40),protocol: str=Query('',max_length=40),health_status: str=Query('',max_length=20),protocol_type: Literal['','text','image','vector']=''):
    query=select(Provider).where(Provider.deleted_at.is_(None))
    if q: query=query.where(or_(Provider.name.icontains(q,autoescape=True),select(ProviderModelMapping.id).where(
        ProviderModelMapping.provider_id==Provider.id,ProviderModelMapping.deleted_at.is_(None),or_(ProviderModelMapping.logical_model.icontains(q,autoescape=True),ProviderModelMapping.upstream_model.icontains(q,autoescape=True))).exists()))
    if status: query=query.where(Provider.status==status)
    if provider_type: query=query.where(Provider.provider_type==provider_type)
    if protocol:
        legacy={'openai-completions':'openai','openai-responses':'openai','anthropic-messages':'anthropic','ollama':'ollama',
            'openai-embeddings':None,'openai-images':None,'openai-rerank':None}.get(protocol,protocol)
        names={'openai':['openai-completions','openai-responses','openai-embeddings','openai-images','openai-rerank'],'anthropic':['anthropic-messages'],'ollama':['ollama']}.get(protocol,[protocol])
        query=query.where(or_(and_(or_(Provider.protocol_config.is_(None),func.jsonb_typeof(Provider.protocol_config)=='null'),Provider.protocol==legacy),
            *[Provider.protocol_config.has_key(n) for n in names]))
    if protocol_type:
        kinds={'text':['text','reasoning','multimodal'],'image':['image'],'vector':['embedding','rerank']}[protocol_type]
        query=query.where(or_(Provider.protocol_type==protocol_type,and_(Provider.protocol_type.is_(None),select(ProviderModelMapping.id).where(
            ProviderModelMapping.provider_id==Provider.id,ProviderModelMapping.deleted_at.is_(None),ProviderModelMapping.model_type.in_(kinds)).exists())))
    if health_status: query=query.where(Provider.health_status==health_status)
    total=await db.scalar(select(func.count()).select_from(query.subquery()))
    rows=(await db.scalars(query.order_by(Provider.priority.asc(),Provider.id).offset((page-1)*page_size).limit(page_size))).all()
    return {'data':{'items':await public_rows(rows,db),'total':total}}


@router.get('/{provider_id}')
async def detail(provider_id: int,actor=Depends(administrator),db=Depends(get_session)):
    return {'data':(await public_rows([await target(db,provider_id)],db))[0]}


@router.post('',status_code=201)
async def create(body: ProviderCreate,request: Request,actor=Depends(administrator),db=Depends(get_session)):
    from app.api.admin.model_mappings import config_lock
    if body.model_mappings is None:raise APIError(422,'PROVIDER_MAPPINGS_REQUIRED','账号至少需要一个模型映射')
    if body.model_mappings is not None:await config_lock(db)
    validate_input(body,bool(body.api_key))
    values=body.model_dump(exclude={'api_key','model_mappings'})
    row=Provider(**values,api_key_encrypted=encrypt_secret(body.api_key.get_secret_value()) if body.api_key else None)
    db.add(row)
    try:
        await db.flush()
        await validate_test_model(db,row,body.model_mappings)
        if body.model_mappings is not None:await sync_mappings(db,row,body.model_mappings)
        await db.refresh(row)
        audit(db,actor.id,'create_provider',row.id,request.client.host,resource_type='provider')
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise APIError(409,'PROVIDER_NAME_EXISTS','账号名称已存在') from None
    return {'data':public_provider(row)}


@router.patch('/{provider_id}')
async def edit(provider_id: int,body: ProviderEdit,request: Request,actor=Depends(administrator),db=Depends(get_session)):
    from app.api.admin.model_mappings import config_lock
    if body.model_mappings is not None:await config_lock(db)
    row=await target(db,provider_id,True)
    if body.expected_config_version is not None and row.config_version!=body.expected_config_version:
        raise APIError(409,'PROVIDER_CHANGED','账号已被其他操作修改，请重新加载后保存')
    submitted=body.model_dump(exclude_unset=True)
    if body.clear_api_key and body.api_key is not None:
        raise APIError(422,'PROVIDER_KEY_CONFLICT','不能同时更换和清除Key')
    values={f:submitted.get(f,getattr(row,f)) for f in FIELDS}
    try:
        checked=ProviderCreate(**values,api_key=body.api_key)
    except ValidationError as error:
        fields=', '.join('.'.join(str(x) for x in e['loc']) for e in error.errors())
        raise APIError(422,'VALIDATION_ERROR','请检查字段：'+fields) from None
    has_key=bool(body.api_key) or (bool(row.api_key_encrypted) and not body.clear_api_key)
    validate_input(checked,has_key)
    probe=Provider(id=row.id,**checked.model_dump(exclude={'api_key','model_mappings'}))
    await validate_test_model(db,probe,body.model_mappings)
    from app.services.provider_rules import category_mapping
    for m in body.model_mappings if body.model_mappings is not None else (await db.scalars(select(ProviderModelMapping).where(ProviderModelMapping.provider_id==row.id,ProviderModelMapping.deleted_at.is_(None)))).all():category_mapping(probe,m)
    checked_values=checked.model_dump(exclude={'api_key','model_mappings'})
    connection_changed=any(getattr(row,f)!=checked_values[f] for f in ('provider_type','protocol','base_url','protocol_config','proxy','account_type','protocol_type')) or body.api_key is not None or body.clear_api_key
    for field,value in checked_values.items(): setattr(row,field,value)
    if body.api_key is not None: row.api_key_encrypted=encrypt_secret(body.api_key.get_secret_value())
    elif body.clear_api_key: row.api_key_encrypted=None
    row.config_version+=1
    if connection_changed:
        row.health_status='unknown';row.failure_count=0;row.cooldown_until=None
        row.last_test_at=None;row.last_http_status=None;row.last_latency_ms=None;row.last_error_code=None
    try:
        await db.flush()
        if body.model_mappings is not None:await sync_mappings(db,row,body.model_mappings)
        await db.refresh(row)
        audit(db,actor.id,'update_provider',row.id,request.client.host,resource_type='provider')
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise APIError(409,'PROVIDER_NAME_EXISTS','账号名称已存在') from None
    return {'data':public_provider(row)}


@router.delete('/{provider_id}')
async def remove(provider_id: int,request: Request,actor=Depends(administrator),db=Depends(get_session)):
    from app.api.admin.model_mappings import config_lock
    from app.services.provider_rules import protect_removed
    await config_lock(db)
    row=await target(db,provider_id,True)
    mappings=(await db.scalars(select(ProviderModelMapping).where(ProviderModelMapping.provider_id==provider_id,ProviderModelMapping.deleted_at.is_(None)).with_for_update())).all()
    await protect_removed(db,row,{m.logical_model for m in mappings})
    for m in mappings:m.status='disabled';m.deleted_at=now()
    row.status='deleted';row.deleted_at=now();row.config_version+=1
    audit(db,actor.id,'delete_provider',row.id,request.client.host,resource_type='provider')
    await db.commit()
    return {'data':{'message':'账号已删除，历史关联保留'}}


class ModelTest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    consent: Literal[True]
    image_consent: bool=False
    models: list[str]=Field(min_length=1,max_length=100)
    expected_config_version: int=Field(ge=0)

    @field_validator('models')
    @classmethod
    def unique(cls,value):
        if len(value)!=len(set(value)) or any(not v or len(v)>100 for v in value):raise ValueError('Select distinct saved models')
        return value


@router.post('/{provider_id}/test-models')
async def test_models(provider_id: int,body: ModelTest,request: Request,actor=Depends(administrator),db=Depends(get_session)):
    from app.services.provider_testing import run_one
    row=await target(db,provider_id)
    if row.status!='enabled':raise APIError(409,'PROVIDER_DISABLED','请先启用账号')
    if row.config_version!=body.expected_config_version:raise APIError(409,'PROVIDER_CHANGED','账号已变化，请重新加载')
    items=(await db.scalars(select(ProviderModelMapping).where(ProviderModelMapping.provider_id==provider_id,
        ProviderModelMapping.logical_model.in_(body.models),ProviderModelMapping.status=='enabled',ProviderModelMapping.deleted_at.is_(None)))).all()
    if len(items)!=len(body.models):raise APIError(422,'INVALID_TEST_MODEL','仅能测试本账号已保存且启用的映射')
    if any(m.model_type=='image' for m in items) and not body.image_consent:raise APIError(422,'IMAGE_TEST_CONSENT_REQUIRED','文生图测试须单独确认真实生成图片及费用')
    by_name={m.logical_model:m for m in items}
    audit(db,actor.id,'test_provider_models',provider_id,request.client.host,resource_type='provider')
    await db.commit()
    results=[]
    for name in body.models:
        results.append(await run_one(actor.id,row,by_name[name],request))
        if results[-1]['error_code'] in ('PROVIDER_CHANGED','ADMIN_TEST_FORBIDDEN'):break
    return {'data':{'results':results,'success_count':sum(r['success'] for r in results),'failure_count':sum(not r['success'] for r in results)}}


@router.post('/{provider_id}/test')
async def test(provider_id: int,request: Request,actor=Depends(administrator),db=Depends(get_session)):
    row=await target(db,provider_id)
    if row.status!='enabled': raise APIError(409,'PROVIDER_DISABLED','请先启用账号，再测试连接')
    version=row.config_version
    await validate_test_model(db,row)
    test_model=row.default_test_model
    mapping=await db.scalar(select(ProviderModelMapping).where(ProviderModelMapping.provider_id==row.id,
        ProviderModelMapping.logical_model==test_model,ProviderModelMapping.deleted_at.is_(None))) if test_model else None
    adapter=build_adapter(row,decrypt_secret(row.api_key_encrypted))
    await db.commit()  # Release DB transaction before external network I/O.
    try:
        models=await adapter.list_models()
        available=mapping is None or mapping.upstream_model in {m['id'] for m in models}
        result={'success':available,'network_connected':True,'authentication':'accepted' if row.api_key_encrypted else 'not_configured',
                'http_status':adapter.http_status,'latency_ms':adapter.latency_ms,'model_count':len(models),'error_code':None,
                'message':('默认测试模型已在上游模型列表中确认；生成能力仍需实际调用验证' if test_model else '模型列表请求成功；生成能力仍需对应模型调用验证') if available else '上游模型列表中未找到默认测试模型',
                'test_model':test_model,'model_available':available if test_model else None}
        if not available:result['error_code']='TEST_MODEL_NOT_FOUND'
    except ProviderFailure as error:
        result={'success':False,'network_connected':error.network,'authentication':error.auth,
                'http_status':error.status,'latency_ms':error.latency_ms,'model_count':None,'error_code':error.code,
                'message':ERROR_MESSAGES.get(error.code,'所选协议暂不支持此操作')}
    connected=result['success'] or result['error_code']=='TEST_MODEL_NOT_FOUND'
    unsupported=result.get('http_status') in (404,405,501) or result['error_code']=='UNSUPPORTED_OPERATION'
    updated=await db.execute(update(Provider).where(Provider.id==provider_id,Provider.config_version==version,Provider.status=='enabled',Provider.deleted_at.is_(None))
        .values(health_status='healthy' if connected else 'unknown' if unsupported else 'unhealthy',failure_count=0 if connected else Provider.failure_count if unsupported else Provider.failure_count+1,cooldown_until=Provider.cooldown_until if unsupported else None,
                last_test_at=now(),last_http_status=result['http_status'],last_latency_ms=result['latency_ms'],last_error_code=result['error_code'],updated_at=now()))
    if not updated.rowcount:
        await db.rollback()
        raise APIError(409,'PROVIDER_CHANGED','测试期间账号配置已变化，请重新测试')
    audit(db,actor.id,'test_provider',provider_id,request.client.host,result='success' if result['success'] else 'failure',resource_type='provider')
    await db.commit()
    return {'data':result}


