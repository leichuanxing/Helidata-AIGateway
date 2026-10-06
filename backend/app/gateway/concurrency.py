from contextlib import asynccontextmanager
from redis.exceptions import RedisError
from app.gateway.admission import Admission
from app.providers.operations import INFERENCE


@asynccontextmanager
async def acquire(ctx):
    if ctx.operation not in INFERENCE:
        yield;return
    admission=Admission(ctx);ctx.admission=admission
    try:
        await admission.wait()
        yield
    finally:
        try:await admission.release()
        except RedisError:pass
