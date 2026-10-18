"""Expose reranking as an independent provider category without rewriting accounts."""
from alembic import op

revision='0033'
down_revision='0032'
branch_labels=None
depends_on=None

def upgrade():
    op.drop_constraint('ck_provider_category','providers',type_='check')
    op.create_check_constraint('ck_provider_category','providers',"protocol_type IS NULL OR protocol_type IN ('text','multimodal','image','vector','rerank')")

def downgrade():
    # Previous versions already support rerank mappings within vector accounts.
    op.execute("UPDATE providers SET protocol_type='vector' WHERE protocol_type='rerank'")
    op.drop_constraint('ck_provider_category','providers',type_='check')
    op.create_check_constraint('ck_provider_category','providers',"protocol_type IS NULL OR protocol_type IN ('text','multimodal','image','vector')")
