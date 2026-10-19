from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.core.config import get_settings
import asyncpg

class DatabaseUnavailable(RuntimeError):
    """A database transport failure, with no connection details in its text."""

async def connect_database(config):
    try:
        return await asyncpg.connect(host=config.host,port=config.port,user=config.username,
            password=config.password.get_secret_value(),database=config.database,ssl=False,
            timeout=config.connect_timeout,server_settings={'statement_timeout':str(config.statement_timeout*1000)})
    except (ConnectionError,TimeoutError,asyncpg.PostgresConnectionError,asyncpg.CannotConnectNowError):
        raise DatabaseUnavailable('Database connection unavailable') from None

settings = get_settings().database
engine = create_async_engine(settings.url(), pool_pre_ping=True,
                             pool_size=settings.pool_size, max_overflow=settings.max_overflow,
                             pool_timeout=settings.pool_timeout, pool_recycle=settings.pool_recycle,
                             async_creator=lambda:connect_database(settings),
                             hide_parameters=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    async with session_factory() as session:
        yield session
