"""Run inside stage5 container; verify upgrade/downgrade on a disposable database."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import uuid

from argon2 import PasswordHasher
import yaml

NAME = 'stage5_test_' + uuid.uuid4().hex[:12]
settings = yaml.safe_load(Path('/data/config/config.yaml').read_text())


def sql(database, statement, success=True):
    result = subprocess.run(['runuser','-u','postgres','--','psql','-d',database,'-At','-v','ON_ERROR_STOP=1','-c',statement], capture_output=True, text=True)
    if success:
        assert result.returncode == 0, 'SQL test failed'
    else:
        assert result.returncode != 0, 'Constraint did not reject invalid input'
    return result.stdout.strip()


def migrate(version, direction='upgrade'):
    result = subprocess.run(['alembic',direction,version],env=environment,capture_output=True,text=True)
    assert result.returncode == 0, 'Migration failed: ' + result.stderr


sql('postgres', f'CREATE DATABASE {NAME} OWNER helidata TEMPLATE template0 ENCODING \'UTF8\'')
try:
    with tempfile.TemporaryDirectory() as directory:
        settings['database']['database'] = NAME
        path = Path(directory) / 'config.yaml'
        path.write_text(yaml.safe_dump(settings))
        path.chmod(0o600)
        environment = dict(os.environ, GATEWAY_CONFIG=str(path))
        migrate('0001')
        password_hash = PasswordHasher().hash(secrets.token_urlsafe(24))
        sql(NAME, f"INSERT INTO users(username,password_hash,role,status,must_change_password) VALUES ('阶段二升级用户','{password_hash}','admin','enabled',true)")
        old = sql(NAME, 'SELECT id,username,password_hash,role,status,must_change_password,created_at FROM users')
        migrate('head')
        assert sql(NAME,'SELECT version_num FROM alembic_version') == '0005'
        assert sql(NAME,'SELECT id,username,password_hash,role,status,must_change_password,created_at FROM users') == old
        assert sql(NAME,'SELECT r.code FROM users u JOIN roles r ON r.id=u.role_id') == 'admin'
        assert json.loads(sql(NAME,"SELECT value FROM system_settings WHERE key='system_name'")) == '合力数据AI网关'
        sql(NAME,"INSERT INTO user_groups(name,quota_limit) VALUES ('非法配额',-1)",success=False)
        sql(NAME,"INSERT INTO user_groups(name,quota_period) VALUES ('非法周期','weekly')",success=False)
        sql(NAME,"INSERT INTO user_groups(name,max_concurrency) VALUES ('非法并发',0)",success=False)
        sql(NAME,"UPDATE users SET role='super_admin'",success=False)
        sql(NAME,"UPDATE users SET user_group_id=999999",success=False)
        sql(NAME,"DELETE FROM roles WHERE code='admin'",success=False)
        assert sql(NAME,"SELECT COUNT(*) FROM pg_tables WHERE schemaname='public' AND tablename IN ('users','roles','user_groups','system_settings','audit_logs')") == '5'
        assert sql(NAME,"SELECT COUNT(*) FROM pg_tables WHERE schemaname='public' AND tablename='providers'") == '1'
        sql(NAME,"INSERT INTO providers(name,provider_type,protocol,base_url,max_concurrency) VALUES ('bad','openai','openai','https://example.com/v1',0)",success=False)
        migrate('0001','downgrade')
        assert sql(NAME,'SELECT id,username,password_hash,role,status,must_change_password,created_at FROM users') == old
        migrate('head')
        assert sql(NAME,'SELECT version_num FROM alembic_version') == '0005'
        print('PASS: 0001 -> 0005 preserves existing user and password; downgrade/re-upgrade on disposable database')
        print('PASS: all five tables, UTF-8 settings, foreign keys and quota/concurrency constraints')
finally:
    sql('postgres', f'DROP DATABASE {NAME}')


