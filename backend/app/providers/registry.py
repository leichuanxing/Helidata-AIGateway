from app.providers.base import OpenAIProvider,CustomOpenAIProvider,AnthropicProvider,OllamaProvider
PROVIDER_TYPES={
    'openai':{'name':'OpenAI','protocols':['openai'],'base_url':'https://api.openai.com/v1','key_required':True},
    'deepseek':{'name':'DeepSeek','protocols':['openai'],'base_url':'https://api.deepseek.com','key_required':True},
    'anthropic':{'name':'Anthropic','protocols':['anthropic'],'base_url':'https://api.anthropic.com/v1','key_required':True},
    'aliyun':{'name':'Aliyun','protocols':['openai'],'base_url':'https://dashscope.aliyuncs.com/compatible-mode/v1','key_required':True},
    'vllm':{'name':'vLLM','protocols':['openai'],'base_url':'','key_required':False},
    'sglang':{'name':'SGLang','protocols':['openai'],'base_url':'','key_required':False},
    'ollama':{'name':'Ollama','protocols':['ollama','openai'],'base_url':'','key_required':False},
    'custom_openai':{'name':'Custom OpenAI','protocols':['openai'],'base_url':'','key_required':False},
}
ADAPTERS={'openai':OpenAIProvider,'anthropic':AnthropicProvider,'ollama':OllamaProvider}


def build_adapter(provider,key):
    adapter=CustomOpenAIProvider if provider.provider_type=='custom_openai' else ADAPTERS[provider.protocol]
    return adapter(provider.base_url,key,provider.proxy)
