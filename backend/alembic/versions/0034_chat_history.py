"""Persist owner-scoped playground transcripts without binary attachments."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision='0034'
down_revision='0033'
branch_labels=None
depends_on=None
def upgrade():
 op.create_table('chat_test_history',sa.Column('id',sa.String(36),primary_key=True),sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),sa.Column('title',sa.String(100),nullable=False),sa.Column('model',sa.String(100),nullable=False),sa.Column('model_type',sa.String(20),nullable=False),sa.Column('transcript',postgresql.JSONB(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
 op.create_index('ix_chat_history_owner_updated','chat_test_history',['user_id','updated_at'])
def downgrade():
 op.drop_table('chat_test_history')
