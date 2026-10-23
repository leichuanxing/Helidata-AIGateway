"""Editable decision service URL; retain legacy region/workspace for compatibility."""
from alembic import op
import sqlalchemy as sa
revision='0036'
down_revision='0035'
branch_labels=None
depends_on=None

def upgrade():
 op.add_column('route_configs',sa.Column('decision_service_url',sa.String(2048),nullable=False,server_default=''))
 op.execute("UPDATE route_configs SET decision_service_url='https://' || lower(decision_workspace) || '.' || decision_region || '.maas.aliyuncs.com/compatible-mode/v1/systemone' WHERE decision_workspace ~ '^[A-Za-z0-9][A-Za-z0-9-]{0,62}$' AND decision_region IN ('cn-beijing','ap-southeast-1')")

def downgrade():
 bind=op.get_bind()
 if bind.execute(sa.text("SELECT count(*) FROM route_configs WHERE decision_service_url<>'' AND decision_service_url<>('https://' || lower(decision_workspace) || '.' || decision_region || '.maas.aliyuncs.com/compatible-mode/v1/systemone')")).scalar():raise RuntimeError('Custom decision URLs cannot be represented by the previous version')
 op.drop_column('route_configs','decision_service_url')
