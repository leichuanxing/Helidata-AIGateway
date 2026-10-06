from app.providers.base import ProviderFailure
def validate(data,payload=None):
    rows=data.get('data')
    if type(data.get('created')) is not int or not isinstance(rows,list) or not rows or any(not isinstance(r,dict) or not (isinstance(r.get('url'),str) and r['url'] or isinstance(r.get('b64_json'),str) and r['b64_json']) for r in rows):raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
