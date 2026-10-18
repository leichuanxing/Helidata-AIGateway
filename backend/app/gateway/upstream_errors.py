from app.core.exceptions import APIError
from app.providers.base import ProviderFailure


def translate(error):
    code = error.code if isinstance(error, ProviderFailure) else 'UPSTREAM_TIMEOUT'
    status = 503 if code == 'UPSTREAM_POOL_EXHAUSTED' else 504 if code == 'UPSTREAM_TIMEOUT' else 502
    if isinstance(error, ProviderFailure) and error.status == 429:
        status, code = 503, 'UPSTREAM_RATE_LIMITED'
    elif isinstance(error, ProviderFailure) and error.status in (400, 422):
        status, code = 400, 'UPSTREAM_REQUEST_REJECTED'
    result=APIError(status, code, '上游调用失败，请检查模型参数或账号连接状态')
    result.upstream_status=error.status if isinstance(error,ProviderFailure) else None
    return result
