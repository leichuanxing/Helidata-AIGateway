"""Optional TypeSafe decision routing; legacy vector rules remain unchanged."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='0035'
down_revision='0034'
branch_labels=None
depends_on=None

def upgrade():
 for name in ('embedding_model','simple_model_group','complex_model_group'):op.alter_column('route_configs',name,nullable=True)
 for column in (sa.Column('route_mode',sa.String(20),nullable=False,server_default='vector'),sa.Column('decision_provider',sa.String(20),nullable=False,server_default='typesafe'),sa.Column('decision_workspace',sa.String(63),nullable=False,server_default=''),sa.Column('decision_region',sa.String(30),nullable=False,server_default='cn-beijing'),sa.Column('aliyun_key_encrypted',sa.Text()),sa.Column('decision_key_encrypted',sa.Text()),sa.Column('decision_timeout',sa.Integer(),nullable=False,server_default='15'),sa.Column('decision_threshold',sa.Float(),nullable=False,server_default='0.5'),sa.Column('decision_fallback_group',sa.Integer(),sa.ForeignKey('model_groups.id',ondelete='RESTRICT')),sa.Column('decision_targets',JSONB(),nullable=False,server_default='[]')):op.add_column('route_configs',column)
 op.create_check_constraint('ck_route_mode','route_configs',"route_mode IN ('vector','model')")
 op.create_check_constraint('ck_route_decision_timeout','route_configs','decision_timeout BETWEEN 1 AND 60')
 op.create_check_constraint('ck_route_decision_threshold','route_configs','decision_threshold BETWEEN 0 AND 1')
 op.create_check_constraint('ck_route_vector_required','route_configs',"route_mode <> 'vector' OR (embedding_model IS NOT NULL AND simple_model_group IS NOT NULL AND complex_model_group IS NOT NULL)")
 op.create_check_constraint('ck_route_targets','route_configs',"jsonb_typeof(decision_targets)='array' AND jsonb_array_length(decision_targets)<=10")
 for name,size in (('decision_model',100),('decision_target',80),('decision_request_id',80)):op.add_column('route_decisions',sa.Column(name,sa.String(size)))
 op.drop_constraint('ck_route_decision_source','route_decisions',type_='check')
 op.create_check_constraint('ck_route_decision_source','route_decisions',"source IN ('legacy','vector','local_rule','fallback','error','model')")

def downgrade():
 # New mode cannot be represented by the previous version. Refuse lossy downgrade.
 bind=op.get_bind()
 if bind.execute(sa.text("SELECT count(*) FROM route_configs WHERE route_mode='model' OR embedding_model IS NULL OR simple_model_group IS NULL OR complex_model_group IS NULL")).scalar():raise RuntimeError('Remove or convert model decision rules before downgrade')
 bind.execute(sa.text("UPDATE route_decisions SET source='legacy' WHERE source='model'"))
 op.drop_constraint('ck_route_decision_source','route_decisions',type_='check')
 op.create_check_constraint('ck_route_decision_source','route_decisions',"source IN ('legacy','vector','local_rule','fallback','error')")
 for name in ('decision_model','decision_target','decision_request_id'):op.drop_column('route_decisions',name)
 for name in ('ck_route_mode','ck_route_decision_timeout','ck_route_decision_threshold','ck_route_vector_required','ck_route_targets'):op.drop_constraint(name,'route_configs',type_='check')
 for name in ('decision_targets','decision_fallback_group','decision_threshold','decision_timeout','decision_key_encrypted','aliyun_key_encrypted','decision_provider','decision_workspace','decision_region','route_mode'):op.drop_column('route_configs',name)
 for name in ('embedding_model','simple_model_group','complex_model_group'):op.alter_column('route_configs',name,nullable=False)
