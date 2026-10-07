"""Keep mapping capability metadata consistent when a logical model changes."""
from alembic import op

revision='0031'
down_revision='0030'
branch_labels=None
depends_on=None


def upgrade():
    op.drop_constraint('fk_mapping_logical_model','provider_model_mappings',type_='foreignkey')
    op.create_foreign_key('fk_mapping_logical_model','provider_model_mappings','logical_models',
        ['logical_model','model_type'],['name','model_type'],ondelete='RESTRICT',onupdate='CASCADE')


def downgrade():
    op.drop_constraint('fk_mapping_logical_model','provider_model_mappings',type_='foreignkey')
    op.create_foreign_key('fk_mapping_logical_model','provider_model_mappings','logical_models',
        ['logical_model','model_type'],['name','model_type'],ondelete='RESTRICT')
