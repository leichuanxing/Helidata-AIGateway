"""Gateway access policy. Never trust forwarding headers from arbitrary peers."""
from datetime import datetime, timezone
from functools import lru_cache
from ipaddress import ip_address, ip_network
from hashlib import sha256
from sqlalchemy import select
from app.schemas.gateway_security import SecurityPolicy
from app.models.user import SystemSetting, AuditLog
from app.core.exceptions import APIError
from app.core.database import session_factory
from app.core.redis import redis_client
from app.core.config import get_settings

policy = SecurityPolicy()

@lru_cache(maxsize=4096)
def network(value): return ip_network(value, strict=False)

def address(value):
    parsed = ip_address(value)
    if getattr(parsed, 'ipv4_mapped', None): parsed = parsed.ipv4_mapped
    return parsed

def matches(ip, values):
    parsed = address(ip)
    return any(parsed.version == network(value).version and parsed in network(value) for value in values)

def resolve_ip(peer, forwarded='', real='', trusted=()):
    peer = str(address(peer))
    if not matches(peer, trusted): return peer
    # XFF chain is walked from the socket peer toward the client, stopping at
    # the first untrusted hop. Invalid/oversized chains never gain trust.
    if forwarded:
        parts = forwarded.split(',')
        if len(parts) > 32: return peer
        try: chain = [str(address(part.strip())) for part in parts]
        except ValueError: return peer
        current = peer
        for hop in reversed(chain):
            if not matches(current, trusted): break
            current = hop
        return current
    if real:
        try: return str(address(real.strip()))
        except ValueError: return peer
    return peer

def client(request, selected=None):
    selected = selected or policy
    socket_peer = getattr(request.state, 'security_socket_peer', None) or (request.client.host if request.client else '127.0.0.1')
    # Uvicorn binds loopback inside the image; nginx overwrites this private
    # header on every public route. Direct public peers cannot set it.
    peer = socket_peer
    if socket_peer in ('127.0.0.1','::1'):
        conveyed = request.headers.get('x-gateway-peer-ip')
        if conveyed:
            try: peer = str(address(conveyed))
            except ValueError: pass
    return resolve_ip(peer, request.headers.get('x-forwarded-for',''), request.headers.get('x-real-ip',''), selected.trusted_proxies)

def rejection(ip, category, selected=None):
    selected = selected or policy
    for ban in selected.bans:
        if (ban.expires_at is None or ban.expires_at > datetime.now(timezone.utc)) and matches(ip,[ban.address]):
            return 'IP_BANNED'
    for rule in (selected.global_access, getattr(selected, category + '_access', AccessRuleDefault)):
        if not rule.enabled: continue
        hit = matches(ip, rule.addresses)
        if rule.mode == 'blacklist' and hit: return 'BLACKLIST_HIT'
        if rule.mode == 'whitelist' and not hit: return 'WHITELIST_REJECTED'
    return None

from app.schemas.gateway_security import AccessRule
AccessRuleDefault = AccessRule()

async def load():
    global policy
    async with session_factory() as db:
        row = await db.get(SystemSetting, 'gateway_security')
        if row: policy = SecurityPolicy.model_validate(row.value)

async def event(request, action, key_id=None, actor_id=None):
    # Store only safe metadata, never credentials, prompts or request headers.
    async with session_factory() as db:
        db.add(AuditLog(actor_id=actor_id, action=action, resource_type='gateway_security',
            resource_id=str(key_id) if key_id else None, client_ip=request.client.host if request.client else None,
            result='failure', details={'request_id':getattr(request.state,'request_id',None)}))
        await db.commit()

RATE_SCRIPT = """local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return {n,redis.call('TTL',KEYS[1])}"""
async def rate(request, kind, identifier, limit):
    if not limit: return
    marker = 'security_rate_' + kind
    if getattr(request.state, marker, False): return
    setattr(request.state, marker, True)
    key = 'gateway:security:rpm:' + kind + ':' + sha256(str(identifier).encode()).hexdigest()
    count, ttl = await redis_client.eval(RATE_SCRIPT, 1, key)
    if int(count) > limit:
        await event(request, 'RATE_LIMITED', identifier if kind == 'key' else None)
        error = APIError(429,'GATEWAY_RATE_LIMITED','请求频率超过每分钟上限')
        error.headers = {'Retry-After':str(max(1,int(ttl)))}
        raise error

async def enforce(request):
    request.state.security_socket_peer = request.client.host if request.client else '127.0.0.1'
    ip = client(request)
    request.scope['client'] = (ip, request.client.port if request.client else 0)
    if hasattr(request,'_client'): del request._client
    path = request.scope['path']
    if path in ('/health','/api/health'): return
    category = 'admin' if path.startswith(('/api/admin/','/api/auth/','/admin/','/internal/gateway-security/')) or path == '/login' else 'api' if path.startswith('/v1/') else 'global'
    code = rejection(ip, category)
    if code:
        await event(request, code)
        raise APIError(403, code, '来源 IP 不允许访问网关')
    # Static guard checks access only; the actual backend request consumes RPM.
    if not path.startswith('/internal/gateway-security/'):
        await rate(request, 'ip', ip, policy.ip_rpm)

async def enforce_key(request, key):
    binding = next((item for item in policy.key_bindings if item.key_id == key.id),None)
    if binding and not matches(request.client.host,binding.addresses):
        await event(request,'API_KEY_IP_MISMATCH',key.id)
        raise APIError(403,'API_KEY_IP_MISMATCH','API Key 与来源 IP 不匹配')
    await rate(request,'key',key.id,policy.key_rpm)

def prevent_lockout(request, selected):
    # Re-evaluate proxy changes, not just the previously resolved address.
    ip = client(request, selected)
    if rejection(ip,'admin',selected):
        raise APIError(400,'ADMIN_IP_LOCKOUT','配置将阻止当前管理员访问，请先允许当前管理员 IP：' + ip)
    return ip
