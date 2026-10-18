"""Independent virtual routing integrated with existing authorization and leases."""
import asyncio
from contextlib import asynccontextmanager,suppress
from uuid import uuid4
from sqlalchemy import select,or_
from redis.exceptions import RedisError
from app.models.balance import BalancedRoute,BalancedNode
from app.models.user import Provider,ProviderModelMapping,LogicalModel
from app.core.security import now
from app.core.redis import redis_client
from app.core.exceptions import APIError
from app.schemas.balance import matching_type
from app.providers.operations import compatible

def node_key(ident):return f'balance:node:{ident}:concurrency'
def route_key(ident):return f'balance:route:{ident}:concurrency'

async def resolve(db,ctx):
    route=await db.scalar(select(BalancedRoute).where(BalancedRoute.model_name==ctx.logical_model))
    if route is None:
        if getattr(ctx,'balance_route',None):raise APIError(409,'BALANCE_CHANGED','负载均衡路由已变化')
        return None
    if route.status!='enabled':raise APIError(503,'BALANCE_DISABLED','负载均衡路由已禁用')
    previous=getattr(ctx,'balance_route',None)
    if previous and (previous.id!=route.id or previous.config_version!=route.config_version):
        raise APIError(409,'BALANCE_CHANGED','负载均衡路由配置已变化，请重试')
    ctx.balance_route=route
    alias=await db.get(LogicalModel,route.model_name)
    from app.providers.operations import KINDS
    if ctx.operation in KINDS and alias.model_type not in KINDS[ctx.operation]:
        raise APIError(400,'MODEL_TYPE_UNSUPPORTED','统一模型类型不支持此请求')
    rows=(await db.execute(select(BalancedNode,ProviderModelMapping,Provider).join(
        ProviderModelMapping,ProviderModelMapping.id==BalancedNode.mapping_id).join(Provider,Provider.id==ProviderModelMapping.provider_id).where(
        BalancedNode.route_id==route.id,BalancedNode.status=='enabled',
        or_(BalancedNode.cooldown_until.is_(None),BalancedNode.cooldown_until<=now()),
        ProviderModelMapping.status=='enabled',ProviderModelMapping.deleted_at.is_(None),Provider.status=='enabled',Provider.deleted_at.is_(None),
        Provider.health_status!='unhealthy',or_(Provider.cooldown_until.is_(None),Provider.cooldown_until<=now())
    ).order_by(BalancedNode.id))).all()
    ctx.balance_nodes={n.mapping_id:n for n,m,p in rows}
    valid=[(m,p) for n,m,p in rows if matching_type(alias.model_type,m.model_type) and (ctx.operation=='preflight' or compatible(ctx.operation,p))]
    return [(route.model_name,valid)],bool(rows and not valid)

def metadata(ctx,mapping,provider):
    node=ctx.balance_nodes[mapping.id];route=ctx.balance_route
    from app.providers.configuration import NATIVE,select_protocol
    return {'id':provider.id,'mapping_id':mapping.id,'node_id':node.id,'node_key':node_key(node.id),
        'node_limit':1 if node.cooldown_until else node.max_concurrency,'priority':node.priority,'weight':node.weight,
        'strategy':route.strategy,'native':int(select_protocol(provider,ctx.operation)!=NATIVE.get(ctx.operation)),
        'route_key':route_key(route.id),'route_limit':route.max_concurrency,
        'state':f'balance:select:{route.id}:{route.config_version}:{ctx.operation}'}

def safe_retry(error,route):
    return error.detail['code'] in ('UPSTREAM_AUTH_FAILED','UPSTREAM_RATE_LIMITED') or getattr(error,'safe_to_retry',False) or route.retry_uncertain

@asynccontextmanager
async def node_lease(ctx):
    from app.gateway.provider_concurrency import ACQUIRE,RENEW,TTL,RENEW_SECONDS
    node=ctx.balance_node;slot=node_key(node.id);token=uuid4().hex
    admission=ctx.admission
    inherited=await admission.take_node(node.id) if admission else None
    if inherited:token=inherited
    try:
        accepted=await redis_client.eval(RENEW,1,slot,token,TTL) if inherited else await redis_client.eval(ACQUIRE,1,slot,token,1 if node.cooldown_until else node.max_concurrency,TTL)
    except RedisError:raise APIError(503,'SCHEDULER_UNAVAILABLE','节点并发状态不可用') from None
    if not accepted:raise APIError(503,'PROVIDER_BUSY','节点并发已满')
    owner=asyncio.current_task()
    async def renew():
        try:
            while True:
                await asyncio.sleep(RENEW_SECONDS)
                if not await redis_client.eval(RENEW,1,slot,token,TTL):
                    ctx.provider_lease_lost=True;owner.cancel();return
        except RedisError:ctx.provider_lease_lost=True;owner.cancel()
    task=asyncio.create_task(renew())
    try:yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):await task
        try:await redis_client.zrem(slot,token)
        except RedisError:pass

# Optional extension to the existing admission transaction. Ordinary providers keep
# their original ordering. This selects and reserves both node and account capacity.
SELECT_LUA="""
local selected=nil
local balanced=providers[1] and providers[1].strategy
local candidates={};local native=nil
for _,p in ipairs(providers) do
 redis.call('ZREMRANGEBYSCORE',p.key,'-inf',n)
 local available=redis.call('ZCARD',p.key)<p.limit
 if balanced then
  redis.call('ZREMRANGEBYSCORE',p.node_key,'-inf',n)
  p.load=redis.call('ZCARD',p.node_key)
  available=available and p.load<p.node_limit
  if available then
   if not native or p.native<native then native=p.native;candidates={} end
   if p.native==native then table.insert(candidates,p) end
  end
 elseif available and not selected then selected=p end
end
if balanced then
 local p=providers[1]
 redis.call('ZREMRANGEBYSCORE',p.route_key,'-inf',n)
 if redis.call('ZCARD',p.route_key)>=p.route_limit then room=false end
 if room and (not head or head==token) and #candidates>0 then
  if p.strategy=='round_robin' or p.strategy=='weighted_round_robin' then
   local total=0;local best=nil
   for _,c in ipairs(candidates) do
    local w=p.strategy=='round_robin' and 1 or c.weight;total=total+w
    local score=redis.call('HINCRBY',p.state,tostring(c.node_id),w)
    if not best or score>best then best=score;selected=c end
   end
   redis.call('HINCRBY',p.state,tostring(selected.node_id),-total);redis.call('EXPIRE',p.state,3600)
  elseif p.strategy=='random' then
   selected=candidates[(tonumber(ARGV[9] or '0') % #candidates)+1]
  else
   for _,c in ipairs(candidates) do
    if not selected or (p.strategy=='priority' and c.priority<selected.priority)
      or ((p.strategy~='priority' or c.priority==selected.priority) and c.load<selected.load) then selected=c end
   end
  end
 end
end
"""
