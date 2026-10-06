"""Durable group quota periods, per-attempt reservations and reported usage."""
from alembic import op
import sqlalchemy as sa
revision='0007'
down_revision='0006'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('quota_buckets',
        sa.Column('group_id',sa.Integer(),sa.ForeignKey('user_groups.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('period',sa.String(12),primary_key=True),sa.Column('period_start',sa.String(10),primary_key=True),
        sa.Column('reported_tokens',sa.BigInteger(),nullable=False,server_default='0'),
        sa.Column('unreported_budget',sa.BigInteger(),nullable=False,server_default='0'),
        sa.Column('reserved_budget',sa.BigInteger(),nullable=False,server_default='0'),
        sa.CheckConstraint('reported_tokens >= 0 AND unreported_budget >= 0 AND reserved_budget >= 0',name='ck_quota_bucket_nonnegative'))
    op.create_table('quota_reservations',
        sa.Column('id',sa.String(80),primary_key=True),
        sa.Column('group_id',sa.Integer(),sa.ForeignKey('user_groups.id',ondelete='CASCADE'),nullable=False,index=True),
        sa.Column('period',sa.String(12),nullable=False),sa.Column('period_start',sa.String(10),nullable=False),
        sa.Column('budget',sa.BigInteger(),nullable=False),sa.Column('reported_tokens',sa.BigInteger()),
        sa.Column('state',sa.String(20),nullable=False,server_default='active'),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False,index=True),
        sa.CheckConstraint('budget >= 0 AND (reported_tokens IS NULL OR reported_tokens >= 0)',name='ck_quota_reservation_nonnegative'))

def downgrade():
    op.drop_table('quota_reservations');op.drop_table('quota_buckets')
