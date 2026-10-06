"""User group permissions and hash-only API keys."""
from alembic import op
import sqlalchemy as sa
revision='0004'
down_revision='0003'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('model_groups',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('name',sa.String(80),nullable=False,unique=True),
        sa.Column('description',sa.Text(),nullable=False,server_default=''),
        sa.Column('status',sa.String(20),nullable=False,server_default='enabled'),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('enabled','disabled')",name='ck_model_group_status'))
    op.create_table('user_group_model_groups',
        sa.Column('user_group_id',sa.Integer(),sa.ForeignKey('user_groups.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('model_group_id',sa.Integer(),sa.ForeignKey('model_groups.id',ondelete='RESTRICT'),primary_key=True))
    op.create_table('api_keys',
        sa.Column('id',sa.Integer(),primary_key=True),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('name',sa.String(80),nullable=False),
        sa.Column('key_hash',sa.String(64),nullable=False,unique=True),
        sa.Column('prefix',sa.String(16),nullable=False),
        sa.Column('suffix',sa.String(4),nullable=False),
        sa.Column('status',sa.String(20),nullable=False,server_default='enabled'),
        sa.Column('last_used_at',sa.DateTime(timezone=True)),
        sa.Column('deleted_at',sa.DateTime(timezone=True)),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('enabled','disabled','deleted')",name='ck_api_key_status'))
    op.create_index('ix_api_keys_user_id','api_keys',['user_id'])


def downgrade():
    op.drop_table('api_keys')
    op.drop_table('user_group_model_groups')
    op.drop_table('model_groups')
