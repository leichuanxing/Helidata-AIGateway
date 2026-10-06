"""Bound database preparation before the four-level execution admission."""
import asyncio
from contextlib import asynccontextmanager
from app.core.config import get_settings
from app.core.exceptions import APIError

cfg = get_settings()
slots = max(1,min(8,(cfg.database.pool_size+cfg.database.max_overflow)//2))
semaphore = asyncio.Semaphore(slots)
waiting = 0


@asynccontextmanager
async def acquire():
    global waiting
    if semaphore.locked() and waiting >= cfg.gateway.preparation_queue_size:
        raise APIError(429,'PREPARATION_QUEUE_FULL','请求准备队列已满')
    waiting += 1
    acquired = False
    try:
        try:
            async with asyncio.timeout(cfg.gateway.preparation_timeout):
                await semaphore.acquire()
                acquired = True
        except TimeoutError:
            raise APIError(429,'PREPARATION_TIMEOUT','请求准备等待超时') from None
    finally:
        waiting -= 1
    try:
        yield
    finally:
        if acquired:
            semaphore.release()
