"""Optional vector build, per-sample thresholds and 65536-character samples."""
from alembic import op
import sqlalchemy as sa
revision='0021'
down_revision='0020'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('route_samples',sa.Column('similarity_threshold',sa.Float(),nullable=True))
    op.add_column('route_samples',sa.Column('remark',sa.Text(),nullable=False,server_default=''))
    op.add_column('route_samples',sa.Column('vector_requested',sa.Boolean(),nullable=False,server_default='true'))
    op.create_check_constraint('ck_route_sample_threshold','route_samples','similarity_threshold BETWEEN 0 AND 1')
    op.drop_constraint('ck_route_sample_prompt','route_samples',type_='check')
    op.create_check_constraint('ck_route_sample_prompt','route_samples','length(prompt) BETWEEN 1 AND 65536')


def downgrade():
    # Existing long samples make downgrade fail rather than silently truncate data.
    op.drop_constraint('ck_route_sample_prompt','route_samples',type_='check')
    op.create_check_constraint('ck_route_sample_prompt','route_samples','length(prompt) BETWEEN 1 AND 16000')
    op.drop_constraint('ck_route_sample_threshold','route_samples',type_='check')
    for field in ('vector_requested','remark','similarity_threshold'):op.drop_column('route_samples',field)
