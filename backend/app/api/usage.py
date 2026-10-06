from datetime import datetime,timedelta,timezone
from typing import Literal
from fastapi import APIRouter,Depends,Query
from app.core.database import get_session
from app.core.dependencies import administrator,active_user
from app.core.exceptions import APIError
from app.services.usage import statistics
router=APIRouter(tags=['用量统计'])


def window(start,end):
    end=end or datetime.now(timezone.utc);start=start or end-timedelta(days=7)
    if start.tzinfo is None or end.tzinfo is None:raise APIError(422,'USAGE_TIMEZONE_REQUIRED','时间必须包含时区')
    start=start.astimezone(timezone.utc);end=end.astimezone(timezone.utc)
    if start>=end or end-start>timedelta(days=366):raise APIError(422,'USAGE_TIME_RANGE_INVALID','时间范围应大于0且不超过366天')
    return start,end


@router.get('/api/admin/usage')
async def admin(actor=Depends(administrator),db=Depends(get_session),start:datetime|None=None,end:datetime|None=None,
    grain:Literal['hour','day']='day',user_id:int|None=Query(None,ge=1),user_group_id:int|None=Query(None,ge=1),
    api_key_id:int|None=Query(None,ge=1),provider_id:int|None=Query(None,ge=1),model:str=Query('',max_length=100),protocol:str=Query('',max_length=30),operation:Literal['','chat','responses','messages','embeddings','rerank','images']=''):
    start,end=window(start,end)
    return {'data':await statistics(db,start,end,grain,dict(user_id=user_id,user_group_id=user_group_id,api_key_id=api_key_id,provider_id=provider_id,model=model,protocol=protocol,operation=operation))}


@router.get('/api/portal/usage')
async def portal(actor=Depends(active_user),db=Depends(get_session),start:datetime|None=None,end:datetime|None=None,
    grain:Literal['hour','day']='day',api_key_id:int|None=Query(None,ge=1),model:str=Query('',max_length=100),operation:Literal['','chat','responses','messages','embeddings','rerank','images']=''):
    start,end=window(start,end)
    return {'data':await statistics(db,start,end,grain,dict(user_id=actor.id,api_key_id=api_key_id,model=model,operation=operation))}
