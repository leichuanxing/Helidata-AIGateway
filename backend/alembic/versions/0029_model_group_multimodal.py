"""Allow explicit multimodal model groups without rewriting existing groups."""
from alembic import op

revision='0029'
down_revision='0028'
branch_labels=None
depends_on=None


def upgrade():
    op.drop_constraint('ck_model_group_protocol','model_groups',type_='check')
    op.create_check_constraint('ck_model_group_protocol','model_groups',"protocol_type IN ('text','multimodal','image','vector')")


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM model_groups WHERE protocol_type='multimodal') THEN RAISE EXCEPTION 'Change multimodal model groups before downgrade'; END IF; END $$")
    op.drop_constraint('ck_model_group_protocol','model_groups',type_='check')
    op.create_check_constraint('ck_model_group_protocol','model_groups',"protocol_type IN ('text','image','vector')")
