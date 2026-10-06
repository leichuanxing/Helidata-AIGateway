"""Allow shared embedding services with variable dimensions; preserve old vectors."""
from alembic import op
revision='0026'
down_revision='0025'
branch_labels=None
depends_on=None

def upgrade():
    op.drop_constraint('ck_audit_vector_valid','review_vectors',type_='check')
    op.create_check_constraint('ck_audit_vector_valid','review_vectors','vector_dims(embedding) BETWEEN 1 AND 4096 AND vector_norm(embedding)>0')

def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS(SELECT 1 FROM review_vectors WHERE vector_dims(embedding)<>384) THEN RAISE EXCEPTION 'Non-local vectors require a reviewed rollback'; END IF; END $$")
    op.drop_constraint('ck_audit_vector_valid','review_vectors',type_='check')
    op.create_check_constraint('ck_audit_vector_valid','review_vectors','vector_dims(embedding)=384 AND vector_norm(embedding)>0')
