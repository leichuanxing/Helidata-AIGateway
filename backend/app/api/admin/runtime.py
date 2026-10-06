"""Safe pool diagnostics; authenticated super administrators only."""
from fastapi import APIRouter, Depends
from app.core.dependencies import super_administrator
from app.core.database import engine
from app.core.config import get_settings
from app.providers.pool import pools
from app.gateway import preparation

router = APIRouter(prefix='/api/admin/runtime',tags=['运行状态'])


@router.get('')
async def runtime(actor=Depends(super_administrator)):
    cfg = get_settings()
    db = engine.pool
    return {'data':{'http':{**pools.snapshot(),
        'max_connections_per_pool':cfg.gateway.http_max_connections,
        'max_keepalive_per_pool':cfg.gateway.http_max_keepalive,
        'max_proxy_pools':cfg.gateway.http_proxy_pools},
        'database':{'size':db.size(),'checked_out':db.checkedout(),
            'overflow':db.overflow(),'max_overflow':cfg.database.max_overflow,
            'pool_timeout_seconds':cfg.database.pool_timeout,
            'statement_timeout_seconds':cfg.database.statement_timeout},
        'preparation':{'slots':preparation.slots,'waiting':preparation.waiting,
            'queue_size':cfg.gateway.preparation_queue_size,'timeout_seconds':cfg.gateway.preparation_timeout},
        'max_body_bytes':cfg.gateway.max_body_bytes}}
