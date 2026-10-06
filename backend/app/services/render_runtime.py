"""Render internal listeners from validated startup settings."""
import os
import pwd
from pathlib import Path
from app.core.config import get_settings

settings = get_settings()
nginx = Path('/app/nginx.conf.template').read_text()
nginx = nginx.replace('127.0.0.1:8000', f'127.0.0.1:{settings.server.port}')
Path('/run/nginx.conf').write_text(nginx)
redis = Path('/etc/redis/gateway.conf').read_text()
redis = redis.replace('port 6379', f'port {settings.redis.port}')
Path('/run/redis.conf').write_text(redis)
os.chown('/run/redis.conf', 0, pwd.getpwnam('redis').pw_gid)
os.chmod('/run/redis.conf', 0o640)
