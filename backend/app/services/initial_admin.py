"""One-time administrator credentials for fresh offline deployments."""
import json,re,sys
from pathlib import Path
from argon2 import PasswordHasher

INITIAL_ADMIN_FILE=Path('/data/config/initial-admin.json')
def valid_username(value):
    return isinstance(value,str) and re.fullmatch(r'[a-zA-Z0-9_.-]{3,80}',value) is not None

def encode_credentials(value):
    username=value.get('username');password=value.get('password')
    if not valid_username(username):raise ValueError('管理员用户名须为 3 至 80 位字母、数字、下划线、点或短横线')
    if not isinstance(password,str):raise ValueError('管理员密码格式无效')
    classes=sum((any(c.islower() for c in password),any(c.isupper() for c in password),any(c.isdigit() for c in password),any(not c.isalnum() for c in password)))
    if not 12<=len(password)<=128 or classes<3:raise ValueError('密码须为 12 至 128 位，包含大小写字母、数字、符号中的至少三类')
    return {'username':username,'password_hash':PasswordHasher().hash(password)}

def read_credentials(path=INITIAL_ADMIN_FILE):
    try:
        if path.stat().st_size>4096:raise ValueError()
        value=json.loads(path.read_text(encoding='utf-8'))
        if set(value)!={'username','password_hash'} or not valid_username(value['username']):raise ValueError()
        hashed=value['password_hash']
        if not isinstance(hashed,str) or not hashed.startswith('$argon2id$') or len(hashed)>255:raise ValueError()
        PasswordHasher().check_needs_rehash(hashed)
        return value['username'],hashed
    except (OSError,ValueError,TypeError,KeyError) as error:
        raise ValueError('首次管理员配置无效，请重新执行离线部署') from None

if __name__=='__main__':
    try:
        value=json.loads(sys.stdin.read(8192));print(json.dumps(encode_credentials(value)))
    except (ValueError,TypeError,AttributeError):
        print('管理员信息无效：用户名 3 至 80 位；密码 12 至 128 位且包含至少三类字符。',file=sys.stderr)
        raise SystemExit(1)
