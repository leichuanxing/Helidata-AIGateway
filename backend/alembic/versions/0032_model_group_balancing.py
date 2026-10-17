"""Add compatible, opt-in per-group balancing configuration."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision='0032'
down_revision='0031'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('model_groups',sa.Column('balancing_strategy',sa.String(30),nullable=False,server_default='legacy'))
    op.add_column('model_groups',sa.Column('max_retries',sa.Integer(),nullable=False,server_default='2'))
    op.add_column('model_groups',sa.Column('attempt_timeout',sa.Integer(),nullable=False,server_default='120'))
    op.add_column('model_groups',sa.Column('retry_uncertain',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.add_column('model_groups',sa.Column('node_weights',JSONB(),nullable=False,server_default='{}'))
    op.create_check_constraint('ck_model_group_balancing','model_groups',"balancing_strategy IN ('legacy','round_robin','weighted_round_robin','least_concurrency') AND max_retries BETWEEN 0 AND 7 AND attempt_timeout BETWEEN 1 AND 3600")

def downgrade():
    op.drop_constraint('ck_model_group_balancing','model_groups',type_='check')
    for name in ('node_weights','retry_uncertain','attempt_timeout','max_retries','balancing_strategy'):
        op.drop_column('model_groups',name)
