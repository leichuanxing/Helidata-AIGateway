"""Content policy words, local semantic samples and immutable evidence."""
from alembic import op
from sqlalchemy import MetaData,CheckConstraint
from app.models.compliance import AuditWord,AuditSample,AuditVector,CompliancePolicy,ComplianceLog
revision='0014'
down_revision='0013'
branch_labels=None
depends_on=None
def upgrade():
 # Freeze the stage-14 schema: importing current models must not install future
 # columns early during a fresh installation.
 metadata=MetaData()
 excluded={'sensitive_words':('remark',),'review_samples':('remark','status'),
           'compliance_policies':('risk','description'),'compliance_logs':('protocol','status_code')}
 for model in (AuditWord,AuditSample,AuditVector,CompliancePolicy,ComplianceLog):
  table=model.__table__.to_metadata(metadata)
  for name in excluded.get(table.name,()):table._columns.remove(table.c[name])
  for constraint in list(table.constraints):
   if constraint.name in ('ck_review_sample_enabled','ck_audit_sample_status','ck_audit_vector_valid'):table.constraints.remove(constraint)
  if table.name=='review_samples':table.append_constraint(CheckConstraint("vector_status IN ('pending','processing','ready','failed')",name='ck_audit_sample_status'))
  if table.name=='review_vectors':table.append_constraint(CheckConstraint('vector_dims(embedding)=384 AND vector_norm(embedding)>0',name='ck_audit_vector_valid'))
  table.create(op.get_bind())
def downgrade():
 for name in ('compliance_logs','compliance_policies','review_vectors','review_samples','sensitive_words'):op.drop_table(name)
