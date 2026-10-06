"""Database-backed hot settings. Existing YAML secrets and assets are untouched."""
from copy import deepcopy
from sqlalchemy import select
from app.models.user import SystemSetting
from app.core.config import get_settings,Gateway,Security,Logging
from app.schemas.settings import Basic,GatewayOptions,SecurityOptions,LogOptions

basic=Basic().model_dump()
revision=0


async def document(db):
    cfg=get_settings()
    defaults={'basic':Basic().model_dump(),
        'gateway':{k:getattr(cfg.gateway,k) for k in GatewayOptions.model_fields},
        'security':{k:getattr(cfg.security,k) for k in SecurityOptions.model_fields},
        'logging':{k:getattr(cfg.logging,k) for k in LogOptions.model_fields},'revision':0}
    rows={r.key:r.value for r in (await db.scalars(select(SystemSetting).where(SystemSetting.key.in_(['operations','system_name','language','timezone'])))).all()}
    for key in ('system_name','language','timezone'):
        if isinstance(rows.get(key),str):defaults['basic'][key]=rows[key]
    stored=rows.get('operations') or {}
    for section in ('basic','gateway','security','logging'):
        defaults[section].update(stored.get(section,{}))
    defaults['revision']=stored.get('revision',0)
    return defaults


def apply(value):
    global basic,revision
    cfg=get_settings()
    parsed=[Basic.model_validate(value['basic']),GatewayOptions.model_validate(value['gateway']),
        SecurityOptions.model_validate(value['security']),LogOptions.model_validate(value['logging'])]
    # Build all sections before publishing; never touch JWT/database/Master Key secrets.
    gateway=Gateway.model_validate({**cfg.gateway.model_dump(),**parsed[1].model_dump()})
    security=Security.model_validate({**cfg.security.model_dump(),**parsed[2].model_dump()})
    logging=Logging.model_validate({**cfg.logging.model_dump(),**parsed[3].model_dump()})
    cfg.gateway=gateway;cfg.security=security;cfg.logging=logging
    basic=parsed[0].model_dump();revision=value['revision']


def public():
    return deepcopy(basic)


async def load():
    from app.core.database import session_factory
    from pydantic import ValidationError
    try:
        async with session_factory() as db:apply(await document(db))
    except ValidationError:raise RuntimeError('Stored operation settings invalid; restore reviewed settings') from None
