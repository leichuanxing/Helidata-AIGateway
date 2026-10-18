"""Create independent load-balanced virtual routes and mapping nodes."""
from alembic import op
import sqlalchemy as sa

revision='0032'
down_revision='0031'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('balanced_routes',
        sa.Column('id',sa.Integer(),primary_key=True),sa.Column('name',sa.String(80),nullable=False,unique=True),
        sa.Column('model_name',sa.String(100),sa.ForeignKey('logical_models.name',ondelete='RESTRICT'),nullable=False,unique=True),
        sa.Column('strategy',sa.String(30),nullable=False,server_default='round_robin'),
        sa.Column('status',sa.String(20),nullable=False,server_default='enabled'),
        sa.Column('description',sa.Text(),nullable=False,server_default=''),
        sa.Column('max_concurrency',sa.Integer(),nullable=False,server_default='100'),
        sa.Column('max_retries',sa.Integer(),nullable=False,server_default='2'),
        sa.Column('timeout_seconds',sa.Integer(),nullable=False,server_default='60'),
        sa.Column('retry_uncertain',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('health_interval',sa.Integer(),nullable=False,server_default='30'),
        sa.Column('cooldown_seconds',sa.Integer(),nullable=False,server_default='30'),
        sa.Column('failure_threshold',sa.Integer(),nullable=False,server_default='3'),
        sa.Column('config_version',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.CheckConstraint("strategy IN ('round_robin','weighted_round_robin','least_concurrency','random','priority')",name='ck_balanced_strategy'),
        sa.CheckConstraint("status IN ('enabled','disabled')",name='ck_balanced_status'),
        sa.CheckConstraint('max_concurrency BETWEEN 1 AND 10000 AND max_retries BETWEEN 0 AND 7 AND timeout_seconds BETWEEN 1 AND 3600 AND health_interval BETWEEN 10 AND 3600 AND cooldown_seconds BETWEEN 1 AND 3600 AND failure_threshold BETWEEN 1 AND 20',name='ck_balanced_limits'))
    op.create_table('balanced_nodes',sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('route_id',sa.Integer(),sa.ForeignKey('balanced_routes.id',ondelete='CASCADE'),nullable=False),
        sa.Column('mapping_id',sa.Integer(),sa.ForeignKey('provider_model_mappings.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('weight',sa.Integer(),nullable=False,server_default='1'),sa.Column('priority',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('max_concurrency',sa.Integer(),nullable=False,server_default='10'),
        sa.Column('status',sa.String(20),nullable=False,server_default='enabled'),sa.Column('health_status',sa.String(20),nullable=False,server_default='unknown'),
        sa.Column('failure_count',sa.Integer(),nullable=False,server_default='0'),sa.Column('cooldown_until',sa.DateTime(timezone=True)),
        sa.Column('next_check_at',sa.DateTime(timezone=True)),sa.Column('last_checked_at',sa.DateTime(timezone=True)),
        sa.Column('last_latency_ms',sa.Integer()),sa.Column('last_error_code',sa.String(80)),
        sa.UniqueConstraint('route_id','mapping_id',name='uq_balanced_node_mapping'),
        sa.CheckConstraint('weight BETWEEN 1 AND 100 AND max_concurrency BETWEEN 1 AND 10000 AND priority BETWEEN 0 AND 100000 AND failure_count>=0',name='ck_balanced_node_limits'),
        sa.CheckConstraint("status IN ('enabled','disabled') AND health_status IN ('unknown','healthy','unhealthy')",name='ck_balanced_node_status'))
    for name in ('route_id','mapping_id','next_check_at'):op.create_index('ix_balanced_nodes_'+name,'balanced_nodes',[name])

def downgrade():
    op.drop_table('balanced_nodes')
    op.drop_table('balanced_routes')
