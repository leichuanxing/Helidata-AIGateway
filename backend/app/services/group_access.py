"""Effective group limits and explicit access modes preserve migrated permissions."""
from sqlalchemy import select
from app.models.user import UserGroup


def concurrency_limits(group,gateway_limit):
    group_limit=min(group.max_concurrency or gateway_limit,gateway_limit)
    return group_limit,min(group.key_max_concurrency or group_limit,group_limit)


async def default_group(db):
    return await db.scalar(select(UserGroup).where(UserGroup.is_default.is_(True),UserGroup.status=='enabled'))


async def resolve_group(db,group_id):
    # Disabled groups fail closed; only unassigned users use the default.
    return await db.get(UserGroup,group_id) if group_id else await default_group(db)
