from sqlalchemy import select,or_
from app.models.balance import BalancedRoute,BalancedNode
from app.models.user import LogicalModel,ProviderModelMapping,Provider
from app.core.security import now
from app.schemas.balance import matching_type

async def available(db):
    rows=(await db.execute(select(BalancedRoute.model_name,LogicalModel.model_type,ProviderModelMapping.model_type)
        .join(LogicalModel,LogicalModel.name==BalancedRoute.model_name).join(BalancedNode,BalancedNode.route_id==BalancedRoute.id)
        .join(ProviderModelMapping,ProviderModelMapping.id==BalancedNode.mapping_id).join(Provider,Provider.id==ProviderModelMapping.provider_id).where(
        BalancedRoute.status=='enabled',BalancedNode.status=='enabled',ProviderModelMapping.status=='enabled',ProviderModelMapping.deleted_at.is_(None),
        Provider.status=='enabled',Provider.deleted_at.is_(None),Provider.health_status!='unhealthy',
        or_(Provider.cooldown_until.is_(None),Provider.cooldown_until<=now()),or_(BalancedNode.cooldown_until.is_(None),BalancedNode.cooldown_until<=now())))).all()
    return {name:kind for name,kind,actual in rows if matching_type(kind,actual)}
