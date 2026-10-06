from sqlalchemy import select
from app.models.user import LogicalModel
from app.services.model_catalog import catalog


async def listing(db, ctx):
    groups = await catalog(db, ctx.group.id)
    names = {m['logical_model'] for g in groups for m in g['models'] if m['configured']}
    models = (await db.scalars(select(LogicalModel).where(LogicalModel.name.in_(names))
                              .order_by(LogicalModel.name))).all()
    return {'object': 'list', 'data': [{'id': m.name, 'object': 'model',
        'created': int(m.created_at.timestamp()), 'owned_by': 'helidata'} for m in models]}
