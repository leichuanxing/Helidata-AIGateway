"""Shared bounded catalog validation and safe public discovery errors."""
from app.providers.base import ProviderFailure

async def discover_models(adapter):
    models=await adapter.list_models()
    names=list(dict.fromkeys(item['id'] for item in models))
    if any(not name.strip() or len(name)>200 or any(ord(c)<32 or ord(c)==127 for c in name) for name in names):
        raise ProviderFailure('UPSTREAM_INVALID_RESPONSE',adapter.http_status,True,'unknown',adapter.latency_ms)
    return names

def discovery_message(error):
    if error.status in (404,405,501):return '上游未提供此模型列表接口，请核对服务地址，或手工添加真实模型映射'
    messages={
        'UPSTREAM_AUTH_FAILED':'模型发现鉴权失败，请检查 API Key、地域和业务空间权限',
        'UPSTREAM_TIMEOUT':'模型发现超时，请检查上游响应或稍后重试',
        'UPSTREAM_NETWORK_ERROR':'无法连接模型服务，请检查地址、网络和 HTTP 代理',
        'UPSTREAM_INVALID_RESPONSE':'上游模型列表格式无效，请核对所选供应商、协议及服务地址',
        'UPSTREAM_RESPONSE_TOO_LARGE':'上游模型列表超过大小或条数限制，请手工添加所需模型',
        'UPSTREAM_POOL_EXHAUSTED':'上游连接池繁忙，请稍后重试',
        'UNSUPPORTED_OPERATION':'当前接入未提供模型发现，请手工添加真实模型映射',
    }
    return messages.get(error.code,'模型发现失败，请检查上游服务状态'+(f'（HTTP {error.status}）' if error.status else ''))
