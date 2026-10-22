"""Bound decision auditing so a database outage cannot replace the route result."""
import asyncio
import logging
from app.core.database import session_factory
from app.models.routing import RouteDecision

logger=logging.getLogger(__name__)

async def write(record):
    try:
        async with asyncio.timeout(2):
            async with session_factory.begin() as db:
                db.add(RouteDecision(**record))
        return True
    except Exception:
        # Never include prompt/evidence, credentials or database error text.
        logger.error('Route decision audit unavailable request_id=%s config_id=%s status=%s reason=%s',
                     record['request_id'],record['config_id'],record['status'],record['reason'])
        return False
