"""One durable, allowlisted terminal record per Request ID; disk outbox on DB failure."""
import asyncio
from app.core.config import get_settings
from datetime import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
from time import monotonic
import anyio
from sqlalchemy.dialects.postgresql import insert
from app.core.database import session_factory
from app.models.call_log import CallLog
from app.gateway.usage import measure,performance

logger=logging.getLogger('app.gateway.calls')
OUTBOX=Path('/data/logs/call-log-outbox')

def attr(obj,name,default=None):return getattr(obj,name,default)

def snapshot(ctx,outcome,code):
    provider,mapping=ctx.provider,ctx.mapping
    elapsed=measure(ctx)['elapsed_ms']
    upstream_ms=ctx.upstream_elapsed_ms
    if ctx.upstream_started is not None:upstream_ms=round((monotonic()-ctx.upstream_started)*1000,2)
    perf=performance(ctx)
    return {'request_id':ctx.request_id,'created_at':ctx.received_at,'operation':ctx.operation,
        'user_id':attr(ctx.user,'id'),'user_group_id':attr(ctx.group,'id'),'api_key_id':attr(ctx.key,'id'),
        'username_snapshot':attr(ctx.user,'username'),'group_name_snapshot':attr(ctx.group,'name'),'key_name_snapshot':attr(ctx.key,'name'),
        'client_ip':ctx.client_ip[:64],'protocol':attr(provider,'protocol','openai' if ctx.operation=='chat' else None),
        'request_model':ctx.original_model or ctx.logical_model,'logical_model':attr(mapping,'logical_model'),
        'upstream_model':attr(mapping,'upstream_model'),'provider_id':attr(provider,'id'),'provider_name_snapshot':attr(provider,'name'),
        'stream':bool(ctx.payload and ctx.payload.get('stream')),'status':outcome,'http_status':ctx.response_status,
        'error_code':code,'error_message':None if outcome=='success' else ('客户端已断开' if outcome=='client_cancelled' else '请求失败，请结合错误码和链路排查'),
        'input_tokens':ctx.usage_snapshot.get('prompt_tokens'),'output_tokens':ctx.usage_snapshot.get('completion_tokens'),
        'cached_tokens':ctx.usage_snapshot.get('cached_tokens'),'total_tokens':ctx.usage_snapshot.get('total_tokens'),
        'gateway_latency_ms':elapsed,'upstream_latency_ms':upstream_ms,'ttft_ms':perf['ttft_ms'],'tokens_per_second':perf['tokens_per_second'],
        'request_body':getattr(ctx,'request_preview',None) if ctx.key and get_settings().logging.save_request_body else None,
        'response_body':getattr(ctx,'response_preview',None) if ctx.key and get_settings().logging.save_response_body else None,
        'trace':{**{k:v for k,v in perf.items() if k not in ('ttft_ms','tokens_per_second')},'stages':list(ctx.stages),'attempts':list(ctx.attempts),'model_groups':list(ctx.authorized_groups),
            'authentication':'authenticated' if ctx.key else 'not_authenticated','stream_chunks':ctx.stream_chunks,
            'queue_wait_ms':round(attr(ctx.admission,'waited',0)*1000,2),
            'parent_request_id':getattr(getattr(ctx.request,'state',None),'parent_request_id',None),
            'smart_routing':ctx.deferred.get('smart_routing','not_reached'),
            'compliance':ctx.deferred.get('compliance','not_reached')}}

async def persist(record):
    async with asyncio.timeout(3):
        async with session_factory.begin() as db:
            inserted=await db.scalar(insert(CallLog).values(**record).on_conflict_do_nothing(index_elements=['request_id']).returning(CallLog.id))
            if inserted is not None:
                from app.services.usage import accumulate
                await accumulate(db,record)

def spool(record):
    OUTBOX.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(OUTBOX,0o700)
    name=hashlib.sha256(record['request_id'].encode()).hexdigest()
    target=OUTBOX/(name+'.json');temporary=OUTBOX/(name+'.tmp')
    raw={**record,'created_at':record['created_at'].isoformat()}
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as file:
        json.dump(raw,file,ensure_ascii=False);file.flush();os.fsync(file.fileno())
    os.replace(temporary,target)
    directory=os.open(OUTBOX,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(directory)
    finally:os.close(directory)

async def write(ctx,outcome,code=None):
    if ctx.terminal_written:return
    ctx.terminal_written=True
    # Keep the established stdout allowlist and terminal semantics for operations tooling.
    record={'operation':ctx.operation,'outcome':outcome,'code':code,'stages':ctx.stages,
        'stream_chunks':ctx.stream_chunks,'attempts':[{'provider_id':a.get('provider_id'),'code':a.get('code')} for a in ctx.attempts],**measure(ctx)}
    logger.info('%s',json.dumps(record,ensure_ascii=False),extra={'request_id':ctx.request_id})
    durable=snapshot(ctx,outcome,code)
    with anyio.CancelScope(shield=True):
        if ctx.key:
            try:
                from app.services.external_logs import enqueue
                async with asyncio.timeout(.5):
                    await enqueue({**durable,'request_body':getattr(ctx,'request_preview',None),'response_body':getattr(ctx,'response_preview',None)})
            except Exception:logger.warning('External log enqueue unavailable',extra={'request_id':ctx.request_id})
        try:await persist(durable)
        except Exception:
            try:await asyncio.to_thread(spool,durable)
            except Exception:logger.error('Call log persistence and outbox failed',extra={'request_id':ctx.request_id})
            else:logger.warning('Call log deferred to durable outbox',extra={'request_id':ctx.request_id})

async def replay_once():
    files=await asyncio.to_thread(lambda:list(__import__('itertools').islice(OUTBOX.glob('*.json'),100)))
    for file in files:
        try:
            record=json.loads(await asyncio.to_thread(file.read_text,encoding='utf-8'))
            record['created_at']=datetime.fromisoformat(record['created_at'])
            await persist(record)
            await asyncio.to_thread(file.unlink,missing_ok=True)
        except Exception:
            logger.warning('Call log outbox replay pending')
            return

async def replay_loop():
    while True:
        try:await replay_once()
        except Exception:logger.warning('Call log outbox scan pending')
        await asyncio.sleep(5)
