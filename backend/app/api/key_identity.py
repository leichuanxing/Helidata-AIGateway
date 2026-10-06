from fastapi import APIRouter,Depends
from app.core.database import get_session
from app.services.key_auth import api_key_principal,record_key_use
router=APIRouter(prefix='/api/gateway',tags=['网关身份'])


@router.get('/identity')
async def identity(principal=Depends(api_key_principal),db=Depends(get_session)):
    await record_key_use(db,principal)
    group=principal.group
    return {'data':{'user_id':principal.user.id,'key_id':principal.key.id,'user_group':{
        'id':group.id,'name':group.name,'quota_limit':group.quota_limit,'quota_period':group.quota_period,
        'max_concurrency':group.max_concurrency,'key_max_concurrency':group.key_max_concurrency},
        'allowed_model_group_ids':principal.model_group_ids}}
