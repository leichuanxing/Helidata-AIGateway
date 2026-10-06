"""Provider pool with encrypted upstream credentials and test metadata."""
from alembic import op
import sqlalchemy as sa
revision='0005'
down_revision='0004'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('providers',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('name',sa.String(80),nullable=False,unique=True),
        sa.Column('provider_type',sa.String(40),nullable=False),
        sa.Column('protocol',sa.String(20),nullable=False),
        sa.Column('base_url',sa.String(2048),nullable=False),
        sa.Column('api_key_encrypted',sa.Text()),
        sa.Column('proxy',sa.String(2048)),
        sa.Column('priority',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('max_concurrency',sa.Integer(),nullable=False,server_default='10'),
        sa.Column('status',sa.String(20),nullable=False,server_default='enabled'),
        sa.Column('health_status',sa.String(20),nullable=False,server_default='unknown'),
        sa.Column('failure_count',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('cooldown_until',sa.DateTime(timezone=True)),
        sa.Column('remark',sa.Text(),nullable=False,server_default=''),
        sa.Column('config_version',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('last_test_at',sa.DateTime(timezone=True)),
        sa.Column('last_http_status',sa.Integer()),
        sa.Column('last_latency_ms',sa.Integer()),
        sa.Column('last_error_code',sa.String(40)),
        sa.Column('deleted_at',sa.DateTime(timezone=True)),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('enabled','disabled','deleted')",name='ck_provider_status'),
        sa.CheckConstraint("health_status IN ('unknown','healthy','unhealthy')",name='ck_provider_health'),
        sa.CheckConstraint('max_concurrency > 0 AND failure_count >= 0',name='ck_provider_limits'),
        sa.CheckConstraint("protocol IN ('openai','anthropic','ollama')",name='ck_provider_protocol'))


def downgrade():
    op.drop_table('providers')
