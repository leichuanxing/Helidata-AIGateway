"""Usage regression tests. Integration uses transaction-local temporary tables only.

Set USAGE_POSTGRES_TEST=1 with the application's PostgreSQL configuration to run
the exact-boundary, dimension and portal-isolation checks; no upstream calls.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import NullPool
from app.services.usage import contribution, statistics, accumulate, BREAKDOWN_DIMS
from app.api.usage import filter_options, window


class MetricsTest(unittest.TestCase):
    def test_missing_and_zero_are_distinct(self):
        missing=contribution({'status':'failure'})
        zero=contribution(dict(status='success',input_tokens=0,output_tokens=0,total_tokens=0,cached_tokens=0))
        self.assertEqual(missing['total_tokens_count'],0)
        self.assertEqual(zero['total_tokens_count'],1)
        self.assertEqual(missing['usage_unavailable'],1)
        self.assertEqual(zero['usage_unavailable'],0)

    def test_time_window_requires_zone_and_positive_bounded_range(self):
        from app.core.exceptions import APIError
        now=datetime.now(timezone.utc)
        for start,end in [(now,now),(now,now+timedelta(days=367)),(now.replace(tzinfo=None),now)]:
            with self.assertRaises(APIError):window(start,end)


@unittest.skipUnless(os.environ.get('USAGE_POSTGRES_TEST')=='1','PostgreSQL integration explicitly enabled')
class PostgreSQLTest(unittest.IsolatedAsyncioTestCase):
    async def test_dimensions_boundaries_and_portal_isolation(self):
        from app.core.config import get_settings
        engine=create_async_engine(get_settings().database.url(),poolclass=NullPool,connect_args={'ssl':False})
        try:
            async with engine.connect() as connection:
                transaction=await connection.begin()
                async with AsyncSession(bind=connection) as db:
                    for table in ('usage_hourly','usage_daily'):
                        await db.execute(text(f'CREATE TEMP TABLE {table} (LIKE public.{table} INCLUDING ALL) ON COMMIT DROP'))
                    await db.execute(text('CREATE TEMP TABLE call_logs ON COMMIT DROP AS SELECT * FROM public.call_logs WITH NO DATA'))
                    for name,column in [('users','username'),('user_groups','name'),('api_keys','name'),('providers','name'),('logical_models','name')]:
                        await db.execute(text(f'CREATE TEMP TABLE {name} (id int,{column} text'+(',user_id int' if name=='api_keys' else '')+') ON COMMIT DROP'))
                        if name!='api_keys':await db.execute(text(f"INSERT INTO {name} VALUES (1,'visible'),(2,'other')"))
                    await db.execute(text("INSERT INTO api_keys VALUES (1,'own key',1),(2,'other key',2)"))
                    base=datetime(2026,1,1,16,tzinfo=timezone.utc)  # Beijing midnight.
                    records=[]
                    for ident,offset,user,request,actual,status,token,ttft,tps in [
                        (1,-10,1,'virtual','visible','success',10,100,10),
                        (2,10,1,'virtual','visible','success',20,200,20),
                        (3,60,2,'private-model','other','failure',None,None,None),
                        (4,24*60+10,1,'visible','visible','success',0,None,0),
                        (5,24*60+50,2,'private-model','other','success',100,300,30)]:
                        record=dict(id=ident,request_id=f'isolated-usage-{ident}',created_at=base+timedelta(minutes=offset),
                            operation='chat',user_id=user,user_group_id=user,api_key_id=user,provider_id=user,
                            request_model=request,logical_model=actual,protocol='openai',status=status,
                            input_tokens=token,output_tokens=0 if token is not None else None,total_tokens=token,
                            cached_tokens=None,ttft_ms=ttft,tokens_per_second=tps)
                        records.append(record)
                        columns=','.join(record);params=','.join(':'+k for k in record)
                        await db.execute(text(f'INSERT INTO call_logs ({columns}) VALUES ({params})'),record)
                        await accumulate(db,record)
                    start,end=base-timedelta(minutes=5),base+timedelta(days=1,minutes=30)
                    for grain in ('hour','day'):
                        data=await statistics(db,start,end,grain,{},'request_model')
                        self.assertEqual(data['summary']['requests'],3)
                        self.assertEqual(data['summary']['total_tokens'],20)
                        self.assertEqual(data['summary']['success'],2)
                        self.assertEqual(data['summary']['usage_unavailable'],1)
                        self.assertEqual(data['summary']['average_ttft_ms'],200)
                        self.assertEqual(data['summary']['average_tokens_per_second'],10)
                        self.assertEqual(sum(r['requests'] for r in data['series']),3)
                        self.assertEqual(sum(r['requests'] for r in data['breakdown']),3)
                        empty=[r for r in data['series'] if not r['requests']]
                        if grain=='hour':self.assertGreater(len(empty),20)
                        self.assertTrue(all(r['average_ttft_ms'] is None for r in empty))
                        for dimension in BREAKDOWN_DIMS:
                            grouped=await statistics(db,start,end,grain,{},dimension)
                            self.assertEqual(grouped['summary'],data['summary'])
                            self.assertEqual(sum(r['requests'] for r in grouped['breakdown']),3)
                        legacy=await statistics(db,start,end,grain,{})
                        self.assertEqual(legacy['summary'],data['summary'])
                    requested=await statistics(db,start,end,'hour',{'request_model':'virtual'},'logical_model')
                    actual=await statistics(db,start,end,'hour',{'logical_model':'visible'},'request_model')
                    self.assertEqual(requested['summary']['requests'],1)
                    self.assertEqual(actual['summary']['requests'],2)
                    missing=await statistics(db,start,end,'day',{'user_id':2},'logical_model')
                    self.assertIsNone(missing['summary']['total_tokens'])
                    zero=await statistics(db,base+timedelta(days=1),end,'hour',{'user_id':1},'request_model')
                    self.assertEqual(zero['summary']['total_tokens'],0)
                    self.assertEqual(zero['summary']['token_coverage'],100)
                    empty=await statistics(db,base+timedelta(days=3),base+timedelta(days=3,hours=2),'hour',{},'operation')
                    self.assertEqual(empty['summary']['requests'],0)
                    self.assertEqual(len(empty['series']),2)
                    self.assertEqual(empty['breakdown'],[])
                    # Same-hour edges, exact end exclusion and full-day rollups.
                    for lo,hi in [(5,15),(0,10),(10,60),(-60,60),(0,1440),(1445,1455)]:
                        begin,finish=base+timedelta(minutes=lo),base+timedelta(minutes=hi)
                        expected=[r for r in records if begin<=r['created_at']<finish]
                        for grain in ('hour','day'):
                            d=await statistics(db,begin,finish,grain,{},'operation')
                            self.assertEqual(d['summary']['requests'],len(expected))
                            self.assertEqual(d['summary']['total_tokens'] or 0,sum(r['total_tokens'] or 0 for r in expected))
                    mine=(await filter_options(db,1))['data']
                    self.assertEqual(set(mine),{'api_key_id','model','protocol'})
                    self.assertEqual([o['value'] for o in mine['api_key_id']],['1'])
                    self.assertNotIn('private-model',[o['value'] for o in mine['model']])
                    # Truncation never changes totals or hides that rows are omitted.
                    from app.services.usage import DIMS,COUNTERS
                    cols=['bucket',*DIMS,*COUNTERS]
                    projection=["'synthetic-'||g::text" if k=='request_model' else k for k in cols]
                    await db.execute(text('INSERT INTO usage_hourly ('+','.join(cols)+') SELECT '+','.join(projection)+' FROM usage_hourly CROSS JOIN generate_series(1,205) g WHERE request_model=\'virtual\' AND bucket=:base'),{'base':base})
                    limited=await statistics(db,base,base+timedelta(hours=1),'hour',{},'request_model')
                    self.assertEqual(limited['dimension_count'],206)
                    self.assertEqual(len(limited['breakdown']),200)
                    self.assertEqual(limited['summary']['requests'],206)
                    self.assertLess(sum(r['request_share'] for r in limited['breakdown']),100)
                await transaction.rollback()
        finally:await engine.dispose()


if __name__=='__main__':unittest.main()
