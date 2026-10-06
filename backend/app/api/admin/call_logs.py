from datetime import datetime,timedelta,timezone
from typing import Literal
from fastapi import APIRouter,Depends,Query
from sqlalchemy import func,or_,select
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
    status:Literal['','success','failure','client_cancelled','failed']='',http_status:int|None=Query(None,ge=100,le=599),
    protocol:str=Query('',max_length=30),error_code:str=Query('',max_length=80),operation:Literal['','chat','responses','messages','embeddings','rerank','images','models','preflight']='',
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
        ('api_key_id',api_key_id),('provider_id',provider_id),('http_status',http_status),('error_code',error_code),('operation',operation),('protocol',protocol)]:
        if value is not None and value!='':query=query.where(getattr(CallLog,name)==value)
    if model:query=query.where(or_(CallLog.request_model==model,CallLog.logical_model==model))
    if status:query=query.where(CallLog.status.in_(['failure','client_cancelled']) if status=='failed' else CallLog.status==status)
    total=await db.scalar(select(func.count()).select_from(query.subquery()))
    rows=(await db.scalars(query.order_by(CallLog.created_at.desc(),CallLog.id.desc()).offset((page-1)*page_size).limit(page_size))).all()
    return {'data':{'items':[public(row) for row in rows],'total':total,'page':page,'page_size':page_size}}

@router.get('/{request_id}')
async def detail(request_id:str,actor=Depends(administrator),db=Depends(get_session)):
    row=await db.scalar(select(CallLog).where(CallLog.request_id==request_id))
    if not row:raise APIError(404,'CALL_LOG_NOT_FOUND','调用记录不存在或尚未完成')
    return {'data':public(row,True)}
