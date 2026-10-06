"""Add explicit multimodal account category; preserve existing mappings."""
from alembic import op
revision='0028'
down_revision='0027'
branch_labels=None
depends_on=None

def upgrade():
    op.drop_constraint('ck_provider_category','providers',type_='check')
    op.create_check_constraint('ck_provider_category','providers',"protocol_type IS NULL OR protocol_type IN ('text','multimodal','image','vector')")

def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM providers WHERE protocol_type='multimodal') THEN RAISE EXCEPTION 'Change multimodal account categories before downgrade'; END IF; END $$")
    op.drop_constraint('ck_provider_category','providers',type_='check')
    op.create_check_constraint('ck_provider_category','providers',"protocol_type IS NULL OR protocol_type IN ('text','image','vector')")
