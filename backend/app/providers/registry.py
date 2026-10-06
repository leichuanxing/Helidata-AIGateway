from app.providers.base import OpenAIProvider,CustomOpenAIProvider,AnthropicProvider,OllamaProvider
PROVIDER_TYPES={
    'openai':{'name':'OpenAI','protocols':['openai'],'base_url':'https://api.openai.com/v1','key_required':True},
    'deepseek':{'name':'DeepSeek','protocols':['openai'],'base_url':'https://api.deepseek.com','key_required':True},
    'zhipu':{'name':'智谱开放平台','protocols':['openai'],'base_url':'https://open.bigmodel.cn/api/paas/v4','key_required':True,
        'operations':['chat','messages','embeddings','images'],
        'description':'使用智谱开放平台 API Key，按平台规则计费。本接入使用 paas/v4 接口，支持对话、嵌入和图像生成；Responses 使用独立端点，当前接入不支持。填写账户可用的上游模型名称；模型列表接口不可用时请手动添加映射。',
        'docs_url':'https://docs.bigmodel.cn/cn/api/introduction'},
    'zhipu_coding_plan':{'name':'智谱 Coding Plan','protocols':['openai'],'base_url':'https://open.bigmodel.cn/api/coding/paas/v4','key_required':True,
        'operations':['chat','messages'],
        'description':'使用 Coding Plan 套餐 API Key。本接入使用 OpenAI Chat Completion，支持普通及流式对话；Responses 使用独立端点，当前接入不支持。仅限官方支持的编程工具和产品环境，模型及额度以套餐为准。模型列表接口不可用时请手动添加映射。',
        'docs_url':'https://docs.bigmodel.cn/cn/coding-plan/quick-start'},
    'anthropic':{'name':'Anthropic','protocols':['anthropic'],'base_url':'https://api.anthropic.com/v1','key_required':True},
    'aliyun':{'name':'Aliyun','protocols':['openai'],'base_url':'https://dashscope.aliyuncs.com/compatible-mode/v1','key_required':True},
    'vllm':{'name':'vLLM','protocols':['openai'],'base_url':'','key_required':False},
    'sglang':{'name':'SGLang','protocols':['openai'],'base_url':'','key_required':False},
    'ollama':{'name':'Ollama','protocols':['ollama','openai'],'base_url':'','key_required':False},
    'custom_openai':{'name':'Custom OpenAI','protocols':['openai'],'base_url':'','key_required':False},
}
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
