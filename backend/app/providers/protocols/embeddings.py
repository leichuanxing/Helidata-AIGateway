import math
from app.providers.base import ProviderFailure
def validate(data,payload=None):
    rows=data.get('data')
    if data.get('object')!='list' or not isinstance(rows,list) or not rows:raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
    indexes=set()
    for row in rows:
        if not isinstance(row,dict) or row.get('object')!='embedding' or type(row.get('index')) is not int or row['index']<0 or row['index'] in indexes:raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
        indexes.add(row['index']);vector=row.get('embedding')
        if not (isinstance(vector,str) and vector or isinstance(vector,list) and vector and all(type(x) in (int,float) and math.isfinite(x) for x in vector)):raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
