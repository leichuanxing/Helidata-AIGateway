"""Durable atomic reservations; actual usage and unreported budget remain distinct."""
import asyncio
from contextlib import asynccontextmanager,suppress
from datetime import timedelta,timezone
import json
from uuid import uuid4
from sqlalchemy import select,update
from sqlalchemy.dialects.postgresql import insert
from app.core.database import session_factory
from app.core.security import now
from app.core.exceptions import APIError
from app.models.user import UserGroup
from app.models.quota import QuotaBucket,QuotaReservation

TTL=90;RENEW_SECONDS=20

def period_key(period,instant=None):
    local=(instant or now()).astimezone(timezone(timedelta(hours=8)))
    return local.strftime('%Y-%m-%d') if period=='daily' else local.strftime('%Y-%m') if period=='monthly' else 'all'

async def snapshot(group,recover_expired=True,db=None):
    start=period_key(group.quota_period)
    if db is not None:
        row=await db.get(QuotaBucket,(group.id,group.quota_period,start))
    else:
        async with session_factory.begin() as meter_db:
            row=await meter_db.get(QuotaBucket,(group.id,group.quota_period,start),with_for_update=True if recover_expired else None)
            if row and recover_expired:await recover(meter_db,row)
    reported=row.reported_tokens if row else 0;unknown=row.unreported_budget if row else 0;reserved=row.reserved_budget if row else 0
    return {'period':group.quota_period,'period_start':start,'limit':group.quota_limit,
        'reported_tokens':reported,'unreported_budget':unknown,'reserved_budget':reserved,
        'remaining_budget':max(0,group.quota_limit-reported-unknown-reserved) if group.quota_limit else None}

async def check(ctx):
    try:ctx.quota_status=await snapshot(ctx.group)
    except Exception:raise APIError(503,'QUOTA_UNAVAILABLE','配额状态暂不可用') from None
    if ctx.quota_status['remaining_budget']==0:
        raise APIError(429,'QUOTA_EXCEEDED','用户组Token配额已用尽')

def observe(ctx,result):
    usage=result.get('usage') if isinstance(result,dict) else None
    if isinstance(usage,dict):
        clean={name:value for name in ('prompt_tokens','completion_tokens','total_tokens')
            if type(value:=usage.get(name)) is int and 0<=value<=9007199254740991}
        details=usage.get('prompt_tokens_details')
        cached=details.get('cached_tokens') if isinstance(details,dict) else None
        if type(cached) is int and 0<=cached<=9007199254740991:clean['cached_tokens']=cached
        ctx.usage_snapshot={**ctx.usage_snapshot,**clean}
        total=usage.get('total_tokens')
        if type(total) is int and 0<=total<=9007199254740991:ctx.quota_usage=total

def predicate(group_id,period,start):
    return (QuotaBucket.group_id==group_id,QuotaBucket.period==period,QuotaBucket.period_start==start)

async def recover(db,bucket):
    expired=(await db.scalars(select(QuotaReservation).where(QuotaReservation.group_id==bucket.group_id,
        QuotaReservation.period==bucket.period,QuotaReservation.period_start==bucket.period_start,
        QuotaReservation.state=='active',QuotaReservation.expires_at<=now()).with_for_update())).all()
    for row in expired:
        bucket.reserved_budget-=row.budget;bucket.unreported_budget+=row.budget;row.state='unreported'

async def reserve(ctx):
    async with session_factory.begin() as db:
        group=await db.get(UserGroup,ctx.group.id,with_for_update=True)
        if not group or group.status!='enabled':raise APIError(403,'GROUP_DISABLED','用户组已停用')
        start=period_key(group.quota_period);ident=(group.id,group.quota_period,start)
        await db.execute(insert(QuotaBucket).values(group_id=group.id,period=group.quota_period,period_start=start).on_conflict_do_nothing())
        bucket=await db.scalar(select(QuotaBucket).where(*predicate(*ident)).with_for_update())
        await recover(db,bucket)
        remaining=group.quota_limit-bucket.reported_tokens-bucket.unreported_budget-bucket.reserved_budget
        n=ctx.payload.get('n',1)
        if type(n) is not int or not 1<=n<=128:
            if group.quota_limit:raise APIError(422,'QUOTA_INPUT_INVALID','有限配额下n须为1至128的整数')
            n=1
        input_budget=len(json.dumps(ctx.payload,ensure_ascii=False).encode())
        output=ctx.payload.get('max_output_tokens') if ctx.operation=='responses' else ctx.payload.get('max_completion_tokens',ctx.payload.get('max_tokens'))
        if ctx.operation in ('embeddings','rerank'):output=0
        if output is None:
            output=min(1024,max(1,(remaining-input_budget)//n)) if group.quota_limit else 1024
            if group.quota_limit and ctx.operation in ('chat','messages','responses'):
                ctx.payload['max_output_tokens' if ctx.operation=='responses' else 'max_tokens' if ctx.operation=='messages' else 'max_completion_tokens']=output
        if type(output) is not int or output<0:raise APIError(422,'QUOTA_INPUT_INVALID','Token上限须为非负整数')
        amount=min(9007199254740991,input_budget+output*n)
        if group.quota_limit and (remaining<=0 or amount>remaining):raise APIError(429,'QUOTA_EXCEEDED','配额不足以预留本次请求预算')
        bucket.reserved_budget+=amount
        reservation=QuotaReservation(id=ctx.request_id+':'+uuid4().hex[:16],group_id=group.id,period=group.quota_period,
            period_start=start,budget=amount,expires_at=now()+timedelta(seconds=TTL))
        db.add(reservation);await db.flush()
        return reservation.id,ident

async def settle(ctx,reservation_id,ident):
    async with session_factory.begin() as db:
        bucket=await db.scalar(select(QuotaBucket).where(*predicate(*ident)).with_for_update())
        row=await db.get(QuotaReservation,reservation_id,with_for_update=True)
        if not row or not bucket:return
        # A crashed/expired reservation already conservatively consumed its budget.
        if row.state=='active':bucket.reserved_budget-=row.budget
        elif row.state=='unreported':bucket.unreported_budget-=row.budget
        else:return
        if ctx.quota_usage is not None:
            row.reported_tokens=ctx.quota_usage;bucket.reported_tokens+=ctx.quota_usage;row.state='reported'
        elif ctx.adapter.http_status in (400,401,403,404,422,429):row.state='unused'
        else:bucket.unreported_budget+=row.budget;row.state='unreported'

@asynccontextmanager
async def acquire(ctx):
    ctx.quota_usage=None
    try:reservation_id,ident=await reserve(ctx)
    except APIError:raise
    except Exception:raise APIError(503,'QUOTA_UNAVAILABLE','无法预留配额') from None
    owner=asyncio.current_task()
    async def renew():
        try:
            while True:
                await asyncio.sleep(RENEW_SECONDS)
                async with session_factory.begin() as db:
                    result=await db.execute(update(QuotaReservation).where(QuotaReservation.id==reservation_id,QuotaReservation.state=='active')
                        .values(expires_at=now()+timedelta(seconds=TTL)))
                    if not result.rowcount:ctx.lease_error='QUOTA_UNAVAILABLE';owner.cancel();return
        except Exception:ctx.lease_error='QUOTA_UNAVAILABLE';owner.cancel()
    task=asyncio.create_task(renew())
    try:yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):await task
        try:await settle(ctx,reservation_id,ident)
        except Exception:
            # Durable reservation remains reserved, later reclaimed as unreported budget.
            import logging
            logging.getLogger(__name__).error('Quota settlement pending',extra={'request_id':ctx.request_id})
