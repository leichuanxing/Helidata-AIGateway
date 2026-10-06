"""Durable call terminal records with historical snapshots and trace."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='0008'
down_revision='0007'
branch_labels=None
depends_on=None

def upgrade():
    fields=[sa.Column('id',sa.BigInteger(),primary_key=True),sa.Column('request_id',sa.String(80),nullable=False,unique=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column('operation',sa.String(20),nullable=False)]
    for name in ('user_id','user_group_id','api_key_id','provider_id'):fields.append(sa.Column(name,sa.Integer()))
    for name,length in [('username_snapshot',80),('group_name_snapshot',80),('key_name_snapshot',80),('protocol',30),
        ('request_model',100),('logical_model',100),('upstream_model',200),('provider_name_snapshot',80),('error_code',80)]:
        fields.append(sa.Column(name,sa.String(length)))
    fields.extend([sa.Column('client_ip',sa.String(64),nullable=False),sa.Column('stream',sa.Boolean(),nullable=False),
        sa.Column('status',sa.String(30),nullable=False),sa.Column('http_status',sa.Integer(),nullable=False),sa.Column('error_message',sa.Text())])
    for name in ('input_tokens','output_tokens','cached_tokens','total_tokens'):fields.append(sa.Column(name,sa.BigInteger()))
    for name in ('gateway_latency_ms','upstream_latency_ms','ttft_ms','tokens_per_second'):
        fields.append(sa.Column(name,sa.Float(),nullable=name!='gateway_latency_ms'))
    fields.append(sa.Column('trace',postgresql.JSONB(),nullable=False))
    op.create_table('call_logs',*fields)
    for name in ('user_id','user_group_id','api_key_id','provider_id'):op.create_index('ix_call_logs_'+name,'call_logs',[name])
    for name,columns in [('created_id',['created_at','id']),('user_created',['user_id','created_at']),('status_created',['status','created_at'])]:
        op.create_index('ix_call_logs_'+name,'call_logs',columns)

def downgrade():
    op.drop_table('call_logs')
