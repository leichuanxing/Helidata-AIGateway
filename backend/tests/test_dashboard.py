"""Dashboard aggregation regression against real PostgreSQL temporary tables."""
import os,unittest
from datetime import datetime,timedelta,timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine,AsyncSession
from sqlalchemy.pool import NullPool

@unittest.skipUnless(os.environ.get('USAGE_POSTGRES_TEST')=='1','PostgreSQL integration explicitly enabled')
class DashboardPostgresTests(unittest.IsolatedAsyncioTestCase):
 async def test_provider_metrics_outside_top_ten_and_unknown_tokens(self):
  from app.core.config import get_settings
  from app.services.usage import accumulate,statistics
  from app.services.dashboard import rankings,provider_metrics
  engine=create_async_engine(get_settings().database.url(),poolclass=NullPool,connect_args={'ssl':False})
  try:
   async with engine.connect() as connection:
    transaction=await connection.begin()
    async with AsyncSession(bind=connection) as db:
     for table in ('usage_hourly','usage_daily'):
      await db.execute(text(f'CREATE TEMP TABLE {table} (LIKE public.{table} INCLUDING ALL) ON COMMIT DROP'))
     await db.execute(text('CREATE TEMP TABLE call_logs ON COMMIT DROP AS SELECT * FROM public.call_logs WITH NO DATA'))
     base=datetime(2026,10,21,16,tzinfo=timezone.utc)
     for i in range(1,13):
      token=100-i if i<=10 else None if i==11 else 0
      record=dict(id=i,request_id=f'dashboard-isolated-{i}',created_at=base+timedelta(minutes=10),operation='chat',
       user_id=1,user_group_id=1,api_key_id=1,provider_id=i,request_model='virtual',logical_model='model'+str(i),protocol='openai',
       status='success' if i<=10 else 'failure',input_tokens=token,output_tokens=0 if token is not None else None,total_tokens=token,cached_tokens=None,ttft_ms=None,tokens_per_second=None)
      await db.execute(text('INSERT INTO call_logs ('+','.join(record)+') VALUES ('+','.join(':'+k for k in record)+')'),record)
      await accumulate(db,record)
     for grain in ('hour','day'):
      start,end=base-timedelta(minutes=1),base+timedelta(hours=2)
      rank=await rankings(db,start,end,grain)
      self.assertEqual(len(rank['provider']),11)
      self.assertEqual(sum(r['requests'] for r in rank['provider']),12)
      metrics=await provider_metrics(db,start,end,grain,list(range(1,14)))
      self.assertEqual(metrics[11],{'requests':1,'failure':1})
      self.assertEqual(metrics[12],{'requests':1,'failure':1})
      self.assertNotIn(13,metrics)
      self.assertEqual(await provider_metrics(db,start,end,grain,[]),{})
      stats=await statistics(db,start,end,grain,{})
      self.assertEqual(stats['summary']['requests'],12)
      self.assertEqual(sum(r['failure'] for r in metrics.values()),stats['summary']['failure'])
      self.assertEqual(stats['summary']['total_tokens'],sum(100-i for i in range(1,11)))
    await transaction.rollback()
  finally:await engine.dispose()
