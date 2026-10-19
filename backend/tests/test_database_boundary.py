import asyncio,json,os,subprocess,unittest
from pathlib import Path
from unittest.mock import AsyncMock,patch
import httpx
from starlette.requests import Request
from sqlalchemy.exc import TimeoutError as PoolTimeout,DBAPIError,IntegrityError
from app.core.database import connect_database,DatabaseUnavailable
from app.core.config import get_settings

class DatabaseBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_transport_errors_are_wrapped_only_at_connection_boundary(self):
        for error in (ConnectionRefusedError('secret connection'),TimeoutError('secret connection')):
            with patch('app.core.database.asyncpg.connect',AsyncMock(side_effect=error)):
                with self.assertRaises(DatabaseUnavailable) as caught:await connect_database(get_settings().database)
                self.assertNotIn('secret',str(caught.exception))
        with patch('app.core.database.asyncpg.connect',AsyncMock(side_effect=FileNotFoundError('configuration file'))):
            with self.assertRaises(FileNotFoundError):await connect_database(get_settings().database)

    async def test_real_connection_handshake_timeout_is_wrapped(self):
        writers=[]
        server=await asyncio.start_server(lambda r,w:writers.append(w),'127.0.0.1',0)
        config=get_settings().database.model_copy(update={'port':server.sockets[0].getsockname()[1],'connect_timeout':1})
        try:
            with self.assertRaises(DatabaseUnavailable):await connect_database(config)
        finally:
            server.close()
            # A half-open PostgreSQL handshake must not hold fixture teardown.
            for writer in writers:writer.transport.abort()
            if hasattr(server,'abort_clients'):server.abort_clients()
            await asyncio.wait_for(server.wait_closed(),2)

    async def test_public_status_and_redaction(self):
        from app.main import unexpected
        request=Request({'type':'http','method':'GET','path':'/api/admin/providers','headers':[],'state':{'request_id':'req-boundary'}})
        for error,status in ((DatabaseUnavailable('secret'),503),(PoolTimeout('secret'),503),(DBAPIError('secret',{},Exception('secret'),connection_invalidated=True),503),
            (FileNotFoundError('secret'),500),(IntegrityError('secret',{},Exception('secret')),500)):
            response=await unexpected(request,error)
            self.assertEqual(response.status_code,status);self.assertNotIn(b'secret',response.body)
            self.assertEqual(response.headers.get('Retry-After'),'2' if status==503 else None)
            self.assertEqual(response.headers['Cache-Control'],'no-store')
            self.assertEqual(response.headers['X-Request-ID'],'req-boundary')

@unittest.skipUnless(os.environ.get('AUDIT_DISPOSABLE')=='1','isolated container only')
class DatabaseRestartTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_pool_exhaustion_recovers_after_release(self):
        from sqlalchemy.ext.asyncio import create_async_engine
        config=get_settings().database
        engine=create_async_engine(config.url(),async_creator=lambda:connect_database(config),
            pool_size=1,max_overflow=0,pool_timeout=.1,hide_parameters=True)
        try:
            async with engine.connect():
                with self.assertRaises(PoolTimeout):
                    async with engine.connect():pass
            async with engine.connect() as connection:
                from sqlalchemy import text
                self.assertEqual((await connection.execute(text('SELECT 1'))).scalar(),1)
        finally:await engine.dispose()

    async def test_real_postgres_stop_and_recovery_without_app_restart(self):
        identity=os.environ.get('AUDIT_CONTAINER_ID','')
        self.assertGreaterEqual(len(identity),12);self.assertEqual(os.environ.get('HOSTNAME','')[:12],identity[:12])
        async with httpx.AsyncClient(base_url='http://127.0.0.1',timeout=15) as client:
            signed=await client.post('/api/auth/login',json={'username':'admin','password':Path('/data/config/audit-password.txt').read_text().strip()})
            self.assertEqual(signed.status_code,200);client.headers['Authorization']='Bearer '+signed.json()['data']['access_token']
            subprocess.run(['supervisorctl','stop','postgresql'],check=True,capture_output=True)
            try:
                response=await client.get('/api/admin/providers')
                self.assertEqual(response.status_code,503,response.text[:200])
                self.assertEqual(response.json()['error']['code'],'DEPENDENCY_UNAVAILABLE')
                self.assertEqual(response.headers['Retry-After'],'2');self.assertEqual(response.headers['Cache-Control'],'no-store')
            finally:subprocess.run(['supervisorctl','start','postgresql'],check=True,capture_output=True)
            for _ in range(40):
                if (await client.get('/api/admin/providers')).status_code==200:break
                await asyncio.sleep(.25)
            else:self.fail('database did not recover without application restart')
