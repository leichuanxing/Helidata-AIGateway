"""User remarks for the product parity iteration."""
from alembic import op
import sqlalchemy as sa
revision='0020'
down_revision='0019'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('users',sa.Column('remark',sa.Text(),nullable=False,server_default=''))


def downgrade():
    op.drop_column('users','remark')
