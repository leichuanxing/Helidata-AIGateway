"""Lightweight settings and brand asset regression without production writes.

Enable SETTINGS_POSTGRES_TEST=1 to verify projection and saves in a temporary
settings table inside an externally rolled-back transaction.
"""
import os,base64,unittest
from unittest.mock import patch
from types import SimpleNamespace as NS
from fastapi import FastAPI
import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine,AsyncSession
from sqlalchemy.pool import NullPool
from app.api.admin.settings import router
from app.core.database import get_session
from app.core.dependencies import super_administrator
from app.services import operations_settings as operations


@unittest.skipUnless(os.environ.get('SETTINGS_POSTGRES_TEST')=='1','PostgreSQL integration explicitly enabled')
class SettingsAssetsTest(unittest.IsolatedAsyncioTestCase):
    async def test_compact_reads_cached_images_and_preserved_assets_on_save(self):
        from app.core.config import get_settings
        engine=create_async_engine(get_settings().database.url(),poolclass=NullPool,connect_args={'ssl':False})
        try:
            async with engine.connect() as connection:
                transaction=await connection.begin()
                async with AsyncSession(bind=connection) as db:
                    await db.execute(text('CREATE TEMP TABLE system_settings (LIKE public.system_settings INCLUDING ALL) ON COMMIT DROP'))
                    await db.execute(text('INSERT INTO system_settings SELECT * FROM public.system_settings'))
                    original=await operations.document(db,private=True)
                    operations.apply(original)
                    app=FastAPI();app.include_router(router)
                    async def session():yield db
                    app.dependency_overrides[get_session]=session
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://acceptance') as client:
                        self.assertEqual((await client.get('/api/admin/settings?include_assets=false')).status_code,401)
                        app.dependency_overrides[super_administrator]=lambda:NS(id=1)
                        legacy=await client.get('/api/admin/settings')
                        compact=await client.get('/api/admin/settings?include_assets=false')
                        self.assertEqual(compact.status_code,200)
                        a,b=legacy.json()['data'],compact.json()['data']
                        self.assertLess(len(compact.content),5000)
                        self.assertNotIn('secret_encrypted',b['elasticsearch'])
                        self.assertEqual(b['elasticsearch']['secret'],'')
                        self.assertEqual(a['revision'],b['revision'])
                        for key in a:
                            if key!='basic':self.assertEqual(a[key],b[key])
                        for kind in ('logo','icon'):
                            if not a['basic'][kind]:continue
                            asset=await client.get(b['basic'][kind])
                            self.assertEqual(asset.status_code,200)
                            self.assertEqual(asset.content,base64.b64decode(a['basic'][kind].split(',',1)[1]))
                            self.assertEqual(asset.headers['content-type'],'image/png')
                            self.assertIn('max-age=86400',asset.headers['cache-control'])
                            cached=await client.get(b['basic'][kind],headers={'If-None-Match':asset.headers['etag']})
                            self.assertEqual(cached.status_code,304)
                        public=await client.get('/api/public/settings')
                        self.assertLess(len(public.content),1000)
                        self.assertNotIn('data:image',public.text)
                        # Equivalent browser save omits existing image references.
                        with patch('app.api.admin.settings.audit'):
                            saved=await client.patch('/api/admin/settings?include_assets=false',json={'revision':b['revision'],'basic':{'system_name':b['basic']['system_name']}})
                        self.assertEqual(saved.status_code,200)
                        stored=await operations.document(db,private=True)
                        self.assertEqual(stored['basic']['logo'],original['basic']['logo'])
                        self.assertEqual(stored['basic']['icon'],original['basic']['icon'])
                        self.assertEqual(stored['revision'],original['revision']+1)
                        for kind in ('logo','icon'):
                            if not b['basic'][kind]:continue
                            stale=await client.get(b['basic'][kind])
                            self.assertEqual(stale.status_code,307)
                            self.assertEqual(stale.headers['cache-control'],'no-store')
                        conflict=await client.patch('/api/admin/settings?include_assets=false',json={'revision':b['revision'],'basic':{'system_name':'conflict'}})
                        self.assertEqual(conflict.status_code,409)
                        invalid=await client.patch('/api/admin/settings',json={'revision':stored['revision'],'basic':{'logo':b['basic']['logo']}})
                        self.assertEqual(invalid.status_code,422)
                        self.assertEqual((await client.get('/api/public/settings/assets/password')).status_code,422)
                        print(f'PASS compact response: {len(legacy.content)} -> {len(compact.content)} bytes; public {len(public.content)} bytes; cached PNG bytes unchanged; authenticated saves preserve assets')
                await transaction.rollback()
        finally:await engine.dispose()


if __name__=='__main__':unittest.main()
