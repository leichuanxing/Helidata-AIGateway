from fastapi import APIRouter,Depends,Request
from sqlalchemy import select
from app.core.database import get_session
from app.core.dependencies import super_administrator
from app.core.exceptions import APIError
from app.models.user import SystemSetting
from app.schemas.settings import SettingsPatch,Basic,GatewayOptions,SecurityOptions,LogOptions
from app.services import operations_settings as operations
from app.services.sessions import audit

router=APIRouter(tags=['系统设置'])


@router.get('/api/public/settings')
async def public():return {'data':operations.public()}


@router.get('/api/admin/settings')
async def read(actor=Depends(super_administrator),db=Depends(get_session)):
    return {'data':await operations.document(db)}


@router.patch('/api/admin/settings')
async def save(body:SettingsPatch,request:Request,actor=Depends(super_administrator),db=Depends(get_session)):
    row=await db.scalar(select(SystemSetting).where(SystemSetting.key=='operations').with_for_update())
    if row is None:raise APIError(503,'SETTINGS_UNAVAILABLE','系统设置尚未初始化')
    current=await operations.document(db)
    if current['revision']!=body.revision:raise APIError(409,'SETTINGS_CHANGED','配置已被更新，请重新加载')
    for name,model in [('basic',Basic),('gateway',GatewayOptions),('security',SecurityOptions),('logging',LogOptions)]:
        section=getattr(body,name)
        if section is not None:current[name]=model.model_validate({**current[name],**section.model_dump(exclude_unset=True)}).model_dump()
    current['revision']+=1
    row.value=current
    # Legacy seed keys stay in sync; assets are stored in the same database snapshot.
    for key in ('system_name','language','timezone'):
        legacy=await db.get(SystemSetting,key)
        if legacy:legacy.value=current['basic'][key]
    audit(db,actor.id,'update_system_settings','operations',request.client.host,resource_type='system_settings')
    await db.commit()
    operations.apply(current)
    return {'data':current}
