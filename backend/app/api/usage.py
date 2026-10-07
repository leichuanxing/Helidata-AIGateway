from datetime import datetime,timedelta,timezone
from typing import Literal
from fastapi import APIRouter,Depends,Query
from app.core.database import get_session
from app.core.dependencies import administrator,active_user
from app.core.exceptions import APIError
from app.services.usage import statistics
from sqlalchemy import select,text
router=APIRouter(tags=['用量统计'])


def window(start,end):
    end=end or datetime.now(timezone.utc);start=start or end-timedelta(days=7)
    if start.tzinfo is None or end.tzinfo is None:raise APIError(422,'USAGE_TIMEZONE_REQUIRED','时间必须包含时区')
    start=start.astimezone(timezone.utc);end=end.astimezone(timezone.utc)
    if start>=end or end-start>timedelta(days=366):raise APIError(422,'USAGE_TIME_RANGE_INVALID','时间范围应大于0且不超过366天')
    return start,end


def model_filter(model,scope):
    return {('request_model' if scope=='request' else 'logical_model' if scope=='actual' else 'model'):model}


async def filter_options(db,user_id=None):
    from app.models.user import User,UserGroup,ApiKey,Provider,LogicalModel
    result={};limit=500
    for key,model,column in [('api_key_id',ApiKey,ApiKey.name),('user_id',User,User.username),('user_group_id',UserGroup,UserGroup.name),('provider_id',Provider,Provider.name)]:
        if user_id is not None and key!='api_key_id':continue
        query=select(model.id,column)
        if user_id is not None:query=query.where(ApiKey.user_id==user_id)
        result[key]=[{'value':str(ident),'label':f'{name} · #{ident}'} for ident,name in (await db.execute(query.order_by(model.id.desc()).limit(limit))).all()]
    params={'actor_id':user_id}
    scope='WHERE user_id=:actor_id' if user_id is not None else ''
    query=f"SELECT name FROM (SELECT request_model AS name FROM usage_daily {scope} UNION SELECT logical_model AS name FROM usage_daily {scope}) m WHERE name<>'' ORDER BY name LIMIT 500"
    names=set((await db.execute(text(query),params)).scalars().all())
    if user_id is None:names.update((await db.scalars(select(LogicalModel.name).order_by(LogicalModel.name).limit(limit))).all())
    result['model']=[{'value':name,'label':name} for name in sorted(names)[:limit]]
    query=f"SELECT DISTINCT protocol FROM usage_daily {scope+' AND' if scope else 'WHERE'} protocol<>'' ORDER BY protocol LIMIT 100"
    result['protocol']=[{'value':name,'label':name} for name in (await db.execute(text(query),params)).scalars().all()]
    return {'data':result}


@router.get('/api/admin/usage/options')
async def admin_options(actor=Depends(administrator),db=Depends(get_session)):
    return await filter_options(db)


@router.get('/api/portal/usage/options')
async def portal_options(actor=Depends(active_user),db=Depends(get_session)):
    return await filter_options(db,actor.id)


@router.get('/api/admin/usage')
async def admin(actor=Depends(administrator),db=Depends(get_session),start:datetime|None=None,end:datetime|None=None,
    grain:Literal['hour','day']='day',user_id:int|None=Query(None,ge=1),user_group_id:int|None=Query(None,ge=1),
    api_key_id:int|None=Query(None,ge=1),provider_id:int|None=Query(None,ge=1),model:str=Query('',max_length=100),model_scope:Literal['either','request','actual']='either',
    dimension:Literal['request_model','logical_model','provider_id','user_id','user_group_id','api_key_id','protocol','operation']='request_model',
    protocol:str=Query('',max_length=30),operation:Literal['','chat','responses','messages','embeddings','rerank','images']=''):
    start,end=window(start,end)
    return {'data':await statistics(db,start,end,grain,dict(user_id=user_id,user_group_id=user_group_id,api_key_id=api_key_id,provider_id=provider_id,**model_filter(model,model_scope),protocol=protocol,operation=operation),dimension)}


@router.get('/api/portal/usage')
async def portal(actor=Depends(active_user),db=Depends(get_session),start:datetime|None=None,end:datetime|None=None,
    grain:Literal['hour','day']='day',api_key_id:int|None=Query(None,ge=1),model:str=Query('',max_length=100),model_scope:Literal['either','request','actual']='either',
    dimension:Literal['request_model','logical_model','api_key_id','operation']='request_model',operation:Literal['','chat','responses','messages','embeddings','rerank','images']=''):
    start,end=window(start,end)
    return {'data':await statistics(db,start,end,grain,dict(user_id=actor.id,api_key_id=api_key_id,**model_filter(model,model_scope),operation=operation),dimension)}
