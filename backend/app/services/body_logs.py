"""Opt-in bounded body previews. Never capture authentication headers."""
import json
import regex
from app.core.config import get_settings

LIMIT=16*1024
SENSITIVE=regex.compile(r'(?i)(password|authorization|cookie|api.?key|access.?token|refresh.?token|secret|credential)')
TOKENS=regex.compile(r'(?i)(?:sk-[a-z0-9_-]{8,}|bearer\s+[a-z0-9._~-]+|(?:password|api.?key|token|secret)\s*[:=]\s*[^\s,;]+)')


def redact(value,policy):
    rules=[regex.compile(p) for p in policy.get('redaction_rules',[])]
    visited=0
    def text(value):
        value=value[:4096]
        try:
            value=TOKENS.sub('[REDACTED]',value,timeout=.01)
            for rule in rules:value=rule.sub('[REDACTED]',value,timeout=.01)
        except TimeoutError:return '[REDACTION_TIMEOUT]'
        return value
    def walk(item,depth=0):
        nonlocal visited
        visited+=1
        if depth>10 or visited>128:return '[TRUNCATED]'
        if isinstance(item,dict):return {text(str(k))[:64]:'[REDACTED]' if SENSITIVE.search(str(k)) else walk(v,depth+1) for k,v in list(item.items())[:25]}
        if isinstance(item,list):return [walk(v,depth+1) for v in item[:25]]
        if isinstance(item,str):return text(item)
        return item if item is None or type(item) in (int,float,bool) else '[UNSUPPORTED]'
    result=walk(value)
    if len(json.dumps(result,ensure_ascii=False).encode())>LIMIT:return {'truncated':True,'reason':'BODY_PREVIEW_LIMIT'}
    return result


def begin(ctx):
    ctx.log_policy=get_settings().logging.model_dump()
    ctx.request_preview=redact(ctx.payload,ctx.log_policy) if ctx.log_policy['save_request_body'] else None
    ctx.response_preview=None;ctx.preview_bytes=0


def response(ctx,value,stream=False):
    policy=getattr(ctx,'log_policy',{})
    if not policy.get('save_response_body') or not get_settings().logging.save_response_body:return
    value=redact(value,policy)
    if not stream:ctx.response_preview=value;return
    if ctx.response_preview is None:ctx.response_preview={'stream':True,'events':[],'truncated':False}
    size=len(json.dumps(value,ensure_ascii=False).encode())+2  # JSON event separators count toward the byte limit
    if ctx.preview_bytes+size>LIMIT-256:
        ctx.response_preview['truncated']=True;return
    if not ctx.response_preview['truncated']:
        ctx.response_preview['events'].append(value);ctx.preview_bytes+=size
