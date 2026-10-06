"""Durable route vectorization job ownership and recovery metadata."""
from alembic import op
import sqlalchemy as sa
revision='0013'
down_revision='0012'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('route_samples',sa.Column('requested_by',sa.Integer(),sa.ForeignKey('users.id',ondelete='SET NULL')))
    op.add_column('route_samples',sa.Column('vector_request_id',sa.String(80)))
    op.add_column('route_samples',sa.Column('job_started_at',sa.DateTime(timezone=True)))


def downgrade():
    for name in ('job_started_at','vector_request_id','requested_by'):
        op.drop_column('route_samples',name)
