"""Allow accumulated upstream token totals to exceed a per-request bigint."""
from alembic import op
import sqlalchemy as sa
revision='0010'
down_revision='0009'
branch_labels=None
depends_on=None


def upgrade():
    for table in ('usage_hourly','usage_daily'):
        for key in ('input_tokens','output_tokens','cached_tokens','total_tokens'):
            op.alter_column(table,key+'_sum',type_=sa.Numeric(38,0),existing_type=sa.BigInteger(),existing_nullable=False)


def downgrade():
    for table in ('usage_hourly','usage_daily'):
        for key in ('input_tokens','output_tokens','cached_tokens','total_tokens'):
            op.alter_column(table,key+'_sum',type_=sa.BigInteger(),existing_type=sa.Numeric(38,0),existing_nullable=False)
