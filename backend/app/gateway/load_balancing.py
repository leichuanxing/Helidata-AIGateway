"""Per-group policy; admission owns the atomic selection and lease reservation."""
from sqlalchemy import select
from app.models.user import ModelGroup,ModelGroupModel
from app.services.model_catalog import allowed_groups

async def policy(db,ctx):
    if ctx.route_group_id is not None:
        row=await db.get(ModelGroup,ctx.route_group_id)
    else:
        groups=await allowed_groups(db,ctx.group.id)
        row=await db.scalar(select(ModelGroup).join(ModelGroupModel).where(
            ModelGroup.id.in_([g.id for g in groups]),ModelGroupModel.logical_model==ctx.logical_model
        ).order_by(ModelGroup.id).limit(1))
    return {'group_id':row.id if row else None,
        'strategy':getattr(row,'balancing_strategy','legacy'),
        'max_retries':getattr(row,'max_retries',2),
        'attempt_timeout':getattr(row,'attempt_timeout',120),
        'retry_uncertain':getattr(row,'retry_uncertain',False),
        'weights':getattr(row,'node_weights',{}) or {}}

def retry_allowed(error,policy):
    """Never replay an uncertain generation unless the administrator opts in."""
    code=error.detail['code']
    if code in ('UPSTREAM_AUTH_FAILED','UPSTREAM_RATE_LIMITED'):
        return True
    if getattr(error,'safe_to_retry',False):
        return True
    return bool(policy.get('retry_uncertain',False))

# Embedded in ADMIT: invoked only after global/key/group capacity and FIFO checks.
# Smooth weighted round robin avoids bursts; all counters share the lease transaction.
SELECT_LUA="""
local selected=nil;local pool=nil;local candidates={}
for _,p in ipairs(providers) do
 redis.call('ZREMRANGEBYSCORE',p.key,'-inf',n)
 p.load=redis.call('ZCARD',p.key)
 if p.load<p.limit and (not pool or pool==p.pool) then
  pool=p.pool;table.insert(candidates,p)
 end
end
if room and (not head or head==token) and #candidates>0 then
 local strategy=candidates[1].strategy
 if strategy=='round_robin' or strategy=='weighted_round_robin' then
  local state=candidates[1].state;local total=0;local best=nil
  for _,p in ipairs(candidates) do
   local weight=strategy=='round_robin' and 1 or p.weight
   total=total+weight
   local score=redis.call('HINCRBY',state,tostring(p.id),weight)
   if not best or score>best then selected=p;best=score end
  end
  redis.call('HINCRBY',state,tostring(selected.id),-total);redis.call('EXPIRE',state,3600)
 elseif strategy=='least_concurrency' then
  for _,p in ipairs(candidates) do
   if not selected or p.load<selected.load then selected=p end
  end
 else selected=candidates[1] end
end
"""
