"""Optional bounded redacted bodies and durable operation settings."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='0017'
down_revision='0016'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('call_logs',sa.Column('request_body',JSONB(),nullable=True))
    op.add_column('call_logs',sa.Column('response_body',JSONB(),nullable=True))
    op.execute("INSERT INTO system_settings(key,value,scope) VALUES ('operations','{}'::jsonb,'operations') ON CONFLICT (key) DO NOTHING")


def downgrade():
    op.drop_column('call_logs','response_body')
    op.drop_column('call_logs','request_body')
    # Generic setting rows survive rollback for a subsequent forward upgrade.
