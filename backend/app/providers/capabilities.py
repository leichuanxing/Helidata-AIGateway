"""Provider/plan operation capabilities, reviewed against vendor docs 2026-10-19."""
RERANK='openai-rerank'
IMAGES='openai-images'

def enrich_capabilities(catalog):
    additions={'aliyun':[RERANK,IMAGES],'siliconflow':[RERANK,IMAGES],
               'volcengine':[IMAGES],'gemini':[IMAGES],'vllm':[RERANK],
               'sglang':[RERANK,IMAGES]}
    for code,names in additions.items():
        catalog[code]['supported_protocols']=list(dict.fromkeys(catalog[code]['supported_protocols']+names))
    catalog['aliyun']['protocol_urls'][RERANK]='https://dashscope.aliyuncs.com/api/v1'
    catalog['gemini']['operations']=['chat','messages','embeddings','images']
    notes={
        'openai':{'image':'使用支持 Images API 的图像模型；普通对话模型不能直接用于生图。','rerank':'当前 OpenAI API 接入没有独立重排序端点。'},
        'aliyun':{'image':'支持 OpenAI 兼容 Images API 的千问图像模型；旧版原生/异步生图模型不适用。','rerank':'网关转换为 DashScope 文本排序接口；基础地址填写 /api/v1，可使用业务空间专属域名。'},
        'siliconflow':{'image':'支持硅基流动生图接口，返回图片 URL；单次一张，暂不提供 b64_json 或批量调用。','rerank':'使用重排序专用模型，支持 /v1/rerank。'},
        'volcengine':{'image':'使用 Seedream 等支持 /images/generations 的模型及按量付费 Key。'},
        'gemini':{'image':'使用支持 OpenAI 兼容 Images API 的 Gemini 图像模型，建议 response_format=b64_json。'},
        'vllm':{'rerank':'需部署支持 /v1/rerank 的 pooling/score 模型；普通聊天实例不具备此能力。','image':'普通 vLLM 文本服务没有 Images API；独立图像服务可通过 Custom OpenAI 接入。'},
        'sglang':{'rerank':'需启动支持 /v1/rerank 的重排模型实例。','image':'需指向 SGLang Diffusion 的 Images API 服务；普通文本实例不能生图。'},
        'custom_openai':{'image':'仅在上游实际提供 /images/generations 时选择。','rerank':'仅在上游实际提供 /rerank（Jina/Cohere 兼容）时选择。'},
        'ollama':{'image':'当前 Ollama OpenAI 兼容接入未适配其原生生图接口。','rerank':'当前 Ollama 接入未提供独立 rerank 协议。'},
    }
    native_image={'tencent','baidu','minimax','openrouter'}
    for code,entry in catalog.items():
        own=notes.get(code,{})
        entry['category_notes']={
            'image':own.get('image','供应商提供其他格式的生图接口，当前预设尚未适配；兼容代理可使用 Custom OpenAI。' if code in native_image else '当前供应商预设没有可用的 Images API 生图接入。'),
            'rerank':own.get('rerank','当前供应商预设尚未接入重排序协议；不是该供应商所有产品能力的判断。'),
        }
        for plan in entry['account_types'].values():
            if 'supported_protocols' in plan:
                plan['category_notes']={category:'当前套餐接入仅支持已列出的对话协议，请使用按量付费或独立服务账号。'
                    for category,protocol in [('image',IMAGES),('rerank',RERANK)] if protocol not in plan['supported_protocols']}
