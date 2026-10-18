import unittest
from pathlib import Path
from pydantic import ValidationError
from app.providers.registry import PROVIDER_TYPES,build_adapter
from app.schemas.provider import ProviderCreate
from app.api.admin.providers import validate_input
from app.core.exceptions import APIError
from types import SimpleNamespace


class ProviderPresetTests(unittest.TestCase):
    def test_independent_rerank_category_and_legacy_vector(self):
        from app.services.provider_rules import category_mapping
        from app.schemas.models import MappingInput
        base=dict(name='rerank',provider_type='custom_openai',protocol='openai',base_url='http://127.0.0.1:8000/v1',protocol_type='rerank',protocol_config={'openai-rerank':{}})
        account=ProviderCreate(**base)
        validate_input(account,False)
        mapping=MappingInput(logical_model='rank',upstream_model='rank',model_type='rerank')
        category_mapping(account,mapping)
        category_mapping(SimpleNamespace(protocol_type='vector'),mapping)
        with self.assertRaises(APIError):category_mapping(account,MappingInput(logical_model='embed',upstream_model='embed',model_type='embedding'))
        for changes in ({'provider_type':'openai'},{'protocol_config':{'openai-embeddings':{}}}):
            with self.assertRaises(APIError):validate_input(ProviderCreate(**{**base,**changes}),True)

    def test_every_provider_and_plan_has_valid_address_and_protocols(self):
        self.assertEqual(len(PROVIDER_TYPES),20)
        for code,entry in PROVIDER_TYPES.items():
            for name,plan in entry['account_types'].items():
                with self.subTest(provider=code,plan=name):
                    body=ProviderCreate(name='preset',provider_type=code,protocol=entry['protocols'][0],base_url=plan['base_url'],account_type=name,api_key='test-key')
                    validate_input(body,True)
                    self.assertTrue(entry['icon_url'].startswith('/providers/'))
                    self.assertTrue(plan.get('supported_protocols',entry['supported_protocols']))

    def test_protocol_specific_addresses_reach_correct_adapters(self):
        expected=[('deepseek','standard','responses','https://api.deepseek.com'),
                  ('deepseek','standard','messages','https://api.deepseek.com/anthropic/v1'),
                  ('zhipu_coding_plan','standard','responses','https://open.bigmodel.cn/api/v1'),
                  ('zhipu_coding_plan','global_token_plan','messages','https://api.z.ai/api/anthropic/v1'),
                  ('tencent','cn_token_plan','messages','https://api.lkeap.cloud.tencent.com/plan/anthropic/v1')]
        from app.providers.configuration import NATIVE
        for code,plan,operation,url in expected:
            entry=PROVIDER_TYPES[code];account=entry['account_types'][plan]
            urls={**entry['protocol_urls'],**account.get('protocol_urls',{})}
            name=NATIVE[operation]
            row=SimpleNamespace(provider_type=code,protocol='anthropic' if operation=='messages' else 'openai',
                base_url=account['base_url'],proxy=None,protocol_config={name:{'api_url':urls.get(name,account['base_url']),'path_prefix':'','auth_type':'x-api-key' if operation=='messages' else 'bearer'}})
            adapter=build_adapter(row,'test-key',operation)
            self.assertEqual(adapter.base_url,url)

    def test_parameter_boundaries_and_required_key(self):
        base=dict(name='account',provider_type='openai',protocol='openai',base_url='https://api.openai.com/v1')
        for field,value in [('name','   '),('priority',-1),('priority',100001),('max_concurrency',0),('max_concurrency',100001),('proxy','http://proxy.example/path'),('base_url','https://user:secret@example.com'),('base_url','https://example.com?key=secret'),('api_key',' key '),('account_type','invalid-plan')]:
            with self.subTest(field=field,value=value),self.assertRaises(ValidationError):ProviderCreate(**{**base,field:value})
        with self.assertRaises(APIError):validate_input(ProviderCreate(**base),False)
        with self.assertRaises(APIError):validate_input(ProviderCreate(**{**base,'account_type':'unknown'}),True)
        ProviderCreate(**{**base,'priority':100000,'max_concurrency':100000})

    def test_duplicate_mapping_and_native_protocol_mix_rejected(self):
        base=dict(name='account',provider_type='openai',protocol='openai',base_url='https://api.openai.com/v1')
        mapping={'logical_model':'same','upstream_model':'upstream'}
        with self.assertRaises(ValidationError):ProviderCreate(**base,model_mappings=[mapping,mapping])
        with self.assertRaises(ValidationError):ProviderCreate(**base,protocol_config={'ollama':{},'openai-completions':{}})
        with self.assertRaises(ValidationError):ProviderCreate(**base,protocol_config={'openai-completions':{'auth_type':'x-api-key'}})
