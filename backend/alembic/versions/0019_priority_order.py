"""Switch to low-number-first priority while preserving legacy relative order."""
from alembic import op
revision='0019'
down_revision='0018'
branch_labels=None
depends_on=None


def upgrade():
    op.execute('UPDATE providers SET priority=100000-priority,config_version=config_version+1')


def downgrade():
    op.execute('UPDATE providers SET priority=100000-priority,config_version=config_version+1')
