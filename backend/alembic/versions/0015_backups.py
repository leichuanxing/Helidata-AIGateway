"""Durable manual backup jobs; existing audit history is retained."""
from alembic import op
import sqlalchemy as sa
revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('backups',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('actor_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('size_bytes', sa.BigInteger()), sa.Column('sha256', sa.String(64)),
        sa.Column('error_code', sa.String(60)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('queued','running','ready','failed')", name='ck_backup_status'))
    # A constant expression enforces one job across BOTH queued and running states.
    op.execute("CREATE UNIQUE INDEX backups_one_active ON backups ((true)) WHERE status IN ('queued','running')")


def downgrade():
    op.drop_table('backups')
