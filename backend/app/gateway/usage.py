from time import monotonic


def measure(ctx):
    return {'elapsed_ms': round((monotonic() - ctx.started) * 1000, 2)}


def effective(chunk):
    for choice in chunk.get('choices',[]):
        delta=choice.get('delta',{})
        if delta.get('content') or delta.get('reasoning_content') or delta.get('refusal'):return True
        for tool in delta.get('tool_calls') or []:
            if isinstance(tool,dict):
                function=tool.get('function') or {}
                if isinstance(function,dict) and (function.get('arguments') or function.get('name')):return True
        function=delta.get('function_call') or {}
        if isinstance(function,dict) and (function.get('arguments') or function.get('name')):return True
    return False


def performance(ctx):
    stream=bool(ctx.payload and ctx.payload.get('stream'))
    first=ctx.first_effective
    start=first if stream else ctx.generation_start
    duration=(ctx.generation_end-start)*1000 if start is not None and ctx.generation_end is not None else None
    output=ctx.usage_snapshot.get('completion_tokens')
    return {'ttft_ms':round((first-ctx.started)*1000,2) if stream and first is not None else None,
        'generation_time_ms':round(duration,3) if duration is not None else None,
        'tokens_per_second':round(output/(duration/1000),3) if output is not None and duration and duration>0 else None,
        'timing_mode':'stream_first_content' if stream else 'nonstream_full_response',
        'usage_status':'available' if all(k in ctx.usage_snapshot for k in ('prompt_tokens','completion_tokens','total_tokens')) else 'usage_unavailable'}
