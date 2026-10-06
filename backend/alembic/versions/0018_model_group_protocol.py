"""Typed groups; preserve existing mixed groups without silently dropping members."""
from alembic import op
import sqlalchemy as sa
revision='0018'
down_revision='0017'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('model_groups',sa.Column('protocol_type',sa.String(20),nullable=True))
    op.create_check_constraint('ck_model_group_protocol','model_groups',"protocol_type IN ('text','image','vector')")
    op.execute("""UPDATE model_groups AS g SET protocol_type=c.category
        FROM (SELECT m.model_group_id,min(CASE WHEN l.model_type='image' THEN 'image'
        WHEN l.model_type IN ('embedding','rerank') THEN 'vector' ELSE 'text' END) AS category
        FROM model_group_models m JOIN logical_models l ON l.name=m.logical_model
        GROUP BY m.model_group_id HAVING count(DISTINCT CASE WHEN l.model_type='image' THEN 'image'
        WHEN l.model_type IN ('embedding','rerank') THEN 'vector' ELSE 'text' END)=1) c
        WHERE g.id=c.model_group_id""")


def downgrade():
    op.drop_constraint('ck_model_group_protocol','model_groups',type_='check')
    op.drop_column('model_groups','protocol_type')
