from redis.asyncio import Redis
from app.core.config import get_settings

settings = get_settings().redis
redis_client = Redis(host=settings.host, port=settings.port, decode_responses=True,
                     socket_connect_timeout=settings.socket_timeout,
                     socket_timeout=settings.socket_timeout, health_check_interval=30)
