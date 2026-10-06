from app.providers.base import OpenAIProvider,CustomOpenAIProvider,AnthropicProvider,OllamaProvider
PROVIDER_TYPES={
    'openai':{'name':'OpenAI','protocols':['openai'],'base_url':'https://api.openai.com/v1','key_required':True},
    'deepseek':{'name':'DeepSeek','protocols':['openai'],'base_url':'https://api.deepseek.com','key_required':True,'operations':['chat','messages']},
    'zhipu':{'name':'智谱开放平台','protocols':['openai'],'base_url':'https://open.bigmodel.cn/api/paas/v4','key_required':True,
        'operations':['chat','messages','embeddings','images'],
        'description':'使用智谱开放平台 API Key，按平台规则计费。本接入使用 paas/v4 接口，支持对话、嵌入和图像生成；Responses 使用独立端点，当前接入不支持。填写账户可用的上游模型名称；模型列表接口不可用时请手动添加映射。',
        'docs_url':'https://docs.bigmodel.cn/cn/api/introduction'},
    'zhipu_coding_plan':{'name':'智谱 Coding Plan','protocols':['openai'],'base_url':'https://open.bigmodel.cn/api/coding/paas/v4','key_required':True,
        'operations':['chat','messages'],
        'description':'使用 Coding Plan 套餐 API Key。本接入使用 OpenAI Chat Completion，支持普通及流式对话；Responses 使用独立端点，当前接入不支持。仅限官方支持的编程工具和产品环境，模型及额度以套餐为准。模型列表接口不可用时请手动添加映射。',
        'docs_url':'https://docs.bigmodel.cn/cn/coding-plan/quick-start'},
    'anthropic':{'name':'Anthropic','protocols':['anthropic'],'base_url':'https://api.anthropic.com/v1','key_required':True},
    'aliyun':{'name':'阿里云百炼','protocols':['openai'],'base_url':'https://dashscope.aliyuncs.com/compatible-mode/v1','key_required':True,
        'account_types':{'standard':{'name':'按量付费','base_url':'https://dashscope.aliyuncs.com/compatible-mode/v1'},
            'coding_plan':{'name':'Coding Plan','base_url':'https://coding.dashscope.aliyuncs.com/v1'},
            'token_plan':{'name':'Token Plan','base_url':'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1'}},
        'docs_url':'https://help.aliyun.com/en/model-studio/base-url'},
    'vllm':{'name':'vLLM','protocols':['openai'],'base_url':'','key_required':False},
    'sglang':{'name':'SGLang','protocols':['openai'],'base_url':'','key_required':False},
    'ollama':{'name':'Ollama','protocols':['ollama','openai'],'base_url':'','key_required':False},
    'custom_openai':{'name':'Custom OpenAI','protocols':['openai'],'base_url':'','key_required':False},
}
# Catalog entries use the existing protocol adapters. No preset model names are invented.
for code,name,url,plans in [
    ('tencent','腾讯云 TokenHub','',('standard','cn_token_plan','global_token_plan','cn_payg','global_payg')),
    ('baidu','百度智能云千帆','',('standard','coding_plan','token_plan')),
    ('siliconflow','硅基流动','https://api.siliconflow.cn/v1',('standard',)),
    ('volcengine','火山引擎方舟','https://ark.cn-beijing.volces.com/api/v3',('standard','coding_plan','token_plan')),
    ('minimax','MiniMax（中国）','',('standard',)),
    ('xiaomi','小米','',('standard','token_plan')),
    ('kimi','Kimi','',('standard','cn_token_plan','global_token_plan','cn_payg','global_payg')),
    ('opencode','OpenCode','',('standard','go','zen')),
    ('openrouter','OpenRouter','',('standard',)),
    ('gemini','Gemini（OpenAI 兼容）','',('standard',)),
]:
    labels={'standard':'按量付费 / 标准账号','coding_plan':'Coding Plan','token_plan':'Token Plan',
        'cn_token_plan':'中国区 Token Plan','global_token_plan':'全球区 Token Plan','cn_payg':'中国区按量付费',
        'global_payg':'全球区按量付费','go':'Go（订阅计划）','zen':'Zen（按量付费）'}
    PROVIDER_TYPES[code]={'name':name,'protocols':['openai'],'base_url':url,'key_required':True,
        'account_types':{p:{'name':labels[p],'base_url':url if p=='standard' else ''} for p in plans},
        'description':'服务地址、协议路径及模型名称以所选账户/套餐控制台为准。请核对套餐专用端点，避免使用按量端点产生额外费用。',
        'docs_url':'https://docs.fit2cloud.com/ai-gateway/admin-user-manual/account_pool/'}
PROVIDER_TYPES['volcengine']['account_types']['coding_plan']['base_url']='https://ark.cn-beijing.volces.com/api/coding/v3'
PROVIDER_TYPES['gemini']['operations']=['chat','messages','embeddings']
PROVIDER_TYPES['gemini']['base_url']='https://generativelanguage.googleapis.com/v1beta/openai'
PROVIDER_TYPES['gemini']['account_types']['standard']['base_url']=PROVIDER_TYPES['gemini']['base_url']
PROVIDER_TYPES['gemini']['description']='通过 Gemini 的 OpenAI 兼容端点接入文本和向量模型；此接入不使用 Gemini 原生 generateContent 协议。服务 URL 请填写官方兼容端点。'
PROVIDER_TYPES['gemini']['docs_url']='https://ai.google.dev/gemini-api/docs/openai'
PROVIDER_TYPES['anthropic']['operations']=['chat','messages']
PROVIDER_TYPES['ollama']['operations']=['chat','messages','embeddings']
PROVIDER_TYPES['zhipu']['account_types']={'standard':{'name':'中国区按量付费','base_url':PROVIDER_TYPES['zhipu']['base_url']},
    'global_payg':{'name':'全球区按量付费','base_url':''}}
PROVIDER_TYPES['zhipu_coding_plan']['account_types']={'standard':{'name':'中国区 Coding / Token Plan','base_url':PROVIDER_TYPES['zhipu_coding_plan']['base_url']},
    'global_token_plan':{'name':'全球区 Token Plan','base_url':''}}
ADAPTERS={'openai':OpenAIProvider,'anthropic':AnthropicProvider,'ollama':OllamaProvider}


def build_adapter(provider,key,operation=None):
    from app.providers.configuration import select_protocol,configurations,NAMES
    from app.providers.base import ProviderFailure
    name=select_protocol(provider,operation)
    if name is None:raise ProviderFailure('UNSUPPORTED_OPERATION')
    protocol=NAMES[name];route=configurations(provider)[name]
    adapter=CustomOpenAIProvider if provider.provider_type=='custom_openai' and protocol=='openai' else ADAPTERS[protocol]
    result=adapter(provider.base_url.rstrip('/')+route['path_prefix'],key or '',provider.proxy)
    result.auth_type=route['auth_type'];result.wire_protocol=protocol;result.protocol_name=name
    return result
