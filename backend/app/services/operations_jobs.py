"""Bounded retention and optional non-generating Provider checks."""
import asyncio
from datetime import timedelta
from sqlalchemy import select,delete,update
from app.core.config import get_settings
from app.core.database import session_factory
from app.core.security import now
from app.models.user import Provider
from app.models.call_log import CallLog
from app.models.routing import RouteDecision
from app.models.compliance import ComplianceLog
from app.providers.registry import build_adapter
from app.providers.base import ProviderFailure
from app.services.provider_crypto import decrypt_secret
import logging
logger=logging.getLogger(__name__)


async def retention():
    cutoff=now()-timedelta(days=get_settings().logging.retention_days)
    # Keep accounting aggregates and immutable administrator audit history.
    async with session_factory.begin() as db:
        for model in (CallLog,RouteDecision,ComplianceLog):
            ids=select(model.id).where(model.created_at<cutoff).order_by(model.id).limit(1000)
            await db.execute(delete(model).where(model.id.in_(ids)))


async def health_checks(cursor=0):
    async with session_factory() as db:
        rows=(await db.scalars(select(Provider).where(Provider.id>cursor,Provider.status=='enabled',Provider.deleted_at.is_(None)).order_by(Provider.id).limit(50))).all()
    for row in rows:
        version=row.config_version;adapter=None
        try:
            adapter=build_adapter(row,decrypt_secret(row.api_key_encrypted));await adapter.list_models()
            success,code=True,None
        except ProviderFailure as error:success,code=False,error.code
        except Exception:success,code=False,'PROVIDER_CHECK_FAILED'
        async with session_factory.begin() as db:
            await db.execute(update(Provider).where(Provider.id==row.id,Provider.config_version==version,Provider.status=='enabled',Provider.deleted_at.is_(None)).values(
                health_status='healthy' if success else 'unhealthy',failure_count=0 if success else Provider.failure_count+1,
                cooldown_until=None,last_test_at=now(),last_http_status=getattr(adapter,'http_status',None),last_error_code=code,
                last_latency_ms=getattr(adapter,'latency_ms',None)))
    return rows[-1].id if len(rows)==50 else 0


async def loop():
    last_retention=last_health=0;cursor=0
    while True:
        instant=asyncio.get_running_loop().time()
        try:
            if instant-last_retention>=600:
                await retention();last_retention=instant
            interval=get_settings().gateway.health_check_interval
            if interval and instant-last_health>=interval:
                cursor=await health_checks(cursor);last_health=instant
        except Exception as error:logger.warning('Operations maintenance pending [%s]',type(error).__name__)
        await asyncio.sleep(1)
