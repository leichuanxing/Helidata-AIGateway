import logging
import shutil

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.database import engine
from app.core.redis import redis_client

router = APIRouter()
logger = logging.getLogger(__name__)


async def dependencies():
    checks = {'fastapi': 'ok'}
    try:
        async with engine.connect() as connection:
            await connection.execute(text('SELECT 1'))
        checks['postgresql'] = 'ok'
    except Exception as error:
        logger.error('PostgreSQL health check failed [%s]', type(error).__name__)
        checks['postgresql'] = 'error'
    try:
        await redis_client.ping()
        checks['redis'] = 'ok'
    except Exception as error:
        logger.error('Redis health check failed [%s]', type(error).__name__)
        checks['redis'] = 'error'
    try:
        disk = shutil.disk_usage('/data')
        checks['disk'] = 'ok' if disk.free > 100 * 1024 * 1024 else 'low'
    except OSError:
        checks['disk'] = 'error'
    return checks


@router.get('/health')
async def health():
    checks = await dependencies()
    good = all(value == 'ok' for value in checks.values())
    return JSONResponse({'status': 'ok' if good else 'error'}, status_code=200 if good else 503)


@router.get('/health/detail')
async def detail():
    checks = await dependencies()
    good = all(value == 'ok' for value in checks.values())
    return JSONResponse({'status': 'ok' if good else 'error', 'checks': checks,
                         'phase': 20, 'application': '合力数据AI网关'}, status_code=200 if good else 503)




