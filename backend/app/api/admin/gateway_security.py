from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Request, Query, Response
from sqlalchemy import select, func
from app.core.database import get_session
from app.core.dependencies import super_administrator
from app.core.exceptions import APIError
from app.models.user import SystemSetting, ApiKey, User, AuditLog
from app.schemas.gateway_security import SecurityPolicy, AccessRule, SecuritySectionPatch, AddressValidation
from pydantic import ValidationError
from ipaddress import ip_network
from app.services import gateway_security as security, operations_settings as operations
from app.services.sessions import audit

router = APIRouter(tags=['网关安全'])

@router.get('/internal/gateway-security/admin', include_in_schema=False)
async def admin_guard(): return Response(status_code=200)

@router.get('/api/admin/gateway-security')
async def read(request: Request, actor=Depends(super_administrator)):
    cfg = security.policy.model_dump(mode='json')
    cfg['login_max_attempts'] = operations.get_settings().security.login_max_attempts
    cfg['login_lock_seconds'] = operations.get_settings().security.login_lock_seconds
    return {'data':{'policy':cfg,'current_ip':request.client.host}}

@router.put('/api/admin/gateway-security')
async def save(body:SecurityPolicy, request:Request, actor=Depends(super_administrator), db=Depends(get_session)):
    from app.api.admin.model_mappings import config_lock
    await config_lock(db)
    row = await db.get(SystemSetting,'gateway_security',with_for_update=True)
    current = SecurityPolicy.model_validate(row.value) if row else SecurityPolicy()
    if current.revision != body.revision: raise APIError(409,'SECURITY_CHANGED','配置已更新，请重新加载后再保存')
    security.prevent_lockout(request, body)
    ids = [item.key_id for item in body.key_bindings]
    if ids:
        actual = set((await db.scalars(select(ApiKey.id).where(ApiKey.id.in_(ids),ApiKey.deleted_at.is_(None),ApiKey.status!='deleted'))).all())
        if actual != set(ids): raise APIError(400,'INVALID_KEY_BINDING','API Key 已删除或不存在，请移除对应绑定')
    value = body.model_copy(update={'revision':current.revision+1})
    if row: row.value=value.model_dump(mode='json')
    else: db.add(SystemSetting(key='gateway_security',scope='security',value=value.model_dump(mode='json')))
    # Login protection shares the existing settings source and atomic lock.
    operation_row = await db.get(SystemSetting,'operations',with_for_update=True)
    settings = await operations.document(db,private=True)
    login_changed=(settings['security']['login_max_attempts']!=body.login_max_attempts or
                   settings['security']['login_lock_seconds']!=body.login_lock_seconds)
    if login_changed:
        settings['security']['login_max_attempts']=body.login_max_attempts
        settings['security']['login_lock_seconds']=body.login_lock_seconds
        settings['revision'] += 1
        if operation_row: operation_row.value=settings
        else: db.add(SystemSetting(key='operations',scope='operations',value=settings))
    audit(db,actor.id,'gateway_security_updated',client_ip=request.client.host,resource_type='gateway_security')
    await db.commit()
    security.policy=value
    operations.apply(settings)
    return {'data':{'policy':value.model_dump(mode='json'),'current_ip':request.client.host}}

@router.patch('/api/admin/gateway-security')
async def save_section(body:SecuritySectionPatch,request:Request,actor=Depends(super_administrator),db=Depends(get_session)):
    from app.api.admin.model_mappings import config_lock
    await config_lock(db)
    row=await db.get(SystemSetting,'gateway_security',with_for_update=True)
    current=SecurityPolicy.model_validate(row.value) if row else SecurityPolicy()
    if current.revision!=body.revision:
        raise APIError(409,'SECURITY_CHANGED','安全配置已被更新，请重新加载后再保存')
    raw=current.model_dump(mode='json')
    raw['login_max_attempts']=operations.get_settings().security.login_max_attempts
    raw['login_lock_seconds']=operations.get_settings().security.login_lock_seconds
    allowed={
        'global_access':{'global_access'},'admin_access':{'admin_access'},
        'api_access':{'api_access','key_bindings'},'rate':{'ip_rpm','key_rpm'},
        'login':{'login_max_attempts','login_lock_seconds'},'bans':{'bans'},
        'proxies':{'trusted_proxies'}}[body.section]
    if not body.values or set(body.values)-allowed:
        raise APIError(422,'SECURITY_SECTION_INVALID','只能保存当前标签的配置')
    raw.update(body.values)
    try: parsed=SecurityPolicy.model_validate(raw)
    except ValidationError as error:
        message=error.errors()[0]['msg'].removeprefix('Value error, ')
        raise APIError(422,'SECURITY_CONFIG_INVALID',message) from None
    return await save(parsed,request,actor,db)

@router.post('/api/admin/gateway-security/validate-addresses')
async def validate_addresses(body:AddressValidation,request:Request,actor=Depends(super_administrator)):
    try:
        normalized=AccessRule(addresses=body.addresses).addresses
        if body.purpose=='proxies' and any(ip_network(value).prefixlen==0 for value in normalized):
            raise APIError(422,'INVALID_TRUSTED_PROXY','可信代理不能使用全网网段')
    except ValidationError:
        raise APIError(422,'INVALID_NETWORK','请输入有效 IPv4、IPv6 或 CIDR 网段') from None
    return {'data':{'addresses':normalized,'includes_current_ip':security.matches(request.client.host,normalized)}}

@router.get('/api/admin/gateway-security/keys')
async def keys(actor=Depends(super_administrator),db=Depends(get_session)):
    rows=(await db.execute(select(ApiKey.id,ApiKey.name,ApiKey.prefix,ApiKey.suffix,User.username).join(User,User.id==ApiKey.user_id).where(ApiKey.deleted_at.is_(None),ApiKey.status!='deleted').order_by(ApiKey.id))).all()
    return {'data':[{'id':r.id,'name':r.name,'label':f'{r.username} / {r.name} ({r.prefix}…{r.suffix})'} for r in rows]}

@router.get('/api/admin/gateway-security/logs')
async def logs(actor=Depends(super_administrator),db=Depends(get_session),ip:str|None=Query(None,max_length=45),event:str|None=Query(None,max_length=80),start:datetime|None=None,end:datetime|None=None,page:int=Query(1,ge=1,le=10000),size:int=Query(20,ge=1,le=100)):
    end=end or datetime.now(timezone.utc)
    start=start or end-timedelta(days=7)
    if start.tzinfo is None or end.tzinfo is None or start>=end or end-start>timedelta(days=31):
        raise APIError(422,'SECURITY_LOG_RANGE_INVALID','查询须包含时区且范围大于0、不超过31天')
    conditions=[AuditLog.resource_type=='gateway_security']
    if ip: conditions.append(AuditLog.client_ip==ip)
    if event: conditions.append(AuditLog.action==event)
    if start: conditions.append(AuditLog.created_at>=start)
    if end: conditions.append(AuditLog.created_at<=end)
    total=await db.scalar(select(func.count()).select_from(AuditLog).where(*conditions))
    rows=(await db.scalars(select(AuditLog).where(*conditions).order_by(AuditLog.id.desc()).offset((page-1)*size).limit(size))).all()
    return {'data':{'total':total,'items':[{'id':r.id,'event':r.action,'ip':r.client_ip,'key_id':r.resource_id,'created_at':r.created_at,'request_id':r.details.get('request_id')} for r in rows]}}

@router.get('/api/admin/gateway-security/logs/{ident}')
async def log_detail(ident:int,actor=Depends(super_administrator),db=Depends(get_session)):
    row=await db.get(AuditLog,ident)
    if not row or row.resource_type!='gateway_security':
        raise APIError(404,'SECURITY_LOG_NOT_FOUND','安全日志不存在')
    return {'data':{'id':row.id,'event':row.action,'ip':row.client_ip,'key_id':row.resource_id,
        'created_at':row.created_at,'request_id':row.details.get('request_id'),'result':row.result,
        'actor_id':row.actor_id}}
