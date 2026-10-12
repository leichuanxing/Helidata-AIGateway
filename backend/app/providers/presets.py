"""Documented account defaults, separate from persisted provider connections.

Changing this catalog never rewrites an existing account. Verified 2026-10-12.
Protocol URLs include the version prefix: adapters append the operation only.
"""
CHAT='openai-completions'
RESPONSES='openai-responses'
MESSAGES='anthropic-messages'
EMBEDDINGS='openai-embeddings'
IMAGES='openai-images'


def enrich(catalog):
    defaults={
        'openai':('https://api.openai.com/v1',[CHAT,RESPONSES,EMBEDDINGS,IMAGES],'https://platform.openai.com/docs/api-reference'),
        'deepseek':('https://api.deepseek.com/v1',[CHAT,RESPONSES,MESSAGES],'https://api-docs.deepseek.com/'),
        'zhipu':('https://open.bigmodel.cn/api/paas/v4',[CHAT,EMBEDDINGS,IMAGES],'https://docs.bigmodel.cn/cn/api/introduction'),
        'zhipu_coding_plan':('https://open.bigmodel.cn/api/coding/paas/v4',[CHAT,RESPONSES,MESSAGES],'https://docs.bigmodel.cn/cn/coding-plan/tool/others'),
        'anthropic':('https://api.anthropic.com/v1',[MESSAGES],'https://platform.claude.com/docs/en/api/overview'),
        'aliyun':('https://dashscope.aliyuncs.com/compatible-mode/v1',[CHAT,EMBEDDINGS],'https://help.aliyun.com/zh/model-studio/base-url'),
        'vllm':('http://127.0.0.1:8000/v1',[CHAT,EMBEDDINGS],'https://docs.vllm.ai/en/latest/serving/openai_compatible_server/'),
        'sglang':('http://127.0.0.1:30000/v1',[CHAT,EMBEDDINGS],'https://docs.sglang.io/docs/basic_usage/send_request'),
        'ollama':('http://127.0.0.1:11434/v1',[CHAT,EMBEDDINGS],'https://docs.ollama.com/api/openai-compatibility'),
        'custom_openai':('http://127.0.0.1:8000/v1',[CHAT,RESPONSES,MESSAGES,EMBEDDINGS,IMAGES,'openai-rerank'],'https://platform.openai.com/docs/api-reference'),
        'tencent':('https://tokenhub.tencentmaas.com/v1',[CHAT,RESPONSES,MESSAGES],'https://cloud.tencent.com/document/product/1823/130078'),
        'baidu':('https://qianfan.baidubce.com/v2',[CHAT],'https://cloud.baidu.com/doc/qianfan/s/imlg0beiu'),
        'siliconflow':('https://api.siliconflow.cn/v1',[CHAT,EMBEDDINGS],'https://docs.siliconflow.cn/docs/api/chat-completions-post'),
        'volcengine':('https://ark.cn-beijing.volces.com/api/v3',[CHAT,RESPONSES,EMBEDDINGS],'https://www.volcengine.com/docs/82379/1399008'),
        'minimax':('https://api.minimax.cn/v1',[CHAT],'https://platform.minimax.cn/docs/api-reference/text-openai-api'),
        'xiaomi':('https://api.xiaomimimo.com/v1',[CHAT,MESSAGES],'https://mimo.mi.com/docs/zh-CN/tokenplan/integration/qwencode'),
        'kimi':('https://api.moonshot.cn/v1',[CHAT],'https://platform.kimi.com/docs/get-api-key'),
        'opencode':('https://opencode.ai/zen/v1',[CHAT,RESPONSES,MESSAGES],'https://opencode.ai/docs/zen/'),
        'openrouter':('https://openrouter.ai/api/v1',[CHAT],'https://openrouter.ai/docs/quickstart'),
        'gemini':('https://generativelanguage.googleapis.com/v1beta/openai',[CHAT,EMBEDDINGS],'https://ai.google.dev/gemini-api/docs/openai'),
    }
    for code,(url,protocols,docs) in defaults.items():
        entry=catalog[code]
        entry.update(base_url=url,supported_protocols=protocols,default_protocols=[MESSAGES if code=='anthropic' else CHAT],
                     protocol_urls={},docs_url=docs,icon_url=f'/providers/{code}.svg')
        if 'account_types' not in entry:entry['account_types']={'standard':{'name':'标准账号','base_url':url}}
        entry['account_types']['standard']['base_url']=url
        entry['description']='默认地址适用于所选账号类型；模型能力以供应商及模型实际支持为准。请求端点由网关追加，地址中不要填写 /chat/completions 等端点。'
    for code in ('vllm','sglang','ollama','custom_openai'):
        catalog[code]['url_is_example']=True
        catalog[code]['description']='这是自部署地址示例，请替换为网关容器能访问的实际服务地址。127.0.0.1 指网关容器自身，不能代表另一台服务器或宿主机。'

    def plan(code,name,url,protocols=None,urls=None,note=None):
        item=catalog[code]['account_types'][name]
        item.update(base_url=url)
        if protocols is not None:item['supported_protocols']=protocols
        if urls:item['protocol_urls']=urls
        if note:item['description']=note

    catalog['deepseek']['operations']=['chat','messages','responses']
    catalog['deepseek']['protocol_urls']={RESPONSES:'https://api.deepseek.com',MESSAGES:'https://api.deepseek.com/anthropic/v1'}
    catalog['zhipu']['description']='按量付费的 paas/v4 接口；支持对话、嵌入与图像生成。仅勾选实际使用的协议，模型发现不可用时手动添加映射。'
    plan('zhipu','global_payg','https://api.z.ai/api/paas/v4')
    catalog['zhipu_coding_plan']['operations']=['chat','messages','responses']
    catalog['zhipu_coding_plan']['protocol_urls']={RESPONSES:'https://open.bigmodel.cn/api/v1',MESSAGES:'https://open.bigmodel.cn/api/anthropic/v1'}
    catalog['zhipu_coding_plan']['description']='套餐使用专属 Key；不同协议使用独立服务地址。使用范围及额度以官方套餐条款为准，模型发现不可用时手动添加映射。'
    plan('zhipu_coding_plan','global_token_plan','https://api.z.ai/api/coding/paas/v4',urls={RESPONSES:'https://api.z.ai/api/v1',MESSAGES:'https://api.z.ai/api/anthropic/v1'})
    for name,host in [('coding_plan','coding.dashscope.aliyuncs.com'),('token_plan','token-plan.cn-beijing.maas.aliyuncs.com')]:
        plan('aliyun',name,catalog['aliyun']['account_types'][name]['base_url'],[CHAT,MESSAGES],{MESSAGES:f'https://{host}/apps/anthropic/v1'},'使用套餐专属 Key；官方限定 AI 工具交互式使用，不适用于普通后端服务。请核对套餐使用范围。')
    plan('tencent','cn_payg',catalog['tencent']['base_url'])
    plan('tencent','global_payg','https://tokenhub-intl.tencentmaas.com/v1')
    plan('tencent','cn_token_plan','https://api.lkeap.cloud.tencent.com/plan/v3',[CHAT,MESSAGES],{MESSAGES:'https://api.lkeap.cloud.tencent.com/plan/anthropic/v1'})
    plan('tencent','global_token_plan','https://tokenhub-intl.tencentcloudmaas.com/plan/v3',[CHAT,MESSAGES],{MESSAGES:'https://tokenhub-intl.tencentcloudmaas.com/plan/anthropic/v1'})
    plan('baidu','coding_plan','https://qianfan.baidubce.com/v2/coding',[CHAT,MESSAGES],{MESSAGES:'https://qianfan.baidubce.com/anthropic/coding/v1'})
    plan('baidu','token_plan','https://qianfan.baidubce.com/v2',[CHAT],note='Token Plan 使用控制台签发的对应 Key；当前 OpenAI 兼容基础地址为 /v2，请核对套餐模型及使用范围。')
    plan('volcengine','coding_plan','https://ark.cn-beijing.volces.com/api/coding/v3',[CHAT])
    plan('volcengine','token_plan','https://ark.cn-beijing.volces.com/api/plan/v3',[CHAT],note='使用 Agent / Token Plan 专属 Key；旧 Coding Plan 与当前 Agent Plan 地址不同，请按控制台所购套餐核对。')
    plan('xiaomi','token_plan','https://token-plan-cn.xiaomimimo.com/v1',[CHAT,MESSAGES],{MESSAGES:'https://token-plan-cn.xiaomimimo.com/anthropic/v1'})
    catalog['xiaomi']['protocol_urls']={MESSAGES:'https://api.xiaomimimo.com/anthropic/v1'}
    plan('kimi','cn_payg','https://api.moonshot.cn/v1')
    plan('kimi','global_payg','https://api.moonshot.ai/v1')
    plan('kimi','cn_token_plan','https://api.kimi.com/coding/v1',[CHAT,MESSAGES])
    plan('kimi','global_token_plan','https://api.kimi.ai/coding/v1',[CHAT,MESSAGES])
    plan('opencode','go','https://opencode.ai/zen/go/v1')
    plan('opencode','zen','https://opencode.ai/zen/v1')
    catalog['opencode']['description']='不同模型使用 Chat、Responses 或 Messages 协议；请按官方模型端点表选择。Go 与 Zen 的地址、Key 和计费方式不同。'
    catalog['ollama']['description']+=' 当前新增账号使用 OpenAI 兼容 /v1 端点；原生 /api 协议不用于新增生成账号。'
