"""Inherited concurrency and protected default, preserving old selected-only access."""
from alembic import op
import sqlalchemy as sa
revision='0022'
down_revision='0021'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('user_groups',sa.Column('model_access',sa.String(20),nullable=False,server_default='selected'))
    op.add_column('user_groups',sa.Column('is_default',sa.Boolean(),nullable=False,server_default='false'))
    op.create_check_constraint('ck_group_access','user_groups',"model_access IN ('all','selected')")
    op.create_check_constraint('ck_default_group_enabled','user_groups',"NOT is_default OR status='enabled'")
    op.create_index('uq_group_default','user_groups',['is_default'],unique=True,postgresql_where=sa.text('is_default'))
    op.drop_constraint('ck_group_concurrency','user_groups',type_='check')
    op.create_check_constraint('ck_group_concurrency','user_groups','max_concurrency >= 0 AND key_max_concurrency >= 0')
    # Create a separate default rather than change an existing group's meaning.
    # A database with providers keeps unassigned users denied until explicitly configured.
    op.execute("""DO $$ DECLARE candidate text := 'Default'; n integer := 0; BEGIN
    WHILE EXISTS(SELECT 1 FROM user_groups WHERE name=candidate) LOOP
      n:=n+1; candidate:='Default ('||n||')';
    END LOOP;
    INSERT INTO user_groups(name,description,max_concurrency,key_max_concurrency,is_default,model_access)
    VALUES(candidate,'系统默认用户组',0,0,true,
      CASE WHEN EXISTS(SELECT 1 FROM providers) THEN 'selected' ELSE 'all' END);
    END $$""")


def downgrade():
    # Fail closed instead of silently changing unrestricted or inherited configurations.
    op.execute("""DO $$ BEGIN
      IF EXISTS(SELECT 1 FROM user_groups WHERE model_access='all' OR max_concurrency=0 OR key_max_concurrency=0)
      THEN RAISE EXCEPTION 'Configure explicit models and positive limits before downgrade'; END IF;
    END $$""")
    op.drop_index('uq_group_default',table_name='user_groups')
    op.drop_constraint('ck_default_group_enabled','user_groups',type_='check')
    op.drop_constraint('ck_group_access','user_groups',type_='check')
    op.drop_constraint('ck_group_concurrency','user_groups',type_='check')
    op.create_check_constraint('ck_group_concurrency','user_groups','max_concurrency > 0 AND key_max_concurrency > 0')
    op.drop_column('user_groups','is_default')
    op.drop_column('user_groups','model_access')
