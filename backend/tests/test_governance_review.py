"""Version and durable job admission boundaries without provider calls."""
import unittest
from types import SimpleNamespace as NS
from pydantic import ValidationError
from app.api.admin.compliance import WordInput,PolicyInput,public,check_version
from app.api.admin.smart_route import retry_sample
from app.models.compliance import CompliancePolicy
from app.core.exceptions import APIError

class GovernanceReviewTests(unittest.TestCase):
 def test_busy_vector_jobs_are_not_requeued_but_edits_invalidate(self):
  for status,requested in [('processing',True),('pending',True)]:
   row=NS(vector_status=status,vector_requested=requested,revision=7)
   self.assertFalse(retry_sample(row,NS(id=1)));self.assertEqual(row.revision,7)
   self.assertTrue(retry_sample(row,NS(id=1),force=True));self.assertEqual(row.revision,8)
  row=NS(vector_status='pending',vector_requested=False,revision=1)
  self.assertTrue(retry_sample(row,NS(id=1)));self.assertTrue(row.vector_requested)
 def test_policy_version_covers_scope_and_status(self):
  row=CompliancePolicy(id=1,name='policy',word_ids=[1],sample_ids=[],group_ids=[],models=[],threshold=.8,status='enabled',action='block',description='',risk='high')
  token=public(row)['version'];body=PolicyInput(name='policy',expected_version=token)
  check_version(body,row)
  row.word_ids=[1,2]
  with self.assertRaises(APIError) as error:check_version(body,row)
  self.assertEqual(error.exception.status_code,409)
  check_version(PolicyInput(name='legacy-client'),row)
 def test_invalid_versions_and_boolean_policy_ids_are_rejected(self):
  for values in [{'pattern':'x','policy_id':True},{'pattern':'x','expected_version':'invalid'}]:
   with self.assertRaises(ValidationError):WordInput(**values)

 def test_route_sample_revision_is_optional_but_strict_and_positive(self):
  from app.schemas.routing import RouteSampleInput
  self.assertIsNone(RouteSampleInput(prompt='sample',classification='simple').expected_revision)
  self.assertEqual(RouteSampleInput(prompt='sample',classification='simple',expected_revision=7).expected_revision,7)
  for revision in (0,-1,True,'7'):
   with self.assertRaises(ValidationError):RouteSampleInput(prompt='sample',classification='simple',expected_revision=revision)
