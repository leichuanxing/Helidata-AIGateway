from fastapi import APIRouter,Depends
from app.core.dependencies import administrator,active_user
from app.core.config import get_settings
from app.core.database import get_session
from app.core.exceptions import APIError
from app.core.redis import redis_client
from app.models.user import UserGroup
from app.gateway.quota import snapshot
from app.gateway.provider_concurrency import LOAD
from app.gateway.admission import QUEUE
from app.models.quota import QuotaBucket,QuotaReservation
from app.gateway.quota import predicate,recover
from app.services.sessions import audit
from sqlalchemy import select
from pydantic import BaseModel,Field
from fastapi import Request,Query
router=APIRouter(tags=['并发与配额'])

@router.get('/api/admin/resource-status')
async def resources(actor=Depends(administrator)):
    from redis.exceptions import RedisError
    try:
        active=await redis_client.eval(LOAD,1,'gateway:concurrency')
        queued=await redis_client.eval("""
        local t=redis.call('TIME');local n=tonumber(t[1])+tonumber(t[2])/1000000
        for _,token in ipairs(redis.call('ZRANGEBYSCORE',KEYS[2],'-inf',n)) do redis.call('ZREM',KEYS[1],token) end
        redis.call('ZREMRANGEBYSCORE',KEYS[2],'-inf',n);return redis.call('ZCARD',KEYS[1])
        """,2,QUEUE,'gateway:queue:leases')
    except RedisError:raise APIError(503,'CONCURRENCY_UNAVAILABLE','并发状态暂不可用') from None
    cfg=get_settings().gateway
    return {'data':{'active_requests':active,'queued_requests':queued,'max_concurrency':cfg.max_concurrency,
        'queue_size':cfg.queue_size,'queue_timeout':cfg.queue_timeout}}

@router.get('/api/portal/quota')
async def own_quota(user=Depends(active_user),db=Depends(get_session)):
    group=await db.get(UserGroup,user.user_group_id) if user.user_group_id else None
    if not group or group.status!='enabled':raise APIError(403,'GROUP_DISABLED','用户组不可用')
    await db.commit()
    return {'data':await snapshot(group)}

class ReconcileInput(BaseModel):
    reported_tokens:int=Field(strict=True,ge=0,le=9007199254740991)

@router.get('/api/admin/user-groups/{group_id}/quota-reservations')
async def reservations(group_id:int,actor=Depends(administrator),db=Depends(get_session),page:int=Query(1,ge=1)):
    buckets=(await db.scalars(select(QuotaBucket).where(QuotaBucket.group_id==group_id).order_by(QuotaBucket.period,QuotaBucket.period_start).with_for_update())).all()
    for bucket in buckets:await recover(db,bucket)
    await db.commit()
    rows=(await db.scalars(select(QuotaReservation).where(QuotaReservation.group_id==group_id,QuotaReservation.state=='unreported')
        .order_by(QuotaReservation.expires_at.desc()).offset((page-1)*50).limit(50))).all()
    return {'data':[{'id':row.id,'request_id':row.id.split(':')[0],'period':row.period,'period_start':row.period_start,
        'unreported_budget':row.budget,'expires_at':row.expires_at} for row in rows]}

@router.put('/api/admin/user-groups/{group_id}/quota-reservations/{reservation_id}')
async def reconcile(group_id:int,reservation_id:str,body:ReconcileInput,request:Request,actor=Depends(administrator),db=Depends(get_session)):
    original=await db.get(QuotaReservation,reservation_id)
    if not original or original.group_id!=group_id:raise APIError(404,'RESERVATION_NOT_FOUND','配额记录不存在')
    bucket=await db.scalar(select(QuotaBucket).where(*predicate(group_id,original.period,original.period_start)).with_for_update())
    # Refresh after locking the bucket, matching settlement lock order.
    row=await db.get(QuotaReservation,reservation_id,with_for_update=True,populate_existing=True)
    if row.state!='unreported':raise APIError(409,'QUOTA_ALREADY_SETTLED','该记录已结算或仍在执行')
    bucket.unreported_budget-=row.budget;bucket.reported_tokens+=body.reported_tokens
    row.reported_tokens=body.reported_tokens;row.state='reconciled'
    audit(db,actor.id,'reconcile_quota',row.id,request.client.host,resource_type='quota_reservation')
    await db.commit()
    return {'data':{'reported_tokens':row.reported_tokens,'state':row.state}}
