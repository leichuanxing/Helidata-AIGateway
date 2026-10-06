"""Content policy words, local semantic samples and immutable evidence."""
from alembic import op
from app.models.compliance import AuditWord,AuditSample,AuditVector,CompliancePolicy,ComplianceLog
revision='0014'
down_revision='0013'
branch_labels=None
depends_on=None
def upgrade():
 for model in (AuditWord,AuditSample,AuditVector,CompliancePolicy,ComplianceLog):model.__table__.create(op.get_bind())
def downgrade():
 for name in ('compliance_logs','compliance_policies','review_vectors','review_samples','sensitive_words'):op.drop_table(name)
