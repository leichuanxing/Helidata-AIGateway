"""Routing decision boundaries, validation and audit fault regressions."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
from app.core.exceptions import APIError
from app.gateway.smart_routing import prompt
from app.services.route_jobs import embedding_value
from app.services.route_vectors import classify,encode_vector
from app.schemas.routing import RouteConfigInput,parse_samples_csv

class RoutingTests(unittest.TestCase):
    def test_effective_threshold_filters_before_classification(self):
        rows=[{'classification':'complex','similarity':.85},
              {'classification':'simple','similarity':.82,'similarity_threshold':.8}]
        selected=classify(rows,.9,.1)
        self.assertEqual(selected.classification,'simple')
        self.assertEqual(selected.similarity,.82)
        self.assertEqual(classify(rows[:1],.9,.1).reason,'ROUTE_LOW_SIMILARITY')

    def test_empty_tie_gap_and_override(self):
        self.assertEqual(classify([],.75,.1).reason,'ROUTE_NO_SAMPLES')
        rows=[{'classification':'simple','similarity':.9},{'classification':'complex','similarity':.9}]
        self.assertEqual(classify(rows,.75,0).reason,'ROUTE_AMBIGUOUS')
        rows[1]['similarity']=.85
        self.assertEqual(classify(rows,.75,.1).reason,'ROUTE_AMBIGUOUS')
        self.assertEqual(classify(rows,.75,0).classification,'simple')

    def test_prompt_protocols_and_invalid_shapes(self):
        for op,body in [('chat',{'messages':[{'role':'system','content':'skip'},{'role':'user','content':' hello\r\n世界 '}]}),
                        ('responses',{'input':' hello\n世界 '}),
                        ('messages',{'messages':[{'role':'user','content':[{'type':'text','text':'hello\n世界'}]}]})]:
            self.assertEqual(prompt(NS(operation=op,payload=body)),'hello\n世界')
        for value in [None,42,False,{},[42],[{'role':'user','content':[{'type':'text','text':42}]}],
                      [{'role':'user','content':[{'type':'image_url','image_url':{'url':'https://example.com/a.png'}}]}]]:
            with self.assertRaises(APIError) as caught:prompt(NS(operation='chat',payload={'messages':value}))
            self.assertEqual(caught.exception.status_code,400)
        for value in [' '*4,'a'*16001,'hello\x00']:
            with self.assertRaises(APIError):prompt(NS(operation='responses',payload={'input':value}))

    def test_malformed_embeddings_are_explicit_502(self):
        for result in [None,[],{}, {'data':[]},{'data':[None]},{'data':['bad']},
                       {'data':[{'index':True,'embedding':[1,0]}]},
                       {'data':[{'index':0,'embedding':[0,0]}]}]:
            with self.assertRaises(APIError) as caught:embedding_value(result)
            self.assertEqual(caught.exception.status_code,502)
        self.assertEqual(embedding_value({'data':[{'index':0,'embedding':[1,0]}]}),[1,0])
        for vector in [[float('nan'),1],[float('inf'),1],[True,1],[0,0]]:
            with self.assertRaises(APIError):encode_vector(vector)

    def test_csv_normalized_duplicates_and_atomic_errors(self):
        with self.assertRaises(APIError) as caught:parse_samples_csv('prompt,classification\nhello,simple\n hello ,complex'.encode())
        self.assertEqual(caught.exception.status_code,409)
        with self.assertRaises(APIError):parse_samples_csv(b'prompt,classification\nhello,simple\nwrong,invalid')
        self.assertEqual(parse_samples_csv(b'prompt,classification,similarity_threshold\nhello,simple,0.8')[0].similarity_threshold,.8)

    def test_rule_version_optional_but_timezone_required(self):
        body=dict(virtual_model='virtual',embedding_model='embedding',simple_model_group=1,complex_model_group=2)
        self.assertIsNone(RouteConfigInput(**body).expected_updated_at)
        with self.assertRaises(ValueError):RouteConfigInput(**body,expected_updated_at='2026-10-22T00:00:00')
        self.assertIsNotNone(RouteConfigInput(**body,expected_updated_at='2026-10-22T00:00:00Z').expected_updated_at)

class AuditFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_audit_failure_preserves_result_and_does_not_leak_text(self):
        from app.services import route_decisions
        with patch.object(route_decisions.session_factory,'begin',side_effect=RuntimeError('private database details')),self.assertLogs(route_decisions.logger,level='ERROR') as output:
            self.assertFalse(await route_decisions.write({'request_id':'req_test','config_id':1,'status':'failed','reason':'ROUTE_DISABLED','normalized_text':'private input'}))
        self.assertNotIn('private',str(output.output))

