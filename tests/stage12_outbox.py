"""Run as actual gateway OS user; real PostgreSQL replay after injected failure."""
import asyncio
from pathlib import Path
import tempfile
from unittest.mock import patch
import uuid
from sqlalchemy import delete,func,select
from app.core.database import session_factory,engine
from app.gateway import call_log
from app.gateway.context import GatewayContext
from app.models.call_log import CallLog

async def main():
    context=GatewayContext('req_'+uuid.uuid4().hex,'chat')
    try:
        assert call_log.OUTBOX.stat().st_mode&0o777==0o700
        with tempfile.TemporaryDirectory(prefix='stage12-',dir=call_log.OUTBOX) as folder:
            with patch.object(call_log,'OUTBOX',Path(folder)):
                async def unavailable(record):raise RuntimeError('hidden-storage-error')
                with patch.object(call_log,'persist',unavailable):await call_log.write(context,'failure','INTERNAL_ERROR')
                pending=list(Path(folder).glob('*.json'));assert len(pending)==1
                assert pending[0].stat().st_mode&0o777==0o600
                await call_log.replay_once();assert not list(Path(folder).glob('*.json'))
                async with session_factory() as db:
                    assert await db.scalar(select(func.count()).select_from(CallLog).where(CallLog.request_id==context.request_id))==1
        print('PASS: actual gateway OS user writes protected durable outbox and replays once into PostgreSQL')
    finally:
        async with session_factory.begin() as db:await db.execute(delete(CallLog).where(CallLog.request_id==context.request_id))
        await engine.dispose()

if __name__=='__main__':asyncio.run(main())
