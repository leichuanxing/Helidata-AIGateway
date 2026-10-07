"""Call log filters/projection regressions; uses a rolled-back temporary table."""
import os,unittest
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from fastapi import FastAPI
import httpx
from sqlalchemy import text,event
from sqlalchemy.ext.asyncio import create_async_engine,AsyncSession
from sqlalchemy.pool import NullPool
from app.api.admin.call_logs import router
from app.core.database import get_session
from app.core.dependencies import administrator

@unittest.skipUnless(os.environ.get('LOGS_POSTGRES_TEST')=='1','PostgreSQL integration explicitly enabled')
class CallLogsTest(unittest.IsolatedAsyncioTestCase):
    async def test_filters_history_projection_and_options(self):
        from app.core.config import get_settings
        engine=create_async_engine(get_settings().database.url(),poolclass=NullPool,connect_args={'ssl':False})
        statements=[]
        @event.listens_for(engine.sync_engine,'before_cursor_execute')
        def capture(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
        try:
            async with engine.connect() as connection:
                transaction=await connection.begin()
                async with AsyncSession(bind=connection) as db:
                    await db.execute(text('CREATE TEMP TABLE call_logs (LIKE public.call_logs INCLUDING ALL) ON COMMIT DROP'))
                    now=datetime.now(timezone.utc)
                    for ident,status,stream,latency,days in [(1,'success',False,800,0),(2,'failure',True,6000,0),(3,'client_cancelled',True,1200,0),(4,'success',False,100,50)]:
                        await db.execute(text("INSERT INTO call_logs (id,request_id,created_at,operation,client_ip,request_model,logical_model,stream,status,http_status,error_code,gateway_latency_ms,trace,request_body) VALUES (:id,:request_id,:created_at,'chat','127.0.0.1','virtual','actual',:stream,:status,200,:error_code,:latency,CAST(:trace AS jsonb),CAST(:body AS jsonb))"),dict(id=ident,request_id=f'fixture-{ident}',created_at=now-timedelta(days=days,seconds=ident),stream=stream,status=status,error_code='UPSTREAM_TIMEOUT' if ident==2 else None,latency=latency,trace='{"stages":[]}',body='{"prompt":"large body"}'))
                    app=FastAPI();app.include_router(router)
                    async def session():yield db
                    app.dependency_overrides[get_session]=session
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://acceptance') as client:
                        self.assertEqual((await client.get('/api/admin/call-logs/options')).status_code,401)
                        app.dependency_overrides[administrator]=lambda:SimpleNamespace(id=1)
                        statements.clear()
                        response=await client.get('/api/admin/call-logs',params={'status':'failed','stream':'true','min_latency_ms':5000,'request_model':'virtual','logical_model':'actual'})
                        self.assertEqual(response.status_code,200,response.text)
                        data=response.json()['data'];self.assertEqual(data['total'],1);self.assertEqual(data['items'][0]['request_id'],'fixture-2')
                        self.assertNotIn('trace',data['items'][0]);self.assertNotIn('request_body',data['items'][0]);self.assertIsNotNone(data['start'])
                        self.assertTrue(all('call_logs.trace' not in sql and 'call_logs.request_body' not in sql and 'call_logs.response_body' not in sql for sql in statements))
                        self.assertEqual((await client.get('/api/admin/call-logs?stream=false')).json()['data']['total'],1)
                        self.assertEqual((await client.get('/api/admin/call-logs?status=failed')).json()['data']['total'],2)
                        self.assertEqual((await client.get('/api/admin/call-logs?model=actual&model_scope=request')).json()['data']['total'],0)
                        self.assertEqual((await client.get('/api/admin/call-logs?model=actual&model_scope=actual')).json()['data']['total'],3)
                        history=(await client.get('/api/admin/call-logs?request_id=fixture-4')).json()['data'];self.assertEqual(history['total'],1);self.assertIsNone(history['start'])
                        page=(await client.get('/api/admin/call-logs?page=2&page_size=1')).json()['data'];self.assertEqual(page['items'][0]['request_id'],'fixture-2');self.assertEqual(page['total'],3)
                        detail=(await client.get('/api/admin/call-logs/fixture-2')).json()['data'];self.assertEqual(detail['request_body']['prompt'],'large body')
                        opts=await client.get('/api/admin/call-logs/options');self.assertEqual(opts.status_code,200);self.assertIn({'value':'UPSTREAM_TIMEOUT','label':'UPSTREAM_TIMEOUT'},opts.json()['data']['error_code'])
                        self.assertNotIn('secret',opts.text.lower())
                        for params in [{'min_latency_ms':-1},{'min_latency_ms':'NaN'},{'page_size':101},{'stream':'bad'},{'start':now.isoformat(),'end':(now+timedelta(days=32)).isoformat()}]:
                            self.assertEqual((await client.get('/api/admin/call-logs',params=params)).status_code,422)
                await transaction.rollback()
        finally:await engine.dispose()
