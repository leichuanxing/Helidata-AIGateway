import asyncio

import asyncpg

from app.core.config import get_settings


async def provision():
    cfg = get_settings().database
    if cfg.host != '127.0.0.1' or cfg.port != 5432:
        raise RuntimeError('Single-container database must use 127.0.0.1:5432')
    connection = await asyncpg.connect(user='postgres', database='postgres', host='/run/postgresql')
    try:
        # Identifiers are quoted independently from string literals.
        username = '"' + cfg.username.replace('"', '""') + '"'
        database = '"' + cfg.database.replace('"', '""') + '"'
        password = "'" + cfg.password.get_secret_value().replace("'", "''") + "'"
        exists = await connection.fetchval('SELECT 1 FROM pg_roles WHERE rolname=$1', cfg.username)
        if not exists:
            await connection.execute(f'CREATE ROLE {username} LOGIN PASSWORD {password}')
        if not await connection.fetchval('SELECT 1 FROM pg_database WHERE datname=$1', cfg.database):
            await connection.execute(f"CREATE DATABASE {database} OWNER {username} TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'C.UTF-8' LC_CTYPE 'C.UTF-8'")
    finally:
        await connection.close()
    # pgvector is not a trusted extension. Provision with the local bootstrap
    # administrator rather than granting superuser privileges to the gateway.
    connection = await asyncpg.connect(user='postgres', database=cfg.database, host='/run/postgresql')
    try:
        await connection.execute('CREATE EXTENSION IF NOT EXISTS vector')
    finally:
        await connection.close()


if __name__ == '__main__':
    asyncio.run(provision())
