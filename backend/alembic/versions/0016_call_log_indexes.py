"""Cover bounded call-log filters without rewriting historical records."""
from alembic import op
revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None
FILTERS = ('provider_id','api_key_id','user_group_id','request_model','logical_model')


def upgrade():
    for field in FILTERS:
        op.create_index('ix_call_logs_'+field+'_created_id','call_logs',[field,'created_at','id'])


def downgrade():
    for field in reversed(FILTERS):
        op.drop_index('ix_call_logs_'+field+'_created_id',table_name='call_logs')
