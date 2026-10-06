"""Complete compliance management without changing existing policy scopes."""
from alembic import op
import sqlalchemy as sa
revision='0027'
down_revision='0026'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('sensitive_words',sa.Column('remark',sa.Text(),nullable=False,server_default=''))
    op.add_column('review_samples',sa.Column('remark',sa.Text(),nullable=False,server_default=''))
    op.add_column('review_samples',sa.Column('status',sa.String(20),nullable=False,server_default='enabled'))
    op.create_check_constraint('ck_review_sample_enabled','review_samples',"status IN ('enabled','disabled')")
    op.drop_constraint('ck_audit_sample_status','review_samples',type_='check')
    op.create_check_constraint('ck_audit_sample_status','review_samples',"vector_status IN ('not_built','pending','processing','ready','failed')")
    op.add_column('compliance_policies',sa.Column('risk',sa.String(20),nullable=True))
    op.add_column('compliance_policies',sa.Column('description',sa.Text(),nullable=False,server_default=''))
    op.add_column('compliance_logs',sa.Column('protocol',sa.String(30),nullable=True))
    op.add_column('compliance_logs',sa.Column('status_code',sa.Integer(),nullable=True))

def downgrade():
    op.execute("UPDATE review_samples SET vector_status='failed',vector_error='VECTOR_NOT_BUILT' WHERE vector_status='not_built'")
    op.drop_constraint('ck_audit_sample_status','review_samples',type_='check')
    op.create_check_constraint('ck_audit_sample_status','review_samples',"vector_status IN ('pending','processing','ready','failed')")
    op.drop_constraint('ck_review_sample_enabled','review_samples',type_='check')
    for table,columns in [('sensitive_words',['remark']),('review_samples',['remark','status']),('compliance_policies',['risk','description']),('compliance_logs',['protocol','status_code'])]:
        for column in columns:op.drop_column(table,column)
