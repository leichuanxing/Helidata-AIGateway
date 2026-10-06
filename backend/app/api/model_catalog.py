from fastapi import APIRouter,Depends
from app.core.database import get_session
from app.core.dependencies import active_user
from app.services.key_auth import api_key_principal,record_key_use
from app.services.model_catalog import catalog
router=APIRouter(tags=['模型目录'])


@router.get('/api/portal/models')
async def portal(user=Depends(active_user),db=Depends(get_session)):
    return {'data':{'groups':await catalog(db,user.user_group_id)}}


@router.get('/api/gateway/models')
async def key_models(principal=Depends(api_key_principal),db=Depends(get_session)):
    groups=await catalog(db,principal.user.user_group_id)
    await record_key_use(db,principal)
    return {'data':{'groups':groups}}
