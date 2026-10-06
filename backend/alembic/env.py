import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.models.user import Base
from app.models import quota,call_log,usage,routing,compliance,backup


def migrate(connection):
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def online():
    engine = create_async_engine(get_settings().database.url(), connect_args={'ssl': False, 'timeout': get_settings().database.connect_timeout}, hide_parameters=True)
    async with engine.connect() as connection:
        await connection.run_sync(migrate)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=get_settings().database.url(), target_metadata=Base.metadata,
                      literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
