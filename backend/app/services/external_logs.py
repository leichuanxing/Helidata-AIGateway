"""Optional bounded Redis outbox for redacted Elasticsearch call records."""
import asyncio,json,logging
from datetime import datetime,timezone,timedelta
import httpx
from app.core.redis import redis_client
from app.core.exceptions import APIError
from app.services import operations_settings as settings
from app.services.provider_crypto import decrypt_secret
QUEUE='logs:elasticsearch:queue'
STATS='logs:elasticsearch:stats'
MAX_BYTES=8*1024*1024
MAX_RECORDS=1000
INDEX='helidata-gateway-calls'
logger=logging.getLogger(__name__)
ENQUEUE='''
local size=tonumber(redis.call('HGET',KEYS[2],'queue_bytes') or '0')
if redis.call('LLEN',KEYS[1])>=tonumber(ARGV[2]) or size+string.len(ARGV[1])>tonumber(ARGV[3]) then
 redis.call('HINCRBY',KEYS[2],'dropped',1);return 0 end
redis.call('RPUSH',KEYS[1],ARGV[1]);redis.call('HINCRBY',KEYS[2],'queue_bytes',string.len(ARGV[1]));return 1
'''
ACK='''
if redis.call('LINDEX',KEYS[1],0)==ARGV[1] then
 redis.call('LPOP',KEYS[1]);redis.call('HINCRBY',KEYS[2],'queue_bytes',-string.len(ARGV[1]));return 1 end
return 0
'''

def headers(cfg):
    secret=decrypt_secret(cfg.get('secret_encrypted'))
    if cfg['auth_type']=='api_key':return {'Authorization':'ApiKey '+secret}
    import base64
    return {'Authorization':'Basic '+base64.b64encode((cfg['username']+':'+secret).encode()).decode()}

async def request(cfg,method,path,**kwargs):
    async with httpx.AsyncClient(timeout=10,follow_redirects=False,trust_env=False) as client:
        response=await client.request(method,cfg['url'].rstrip('/')+path,headers=headers(cfg),**kwargs)
        if response.status_code>=300:raise APIError(502,'ES_CONNECTION_FAILED','Elasticsearch 连接或认证失败')
        if len(response.content)>1024*1024:raise APIError(502,'ES_RESPONSE_INVALID','Elasticsearch 响应过大')
        return response.json()

async def test_connection():
    cfg=dict(settings.elasticsearch)
    if not cfg['url'] or not cfg.get('secret_encrypted'):raise APIError(400,'ES_NOT_CONFIGURED','请先保存 Elasticsearch 地址与认证信息')
    try:
        data=await request(cfg,'GET','/')
        version=str(data.get('version',{}).get('number',''))
        if not version.startswith('9.'):raise APIError(400,'ES_VERSION_UNSUPPORTED','仅支持 Elasticsearch 9.x')
        return {'success':True,'version':version}
    except APIError:raise
    except Exception:raise APIError(502,'ES_CONNECTION_FAILED','Elasticsearch 连接失败，请检查服务地址与证书') from None

def bounded(value,kib):
    if not kib or value is None:return None
    from app.services.body_logs import redact
    value=redact(value,settings.get_settings().logging.model_dump())
    raw=json.dumps(value,ensure_ascii=False)
    limit=kib*1024
    if len(raw.encode())<=limit:return value
    return {'truncated':True,'preview':raw.encode()[:max(0,limit-128)].decode('utf-8',errors='ignore')}

async def enqueue(record,index=INDEX):
    cfg=settings.elasticsearch
    if not cfg['enabled']:return
    # Only authenticated model calls; never export authentication headers or secrets.
    safe={k:v for k,v in record.items() if k not in ('request_body','response_body','trace','client_ip','key_name_snapshot')}
    safe['request_body']=bounded(record.get('request_body'),cfg['request_body_kib'])
    safe['response_body']=bounded(record.get('response_body'),cfg['response_body_kib'])
    safe['created_at']=record['created_at'].isoformat()
    raw=json.dumps({'endpoint':cfg['url'],'index':index,'record':safe},ensure_ascii=False,separators=(',',':'))
    await redis_client.eval(ENQUEUE,2,QUEUE,STATS,raw,MAX_RECORDS,MAX_BYTES)

async def status():
    values=await redis_client.hgetall(STATS)
    return {'enabled':settings.elasticsearch['enabled'],'configured':bool(settings.elasticsearch['url'] and settings.elasticsearch.get('secret_encrypted')),
        'queue_count':await redis_client.llen(QUEUE),'queue_bytes':int(values.get('queue_bytes',0)),
        'dropped':int(values.get('dropped',0)),'last_success':values.get('last_success'),
        'failure_since':values.get('failure_since'),'last_error':values.get('last_error')}

async def step():
    cfg=dict(settings.elasticsearch)
    if not cfg['enabled']:return False
    raw=await redis_client.lindex(QUEUE,0)
    if not raw:return False
    now=datetime.now(timezone.utc).isoformat()
    try:
        envelope=json.loads(raw)
        # A queued body must never be delivered to a replacement server.
        if envelope['endpoint']!=cfg['url']:
            if await redis_client.eval(ACK,2,QUEUE,STATS,raw):await redis_client.hincrby(STATS,'dropped',1)
            return True
        info=await request(cfg,'GET','/')
        if not str(info.get('version',{}).get('number','')).startswith('9.'):raise APIError(400,'ES_VERSION_UNSUPPORTED','仅支持 Elasticsearch 9.x')
        item=envelope['record'];ident=item['request_id'];index=envelope.get('index',INDEX)
        if index not in (INDEX,'helidata-gateway-audits'):raise ValueError('invalid application index')
        # Stable text fields avoid conflicts across string/object/array previews.
        for field in ('request_body','response_body'):
            if item.get(field) is not None:item[field]=json.dumps(item[field],ensure_ascii=False)
        await request(cfg,'PUT',f'/{index}/_doc/{ident}',json=item)
        await redis_client.eval(ACK,2,QUEUE,STATS,raw)
        await redis_client.hset(STATS,mapping={'last_success':now,'failure_since':'','last_error':''})
        return True
    except Exception as error:
        await redis_client.hsetnx(STATS,'failure_since',now)
        # hsetnx won't replace the empty success value.
        if not await redis_client.hget(STATS,'failure_since'):await redis_client.hset(STATS,'failure_since',now)
        code=error.detail['code'] if isinstance(error,APIError) else 'ES_WRITE_FAILED'
        await redis_client.hset(STATS,'last_error',code)
        return False

async def cleanup():
    cfg=dict(settings.elasticsearch)
    if not cfg['enabled']:return
    info=await request(cfg,'GET','/')
    if not str(info.get('version',{}).get('number','')).startswith('9.'):return
    cutoff=(datetime.now(timezone.utc)-timedelta(days=cfg['retention_days'])).isoformat()
    # Dedicated application index only; never touch unrelated Elasticsearch indices.
    for index in (INDEX,'helidata-gateway-audits'):
        try:await request(cfg,'POST',f'/{index}/_delete_by_query?conflicts=proceed',json={'query':{'range':{'created_at':{'lt':cutoff}}}})
        except APIError:continue

async def audit_records():
    from sqlalchemy import select,func
    from app.core.database import session_factory
    from app.models.user import AuditLog
    async with session_factory() as db:
        cursor=await redis_client.hget(STATS,'audit_cursor')
        if cursor is None or not settings.elasticsearch['enabled']:
            latest=await db.scalar(select(func.max(AuditLog.id))) or 0
            await redis_client.hset(STATS,'audit_cursor',latest);return
        rows=(await db.scalars(select(AuditLog).where(AuditLog.id>int(cursor)).order_by(AuditLog.id).limit(100))).all()
    for row in rows:
        await enqueue({'request_id':'audit_'+str(row.id),'created_at':row.created_at,
            'actor_id':row.actor_id,'action':row.action,'resource_type':row.resource_type,
            'resource_id':row.resource_id,'result':row.result},'helidata-gateway-audits')
        await redis_client.hset(STATS,'audit_cursor',row.id)

async def loop():
    last_cleanup=0
    while True:
        try:
            await audit_records()
            work=await step()
            instant=asyncio.get_running_loop().time()
            if instant-last_cleanup>=3600:
                await cleanup();last_cleanup=instant
        except asyncio.CancelledError:raise
        except Exception:
            logger.warning('External log delivery pending');work=False
        await asyncio.sleep(.1 if work else 5)
