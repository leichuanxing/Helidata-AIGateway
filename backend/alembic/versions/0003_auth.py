"""Persistent rotating refresh sessions and auth epoch."""
from alembic import op
import sqlalchemy as sa

revision='0003'
down_revision='0002'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('users',sa.Column('auth_version',sa.Integer(),nullable=False,server_default='0'))
    op.add_column('users',sa.Column('deleted_at',sa.DateTime(timezone=True),nullable=True))
    op.create_table('refresh_sessions',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('token_hash',sa.String(64),nullable=False,unique=True),
        sa.Column('csrf_hash',sa.String(64),nullable=False),
        sa.Column('auth_version',sa.Integer(),nullable=False),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('revoked',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    op.create_index('ix_refresh_sessions_user_id','refresh_sessions',['user_id'])
    op.create_index('ix_refresh_sessions_expires_at','refresh_sessions',['expires_at'])


def downgrade():
    op.drop_table('refresh_sessions')
    op.drop_column('users','deleted_at')
    op.drop_column('users','auth_version')
