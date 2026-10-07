from datetime import datetime,timedelta,timezone
from typing import Literal
from fastapi import APIRouter,Depends,Query
from sqlalchemy import func,or_,select
from sqlalchemy.orm import defer
from app.core.database import get_session
from app.core.dependencies import administrator
from app.core.exceptions import APIError
from app.models.call_log import CallLog

router=APIRouter(prefix='/api/admin/call-logs',tags=['调用日志'])

def public(row,detail=False):
    result={column.name:getattr(row,column.name) for column in CallLog.__table__.columns if column.name not in ('trace','request_body','response_body')}
    if detail:result.update(trace=row.trace,request_body=row.request_body,response_body=row.response_body)
    return result

@router.get('')
async def listing(actor=Depends(administrator),db=Depends(get_session),
    page:int=Query(1,ge=1,le=10000),page_size:int=Query(20,ge=1,le=100),
    request_id:str=Query('',max_length=80),user_id:int|None=Query(None,ge=1),user_group_id:int|None=Query(None,ge=1),
    api_key_id:int|None=Query(None,ge=1),provider_id:int|None=Query(None,ge=1),model:str=Query('',max_length=100),
    model_scope:Literal['either','request','actual']='either',request_model:str=Query('',max_length=100),logical_model:str=Query('',max_length=100),
    status:Literal['','success','failure','client_cancelled','failed']='',http_status:int|None=Query(None,ge=100,le=599),
    protocol:str=Query('',max_length=30),error_code:str=Query('',max_length=80),operation:Literal['','chat','responses','messages','embeddings','rerank','images','models','preflight']='',
    stream:bool|None=None,min_latency_ms:float|None=Query(None,ge=0,le=3600000,allow_inf_nan=False),
    start:datetime|None=None,end:datetime|None=None):
    query=select(CallLog)
    now=datetime.now(timezone.utc)
    if start is not None or end is not None or not request_id:
        end=end or now;start=start or end-timedelta(days=7)
        if start.tzinfo is None or end.tzinfo is None:
            raise APIError(422,'LOG_TIMEZONE_REQUIRED','查询时间必须包含时区')
        if start>=end or end-start>timedelta(days=31):
            raise APIError(422,'LOG_TIME_RANGE_INVALID','查询时间范围应大于0且不超过31天')
        query=query.where(CallLog.created_at>=start,CallLog.created_at<end)
    for name,value in [('request_id',request_id),('user_id',user_id),('user_group_id',user_group_id),
        ('api_key_id',api_key_id),('provider_id',provider_id),('http_status',http_status),('error_code',error_code),('operation',operation),('protocol',protocol),('request_model',request_model),('logical_model',logical_model)]:
        if value is not None and value!='':query=query.where(getattr(CallLog,name)==value)
    if model:query=query.where(CallLog.request_model==model if model_scope=='request' else CallLog.logical_model==model if model_scope=='actual' else or_(CallLog.request_model==model,CallLog.logical_model==model))
    if status:query=query.where(CallLog.status.in_(['failure','client_cancelled']) if status=='failed' else CallLog.status==status)
    if stream is not None:query=query.where(CallLog.stream==stream)
    if min_latency_ms is not None:query=query.where(CallLog.gateway_latency_ms>=min_latency_ms)
    total=await db.scalar(select(func.count()).select_from(query.with_only_columns(CallLog.id).subquery()))
    query=query.options(defer(CallLog.trace,raiseload=True),defer(CallLog.request_body,raiseload=True),defer(CallLog.response_body,raiseload=True))
    rows=(await db.scalars(query.order_by(CallLog.created_at.desc(),CallLog.id.desc()).offset((page-1)*page_size).limit(page_size))).all()
    return {'data':{'items':[public(row) for row in rows],'total':total,'page':page,'page_size':page_size,'start':start,'end':end}}

@router.get('/options')
async def options(actor=Depends(administrator),db=Depends(get_session)):
    from app.models.user import User,UserGroup,ApiKey,Provider,LogicalModel
    result={}
    for key,model,column in [('user_id',User,User.username),('user_group_id',UserGroup,UserGroup.name),('api_key_id',ApiKey,ApiKey.name),('provider_id',Provider,Provider.name)]:
        result[key]=[{'value':str(ident),'label':f'{name} · #{ident}'} for ident,name in (await db.execute(select(model.id,column).order_by(model.id.desc()).limit(500))).all()]
    # Bound discovery by recent rows; do not read bodies or scan all historical logs.
    recent=select(CallLog.request_model,CallLog.logical_model,CallLog.protocol,CallLog.error_code).order_by(CallLog.created_at.desc(),CallLog.id.desc()).limit(2000)
    records=(await db.execute(recent)).all()
    names=set((await db.scalars(select(LogicalModel.name).order_by(LogicalModel.name).limit(500))).all())
    names.update(value for row in records for value in row[:2] if value)
    result['model']=[{'value':v,'label':v} for v in sorted(names)[:500]]
    for key,index in [('protocol',2),('error_code',3)]:
        result[key]=[{'value':v,'label':v} for v in sorted({row[index] for row in records if row[index]})[:100]]
    return {'data':result}

@router.get('/{request_id}')
async def detail(request_id:str,actor=Depends(administrator),db=Depends(get_session)):
    row=await db.scalar(select(CallLog).where(CallLog.request_id==request_id))
    if not row:raise APIError(404,'CALL_LOG_NOT_FOUND','调用记录不存在或尚未完成')
    return {'data':public(row,True)}
