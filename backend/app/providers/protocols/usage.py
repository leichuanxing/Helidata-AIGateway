"""Only reported token counts enter accounting; no missing count becomes zero."""
def integer(value):return type(value) is int and 0<=value<=9007199254740991

def normalized(operation,result):
    usage=result.get('usage') or {}
    if not isinstance(usage,dict):return {}
    if operation in ('chat','embeddings','rerank'):return usage
    clean={}
    for source,target in [('input_tokens','prompt_tokens'),('output_tokens','completion_tokens'),('total_tokens','total_tokens')]:
        if integer(usage.get(source)):clean[target]=usage[source]
    if operation=='messages':
        # Anthropic input_tokens excludes cache read/creation. These are reported input components.
        extras=[usage.get(k,0) for k in ('cache_creation_input_tokens','cache_read_input_tokens')]
        if 'prompt_tokens' in clean and all(integer(v) for v in extras):clean['prompt_tokens']+=sum(extras)
        cached=usage.get('cache_read_input_tokens')
        if integer(cached):clean['prompt_tokens_details']={'cached_tokens':cached}
        if all(k in clean for k in ('prompt_tokens','completion_tokens')):
            clean['total_tokens']=clean['prompt_tokens']+clean['completion_tokens']
    else:
        details=usage.get('input_tokens_details') or {}
        if isinstance(details,dict) and integer(details.get('cached_tokens')):clean['prompt_tokens_details']={'cached_tokens':details['cached_tokens']}
    return clean
