"""Persistent health transitions guarded against configuration races."""
from datetime import timedelta
import logging
from time import monotonic
from sqlalchemy import select
from app.core.database import session_factory
from app.core.security import now
from app.core.config import get_settings
from app.models.user import Provider

from app.providers.operations import INFERENCE

BACKOFF=(30,60,120,300)
logger=logging.getLogger(__name__)

def state(provider):
    if provider.status!='enabled' or provider.deleted_at: return 'Disabled'
    if provider.cooldown_until and provider.cooldown_until>now(): return 'Cooling'
    if provider.health_status=='unhealthy': return 'Unavailable'
    return 'Available'

async def finish(ctx,outcome,code=None):
    if outcome=='client_cancelled' or ctx.operation not in INFERENCE: return
    if code in ('UPSTREAM_REQUEST_REJECTED','CLIENT_DISCONNECTED','UPSTREAM_POOL_EXHAUSTED'): return
    if ctx.provider is None or ctx.adapter is None: return
    if outcome!='success' and (not code or not code.startswith('UPSTREAM_')): return
    try:
        async with session_factory.begin() as db:
            row=await db.scalar(select(Provider).where(Provider.id==ctx.provider.id,
                Provider.config_version==ctx.provider.config_version,Provider.status=='enabled',Provider.deleted_at.is_(None)).with_for_update())
            if row is None: return
            row.last_http_status=ctx.adapter.http_status
            row.last_latency_ms=round((monotonic()-ctx.attempt_started)*1000)
            row.last_error_code=code
            if outcome=='success':
                row.health_status='healthy';row.failure_count=0;row.cooldown_until=None
            else:
                row.failure_count+=1
                if code=='UPSTREAM_AUTH_FAILED':
                    row.health_status='unhealthy';row.cooldown_until=None
                else:
                    row.health_status='unknown'
                    threshold=get_settings().gateway.failure_threshold
                    if row.failure_count>=threshold or code=='UPSTREAM_RATE_LIMITED':
                        step=row.failure_count-(1 if code=='UPSTREAM_RATE_LIMITED' else threshold)
                        delay=min(3600,get_settings().gateway.cooldown_seconds*(1,2,4,10)[min(max(step,0),3)])
                        row.cooldown_until=now()+timedelta(seconds=delay)
    except Exception as error:
        logger.error('Provider health persistence failed [%s]',type(error).__name__,extra={'request_id':ctx.request_id})
