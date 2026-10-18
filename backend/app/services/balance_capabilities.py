"""One capability rule for routing configuration, catalog and node checks."""
from app.providers.operations import compatible

OPERATIONS={'text':('chat','responses','messages'),'reasoning':('chat','responses','messages'),
            'multimodal':('chat','responses','messages'),'embedding':('embeddings',),
            'rerank':('rerank',),'image':('images',)}

def operation_for(kind,provider):
    return next((operation for operation in OPERATIONS.get(kind,()) if compatible(operation,provider)),None)
