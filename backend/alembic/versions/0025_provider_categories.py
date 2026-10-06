"""Optional account/category metadata; legacy mixed accounts remain compatible."""
from alembic import op
import sqlalchemy as sa
revision='0025'
down_revision='0024'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('providers',sa.Column('protocol_type',sa.String(20),nullable=True))
    op.add_column('providers',sa.Column('account_type',sa.String(40),nullable=False,server_default='standard'))
    op.create_check_constraint('ck_provider_category','providers',"protocol_type IS NULL OR protocol_type IN ('text','image','vector')")

def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM providers WHERE protocol_type IS NOT NULL OR account_type <> 'standard')
      THEN RAISE EXCEPTION 'Clear provider category/account metadata before downgrade'; END IF; END $$""")
    op.drop_constraint('ck_provider_category','providers',type_='check')
    op.drop_column('providers','account_type')
    op.drop_column('providers','protocol_type')
