"""Foundation tables and compatible user expansion."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('roles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.String(30), nullable=False, unique=True),
        sa.Column('name', sa.String(80), nullable=False),
        sa.UniqueConstraint('id','code', name='uq_role_id_code'))
    connection = op.get_bind()
    connection.execute(sa.text("INSERT INTO roles (code,name) VALUES ('super_admin','超级管理员'), ('admin','管理员'), ('user','普通用户')"))
    # Preserve any legacy role value instead of silently changing privileges.
    connection.execute(sa.text("INSERT INTO roles (code,name) SELECT DISTINCT role,role FROM users WHERE role NOT IN (SELECT code FROM roles)"))
    op.create_table('user_groups',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(80), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('status', sa.String(20), nullable=False, server_default='enabled'),
        sa.Column('quota_limit', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('quota_period', sa.String(20), nullable=False, server_default='monthly'),
        sa.Column('max_concurrency', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('key_max_concurrency', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('quota_limit >= 0', name='ck_group_quota'),
        sa.CheckConstraint("quota_period IN ('daily','monthly','permanent')", name='ck_group_period'),
        sa.CheckConstraint('max_concurrency > 0 AND key_max_concurrency > 0', name='ck_group_concurrency'),
        sa.CheckConstraint("status IN ('enabled','disabled')", name='ck_group_status'))
    op.add_column('users', sa.Column('role_id', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('user_group_id', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('name', sa.String(100), nullable=False, server_default=''))
    op.add_column('users', sa.Column('email', sa.String(254), nullable=True))
    op.add_column('users', sa.Column('phone', sa.String(30), nullable=True))
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))
    connection.execute(sa.text('UPDATE users SET role_id=roles.id FROM roles WHERE users.role=roles.code'))
    op.alter_column('users', 'role_id', nullable=False)
    op.create_foreign_key('fk_user_role', 'users', 'roles', ['role_id','role'], ['id','code'], ondelete='RESTRICT')
    op.create_foreign_key('fk_user_group', 'users', 'user_groups', ['user_group_id'], ['id'], ondelete='RESTRICT')
    op.create_index('ix_users_role_id', 'users', ['role_id'])
    op.create_index('ix_users_user_group_id', 'users', ['user_group_id'])
    op.create_table('system_settings',
        sa.Column('key', sa.String(100), primary_key=True),
        sa.Column('value', JSONB(), nullable=False),
        sa.Column('scope', sa.String(30), nullable=False, server_default='basic'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    connection.execute(sa.text("INSERT INTO system_settings (key,value,scope) VALUES ('system_name',to_jsonb(CAST(:name AS text)),'basic'), ('language','\"zh-CN\"'::jsonb,'basic'), ('timezone','\"Asia/Shanghai\"'::jsonb,'basic')"), {'name': '合力数据AI网关'})
    op.create_table('audit_logs',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action', sa.String(80), nullable=False),
        sa.Column('resource_type', sa.String(80), nullable=False),
        sa.Column('resource_id', sa.String(100), nullable=True),
        sa.Column('client_ip', sa.String(45), nullable=True),
        sa.Column('result', sa.String(20), nullable=False),
        sa.Column('details', JSONB(), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_audit_logs_actor_id', 'audit_logs', ['actor_id'])
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])


def downgrade():
    op.drop_table('audit_logs')
    op.drop_table('system_settings')
    op.drop_constraint('fk_user_group', 'users', type_='foreignkey')
    op.drop_constraint('fk_user_role', 'users', type_='foreignkey')
    op.drop_index('ix_users_role_id', table_name='users')
    op.drop_index('ix_users_user_group_id', table_name='users')
    for column in ('last_login_at','phone','email','name','user_group_id','role_id'):
        op.drop_column('users', column)
    op.drop_table('user_groups')
    op.drop_table('roles')
