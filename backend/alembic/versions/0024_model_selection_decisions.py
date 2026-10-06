"""Model selection provenance and preview history; existing requests remain intact."""
from alembic import op
import sqlalchemy as sa
revision='0024'
down_revision='0023'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('route_decisions',sa.Column('source',sa.String(20),nullable=False,server_default='legacy'))
    op.add_column('route_decisions',sa.Column('request_kind',sa.String(20),nullable=False,server_default='real'))
    op.add_column('route_decisions',sa.Column('normalized_text',sa.Text(),nullable=True))
    op.add_column('route_decisions',sa.Column('confidence',sa.Float(),nullable=True))
    op.add_column('route_decisions',sa.Column('selected_model',sa.String(100),nullable=True))
    op.execute("UPDATE route_decisions SET source=CASE WHEN status='classified' AND embedding_request_id IS NOT NULL THEN 'vector' WHEN status='fallback' THEN 'fallback' WHEN status='failed' THEN 'error' ELSE 'legacy' END")
    op.create_check_constraint('ck_route_decision_source','route_decisions',"source IN ('legacy','vector','local_rule','fallback','error')")
    op.create_check_constraint('ck_route_decision_kind','route_decisions',"request_kind IN ('real','preview')")
    op.create_check_constraint('ck_route_decision_confidence','route_decisions','confidence IS NULL OR (confidence >= 0 AND confidence <= 2)')
    op.create_check_constraint('ck_route_decision_text','route_decisions','normalized_text IS NULL OR length(normalized_text) <= 16000')


def downgrade():
    for name in ('text','confidence','kind','source'):op.drop_constraint('ck_route_decision_'+name,'route_decisions',type_='check')
    for name in ('selected_model','confidence','normalized_text','request_kind','source'):op.drop_column('route_decisions',name)
