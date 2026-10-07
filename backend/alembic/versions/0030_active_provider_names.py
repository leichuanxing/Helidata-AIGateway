"""Allow deleted account names to be reused without changing historical rows."""
from alembic import op
import sqlalchemy as sa

revision='0030'
down_revision='0029'
branch_labels=None
depends_on=None


def upgrade():
    op.create_index('uq_active_provider_name','providers',['name'],unique=True,postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_constraint('providers_name_key','providers',type_='unique')


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS(SELECT name FROM providers GROUP BY name HAVING count(*)>1) THEN RAISE EXCEPTION 'Resolve reused provider names before downgrade'; END IF; END $$")
    op.create_unique_constraint('providers_name_key','providers',['name'])
    op.drop_index('uq_active_provider_name',table_name='providers')
