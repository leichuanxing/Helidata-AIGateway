from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.core.config import get_settings

settings = get_settings().database
engine = create_async_engine(settings.url(), pool_pre_ping=True,
                             pool_size=settings.pool_size, max_overflow=settings.max_overflow,
                             pool_timeout=settings.pool_timeout, pool_recycle=settings.pool_recycle,
                             connect_args={'ssl': False, 'timeout': settings.connect_timeout,
                                 'server_settings': {'statement_timeout': str(settings.statement_timeout*1000)}},
                             hide_parameters=True)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    async with session_factory() as session:
        yield session
