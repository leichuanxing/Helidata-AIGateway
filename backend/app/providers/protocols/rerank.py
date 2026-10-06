import math
from app.providers.base import ProviderFailure
def validate(data,payload=None):
    rows=data.get('results');indexes=set()
    if not isinstance(rows,list):raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
    for row in rows:
        if not isinstance(row,dict):raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
        index,score=row.get('index'),row.get('relevance_score')
        if type(index) is not int or index<0 or index in indexes or payload and index>=len(payload['documents']) or type(score) not in (int,float) or not math.isfinite(score):raise ProviderFailure('UPSTREAM_INVALID_RESPONSE')
        indexes.add(index)
