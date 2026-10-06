from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from app.core.database import get_session
from app.core.dependencies import administrator
from app.core.exceptions import APIError
from app.models.user import AuditLog, User

router = APIRouter(prefix='/api/admin/audit-logs', tags=['管理审计'])


def public(row, username=None):
    return {**{c.name: getattr(row, c.name) for c in AuditLog.__table__.columns},
            'actor_username': row.details.get('actor_username') or username,
            'actor_role': row.details.get('actor_role')}


@router.get('')
async def listing(actor=Depends(administrator), db=Depends(get_session),
    page: int = Query(1, ge=1, le=10000), page_size: int = Query(20, ge=1, le=100),
    actor_id: int | None = Query(None, ge=1), action: str = Query('', max_length=80),
    resource_type: str = Query('', max_length=80), resource_id: str = Query('', max_length=100),
    result: Literal['', 'success', 'failure'] = '',
    start: datetime | None = None, end: datetime | None = None):
    end = end or datetime.now(timezone.utc); start = start or end - timedelta(days=7)
    if start.tzinfo is None or end.tzinfo is None or start >= end or end-start > timedelta(days=31):
        raise APIError(422, 'AUDIT_TIME_RANGE_INVALID', '查询须包含时区且范围大于0、不超过31天')
    predicates = [AuditLog.created_at >= start, AuditLog.created_at < end]
    for name, value in [('actor_id', actor_id), ('action', action), ('resource_type', resource_type),
                        ('resource_id', resource_id), ('result', result)]:
        if value is not None and value != '': predicates.append(getattr(AuditLog, name) == value)
    total = await db.scalar(select(func.count()).select_from(AuditLog).where(*predicates))
    rows = (await db.execute(select(AuditLog, User.username).outerjoin(User, User.id == AuditLog.actor_id)
        .where(*predicates).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page-1)*page_size).limit(page_size))).all()
    return {'data': {'items': [public(row, username) for row, username in rows], 'total': total}}


@router.get('/{ident}')
async def detail(ident: int, actor=Depends(administrator), db=Depends(get_session)):
    row = (await db.execute(select(AuditLog, User.username).outerjoin(User, User.id == AuditLog.actor_id)
                          .where(AuditLog.id == ident))).first()
    if not row: raise APIError(404, 'AUDIT_NOT_FOUND', '审计记录不存在')
    return {'data': public(*row)}
