"""Optional protocol routes preserve existing provider addresses and credentials."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='0023'
down_revision='0022'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('providers',sa.Column('protocol_config',JSONB(),nullable=True))
    op.add_column('providers',sa.Column('default_test_model',sa.String(100),nullable=True))


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM providers WHERE protocol_config IS NOT NULL OR default_test_model IS NOT NULL)
      THEN RAISE EXCEPTION 'Clear multi-protocol and test-model configuration before downgrade'; END IF;
    END $$""")
    op.drop_column('providers','default_test_model')
    op.drop_column('providers','protocol_config')
