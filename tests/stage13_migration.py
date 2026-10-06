"""Isolated database historic backfill, reversible migration and large sums."""
import asyncio,os,subprocess,tempfile,uuid
from pathlib import Path
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import get_settings
NAME='stage13_migration_'+uuid.uuid4().hex[:10]
settings=get_settings().model_copy(deep=True);settings.database.database=NAME
subprocess.run(['runuser','-u','postgres','--','createdb','-O','helidata',NAME],check=True)
try:
    with tempfile.TemporaryDirectory(prefix='stage13-migration-') as folder:
        config=Path(folder)/'config.yaml'
        source=yaml.safe_load(Path('/data/config/config.yaml').read_text());source['database']['database']=NAME
        config.write_text(yaml.safe_dump(source));config.chmod(0o600)
        env={**os.environ,'GATEWAY_CONFIG':str(config)}
        def migration(direction,revision):subprocess.run(['alembic',direction,revision],cwd='/app/backend',env=env,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        migration('upgrade','0008')
        async def insert():
            engine=create_async_engine(settings.database.url(),connect_args={'ssl':False},hide_parameters=True)
            async with engine.begin() as db:
                await db.execute(text("INSERT INTO call_logs (request_id,created_at,operation,client_ip,stream,status,http_status,gateway_latency_ms,trace,input_tokens,output_tokens,total_tokens,ttft_ms,tokens_per_second) VALUES ('req_historic','2026-10-04T23:45:00+08:00','chat','127.0.0.1',true,'success',200,100,'{}',4,2,6,50,20),('req_preflight','2026-10-04T23:45:00+08:00','preflight','127.0.0.1',false,'success',200,1,'{}',NULL,NULL,NULL,NULL,NULL)"))
            await engine.dispose()
        asyncio.run(insert());migration('upgrade','head')
        async def verify():
            engine=create_async_engine(settings.database.url(),connect_args={'ssl':False},hide_parameters=True)
            async with engine.begin() as db:
                for table in ('usage_hourly','usage_daily'):
                    row=(await db.execute(text(f'SELECT requests,total_tokens_sum,ttft_sum,tps_sum,bucket FROM {table}'))).one()
                    assert tuple(row[:4])==(1,6,50,20)
                    assert row.bucket.hour==(15 if table=='usage_hourly' else 16)
                    await db.execute(text(f'UPDATE {table} SET total_tokens_sum=10000000000000000000'))
                    assert await db.scalar(text(f'SELECT total_tokens_sum FROM {table}'))==10**19
                    await db.execute(text(f'UPDATE {table} SET total_tokens_sum=6'))
            await engine.dispose()
        asyncio.run(verify());migration('downgrade','0008');migration('upgrade','head');asyncio.run(verify())
        print('PASS: 0008 historic chat backfills correct UTC+8 hour/day, excludes preflight, metrics and >bigint totals; downgrade/reupgrade preserves logs')
finally:
    assert NAME.startswith('stage13_migration_')
    subprocess.run(['runuser','-u','postgres','--','dropdb',NAME],check=True)
