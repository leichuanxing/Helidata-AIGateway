"""Select a wire protocol without changing legacy provider URL semantics."""
NAMES={'openai-completions':'openai','openai-responses':'openai','anthropic-messages':'anthropic','ollama':'ollama',
       'openai-embeddings':'openai','openai-images':'openai','openai-rerank':'openai'}
NATIVE={'chat':'openai-completions','responses':'openai-responses','messages':'anthropic-messages',
        'embeddings':'openai-embeddings','images':'openai-images','rerank':'openai-rerank'}


def configurations(provider):
    saved=getattr(provider,'protocol_config',None)
    if saved is not None:return saved
    protocol=provider.protocol
    names=['openai-completions','openai-responses'] if protocol=='openai' else ['anthropic-messages'] if protocol=='anthropic' else ['ollama']
    return {name:{'path_prefix':'','auth_type':'x-api-key' if protocol=='anthropic' else 'bearer'} for name in names}


def select_protocol(provider,operation=None):
    config=configurations(provider)
    preferred=NATIVE.get(operation)
    if preferred in config:return preferred
    # Previously configured accounts used the completions prefix for these operations.
    if operation in ('embeddings','images','rerank') and 'openai-completions' in config:return 'openai-completions'
    if operation=='chat' and 'anthropic-messages' in config:return 'anthropic-messages'
    if operation=='messages' and 'openai-completions' in config:return 'openai-completions'
    if operation not in (None,'models','preflight'):return None
    primary='anthropic-messages' if provider.protocol=='anthropic' else 'ollama' if provider.protocol=='ollama' else 'openai-completions'
    if provider.protocol=='openai' and primary not in config and 'openai-responses' in config:return 'openai-responses'
    return primary if primary in config else next(iter(config),None)
