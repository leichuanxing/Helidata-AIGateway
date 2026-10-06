"""Wire operation routing. Each response codec lives in its own module."""
from app.core.exceptions import APIError
from app.providers.protocols import responses,messages,embeddings,rerank,images
INFERENCE=('chat','responses','messages','embeddings','rerank','images')
TEXT=('chat','responses','messages')
KINDS={'chat':('text','reasoning','multimodal'),'responses':('text','reasoning','multimodal'),
       'messages':('text','reasoning','multimodal'),'embeddings':('embedding',),'rerank':('rerank',),'images':('image',)}
PATHS={'chat':'/chat/completions','responses':'/responses','messages':'/messages','embeddings':'/embeddings','rerank':'/rerank','images':'/images/generations'}
CODECS={'responses':responses,'messages':messages,'embeddings':embeddings,'rerank':rerank,'images':images}

def compatible(operation,provider):
    if operation=='preflight':return True
    if operation in ('chat','messages'):return provider.protocol in ('openai','anthropic')
    if operation in ('responses','embeddings','images'):return provider.protocol=='openai'
    return operation=='rerank' and provider.protocol=='openai' and provider.provider_type=='custom_openai'

def prepare(ctx):
    from app.providers.translator import chat_to_messages,messages_to_chat
    ctx.wire_operation=ctx.operation
    payload={**ctx.payload,'model':ctx.mapping.upstream_model}
    try:
        if ctx.operation=='chat' and ctx.provider.protocol=='anthropic':
            ctx.wire_operation='messages';payload=chat_to_messages(payload)
        elif ctx.operation=='messages' and ctx.provider.protocol=='openai':
            ctx.wire_operation='chat';payload=messages_to_chat(payload)
    except (KeyError,TypeError,ValueError):
        raise APIError(400,'PROTOCOL_ERROR','请求无法转换协议') from None
    return payload

def validate(ctx,result):
    from app.schemas.chat import ChatCompletion
    from app.providers.translator import chat_result_to_messages,messages_result_to_chat
    if ctx.wire_operation=='responses' and result.get('object')=='response' and result.get('status')=='failed':
        from app.gateway.quota import observe
        from app.providers.protocols.usage import normalized
        from app.providers.base import ProviderFailure
        observe(ctx,{'usage':normalized('responses',result)})
        raise ProviderFailure('UPSTREAM_RESPONSE_FAILED')
    if ctx.wire_operation=='chat':ChatCompletion.model_validate(result)
    else:CODECS[ctx.wire_operation].validate(result,ctx.payload)
    from app.gateway.quota import observe
    from app.providers.protocols.usage import normalized
    observe(ctx,{'usage':normalized(ctx.wire_operation,result)})
    if ctx.operation!=ctx.wire_operation:
        try:result=messages_result_to_chat(result) if ctx.operation=='chat' else chat_result_to_messages(result)
        except (KeyError,TypeError,ValueError):raise APIError(502,'PROTOCOL_ERROR','上游响应无法转换协议') from None
    if 'model' in result:result={**result,'model':ctx.original_model or ctx.logical_model}
    return result
