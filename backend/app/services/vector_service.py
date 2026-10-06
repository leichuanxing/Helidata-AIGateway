"""Shared, pinned vector service. Existing local compliance remains the default."""
import hashlib,json
from app.services import operations_settings as settings
from app.services.local_embedding import VERSION

def version():
    if not settings.vector.get('model'):return VERSION
    return 'upstream:'+hashlib.sha256(json.dumps(settings.vector,sort_keys=True).encode()).hexdigest()

def pin(pairs,model):
    cfg=settings.vector
    return [(m,p) for m,p in pairs if not cfg.get('model') or cfg['model']!=model or p.id==cfg['provider_id']]

async def embed(content,actor_id=None,client_ip=''):
    cfg=dict(settings.vector)
    if not cfg.get('model'):
        from app.services.local_embedding import embed as local
        return await local(content)
    from app.services.admin_embedding import embedding
    vector,_=await embedding(actor_id,cfg['model'],content,client_ip,system=True)
    if cfg!=settings.vector:
        from app.core.exceptions import APIError
        raise APIError(409,'VECTOR_CONFIG_CHANGED','向量服务配置已变化，请重试')
    return [vector]
