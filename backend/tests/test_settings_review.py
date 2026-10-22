import asyncio,sys,unittest
from unittest.mock import patch,AsyncMock
from app.schemas.settings import Basic,GatewayOptions,SettingsPatch
from app.core.exceptions import APIError

class SettingsInputTests(unittest.TestCase):
 def test_names_addresses_and_integer_parameters(self):
  self.assertEqual(Basic(system_name=' gateway ').system_name,'gateway')
  for name in ['  ','hidden\x00name']:
   with self.assertRaises(ValueError):Basic(system_name=name)
  self.assertEqual(Basic(public_api_base_url='https://example.com/gateway/v1/').public_api_base_url,'https://example.com/gateway/v1')
  for url in ['https://example.com','https://example.com/v1/chat/completions','https://user:secret@example.com/v1']:
   with self.assertRaises(ValueError):Basic(public_api_base_url=url)
  for count in [True,1.2,'500']:
   with self.assertRaises(ValueError):GatewayOptions(max_concurrency=count)
 def test_empty_and_unexpected_patches_rejected(self):
  for data in [{'revision':1},{'revision':1,'basic':{}},{'revision':1,'gateway':None},{'revision':True,'basic':{'system_name':'gateway'}},{'revision':1,'unknown':True}]:
   with self.assertRaises(ValueError):SettingsPatch.model_validate(data)
  self.assertFalse(SettingsPatch.model_validate({'revision':1,'governance':{'smart_route_enabled':False}}).governance.smart_route_enabled)

class StatusCleanupTests(unittest.IsolatedAsyncioTestCase):
 async def test_cancelled_supervisor_check_reaps_real_subprocess(self):
  from app.services import system_status
  started=asyncio.Event();children=[];original=asyncio.create_subprocess_exec
  async def launch(*args,**kwargs):
   process=await original(sys.executable,'-c','import time;time.sleep(30)',**kwargs)
   children.append(process);started.set();return process
  with patch.object(system_status.asyncio,'create_subprocess_exec',launch):
   task=asyncio.create_task(system_status._processes());await started.wait();task.cancel()
   with self.assertRaises(asyncio.CancelledError):await task
  self.assertIsNotNone(children[0].returncode)
 async def test_cancelled_snapshot_reaps_parallel_checks(self):
  from app.services import system_status
  started=asyncio.Event();closed=[]
  async def wait(label):
   try:started.set();await asyncio.sleep(30)
   finally:closed.append(label)
  with patch.object(system_status,'_cached',None),patch.object(system_status,'_lock',asyncio.Lock()),patch.object(system_status,'dependencies',lambda:wait('checks')),patch.object(system_status,'_processes',lambda:wait('processes')):
   task=asyncio.create_task(system_status.snapshot());await started.wait();task.cancel()
   with self.assertRaises(asyncio.CancelledError):await task
  self.assertEqual(sorted(closed),['checks','processes'])

class VectorTestConsistency(unittest.IsolatedAsyncioTestCase):
 async def test_changed_config_does_not_report_old_test_as_current(self):
  from types import SimpleNamespace as NS
  from app.api.admin.settings import vector_test,VectorTest
  from app.services import operations_settings,admin_embedding
  initial={'revision':1,'vector':{'model':'fixture','provider_id':1}}
  with patch.object(operations_settings,'document',AsyncMock(side_effect=[initial,{**initial,'revision':2}])),patch.object(admin_embedding,'embedding',AsyncMock(return_value=([1,0],'req_fixture'))),patch('app.api.admin.settings.audit'):
   with self.assertRaises(APIError) as caught:
    await vector_test(VectorTest(consent=True,revision=1),NS(client=NS(host='127.0.0.1')),NS(id=1),NS(commit=AsyncMock()))
   self.assertEqual(caught.exception.detail['code'],'VECTOR_CONFIG_CHANGED')
