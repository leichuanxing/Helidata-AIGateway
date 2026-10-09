from dataclasses import dataclass
from fastapi import Depends, Request
from sqlalchemy import select,update,or_
from datetime import timedelta
from app.core.database import get_session
from app.core.exceptions import APIError
from app.core.security import digest,now
from app.models.user import ApiKey,User,UserGroup,ModelGroup,UserGroupModelGroup


@dataclass
class KeyPrincipal:
    key: ApiKey
    user: User
    group: UserGroup
    model_group_ids: list[int]


async def api_key_principal(request: Request,db=Depends(get_session)):
    from app.gateway.authentication import authenticate
    from app.gateway.user_validation import validate as validate_user
    from app.gateway.group_validation import validate as validate_group
    key,user,group=await authenticate(request,db)
    validate_user(user)
    validate_group(group)
    from app.services.model_catalog import allowed_groups
    ids=[item.id for item in await allowed_groups(db,group.id)]
    return KeyPrincipal(key,user,group,list(ids))


def require_model_group(principal,model_group_id):
    if model_group_id not in principal.model_group_ids:
        raise APIError(403,'MODEL_FORBIDDEN','用户组无权访问该模型组')


async def record_key_use(db,principal):
    if principal.key is None:
        await db.commit()  # Web chat still releases the transaction before upstream I/O.
        return
    instant=now()
    # Preserve durable last use with <=1s granularity, without a hot-row write per call.
    await db.execute(update(ApiKey).where(ApiKey.id==principal.key.id,
        or_(ApiKey.last_used_at.is_(None),ApiKey.last_used_at<instant-timedelta(seconds=1)))
        .values(last_used_at=instant))
    await db.commit()
