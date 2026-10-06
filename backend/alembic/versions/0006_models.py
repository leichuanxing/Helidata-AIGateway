"""Canonical logical model catalog, provider mappings and ordered failover groups."""
from alembic import op
import sqlalchemy as sa
revision='0006'
down_revision='0005'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('logical_models',
        sa.Column('name',sa.String(100),primary_key=True),
        sa.Column('model_type',sa.String(20),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.UniqueConstraint('name','model_type',name='uq_logical_model_type'),
        sa.CheckConstraint("model_type IN ('text','reasoning','multimodal','embedding','rerank','image')",name='ck_logical_model_type'))
    op.create_table('provider_model_mappings',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('provider_id',sa.Integer(),sa.ForeignKey('providers.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('logical_model',sa.String(100),nullable=False),
        sa.Column('upstream_model',sa.String(200),nullable=False),
        sa.Column('model_type',sa.String(20),nullable=False),
        sa.Column('status',sa.String(20),nullable=False,server_default='enabled'),
        sa.Column('deleted_at',sa.DateTime(timezone=True)),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['logical_model','model_type'],['logical_models.name','logical_models.model_type'],name='fk_mapping_logical_model',ondelete='RESTRICT'),
        sa.CheckConstraint("status IN ('enabled','disabled')",name='ck_mapping_status'))
    op.create_index('ix_provider_model_mappings_provider_id','provider_model_mappings',['provider_id'])
    op.create_index('ix_provider_model_mappings_logical_model','provider_model_mappings',['logical_model'])
    op.create_index('uq_active_provider_logical','provider_model_mappings',['provider_id','logical_model'],unique=True,postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_table('model_group_models',
        sa.Column('model_group_id',sa.Integer(),sa.ForeignKey('model_groups.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('logical_model',sa.String(100),sa.ForeignKey('logical_models.name',ondelete='RESTRICT'),primary_key=True),
        sa.Column('position',sa.Integer(),nullable=False),
        sa.UniqueConstraint('model_group_id','position',name='uq_model_group_position'),
        sa.CheckConstraint('position >= 0',name='ck_model_group_position'))


def downgrade():
    op.drop_table('model_group_models')
    op.drop_table('provider_model_mappings')
    op.drop_table('logical_models')
