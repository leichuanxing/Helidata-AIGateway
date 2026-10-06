import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from sqlalchemy import URL


class ConfigSection(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Server(ConfigSection):
    host: Literal['0.0.0.0', '127.0.0.1'] = '0.0.0.0'
    port: int = Field(default=8000, ge=1024, le=65535)


class Database(ConfigSection):
    host: Literal['127.0.0.1'] = '127.0.0.1'
    port: Literal[5432] = 5432
    database: str = Field(default='helidata_gateway', pattern=r'^[a-zA-Z_][a-zA-Z0-9_]{0,62}$')
    username: str = Field(default='helidata', pattern=r'^[a-zA-Z_][a-zA-Z0-9_]{0,62}$')
    password: SecretStr = Field(min_length=16)
    pool_size: int = Field(default=10, ge=1, le=100)
    max_overflow: int = Field(default=10, ge=0, le=100)
    connect_timeout: int = Field(default=5, ge=1, le=60)
    pool_timeout: int = Field(default=10, ge=1, le=60)
    pool_recycle: int = Field(default=1800, ge=60, le=86400)
    statement_timeout: int = Field(default=30, ge=1, le=300)

    def url(self):
        return URL.create('postgresql+asyncpg', username=self.username,
                          password=self.password.get_secret_value(), host=self.host,
                          port=self.port, database=self.database)


class RedisConfig(ConfigSection):
    host: Literal['127.0.0.1'] = '127.0.0.1'
    port: int = Field(default=6379, ge=1024, le=65535)
    socket_timeout: int = Field(default=3, ge=1, le=60)


class Gateway(ConfigSection):
    protocol_conversion: bool = True
    max_concurrency: int = Field(default=500, ge=1, le=100000)
    queue_size: int = Field(default=1000, ge=0, le=100000)
    queue_timeout: int = Field(default=30, ge=1, le=3600)
    stream_idle_timeout: int = Field(default=300, ge=1, le=3600)
    http_max_connections: int = Field(default=1024, ge=1, le=10000)
    http_max_keepalive: int = Field(default=64, ge=0, le=10000)
    http_keepalive_expiry: int = Field(default=30, ge=1, le=300)
    http_proxy_pools: int = Field(default=16, ge=1, le=64)
    http_connect_timeout: int = Field(default=10, ge=1, le=60)
    http_write_timeout: int = Field(default=10, ge=1, le=300)
    http_pool_timeout: int = Field(default=10, ge=1, le=60)
    max_body_bytes: int = Field(default=10*1024*1024, ge=1024, le=10*1024*1024)
    preparation_queue_size: int = Field(default=1000, ge=0, le=100000)
    preparation_timeout: int = Field(default=30, ge=1, le=300)
    nonstream_timeout: int = Field(default=120, ge=1, le=600)
    sticky_timeout: int = Field(default=1800, ge=1, le=86400)
    health_check_interval: int = Field(default=0, ge=0, le=86400)
    failure_threshold: int = Field(default=2, ge=1, le=100)
    cooldown_seconds: int = Field(default=30, ge=1, le=3600)


class Security(ConfigSection):
    refresh_days: int = Field(default=14, ge=1, le=90)
    login_max_attempts: int = Field(default=5, ge=1, le=50)
    login_lock_seconds: int = Field(default=900, ge=30, le=86400)
    cookie_secure: bool = False
    jwt_expire: int = Field(default=7200, ge=60, le=86400)
    jwt_secret: SecretStr = Field(min_length=32)


class Logging(ConfigSection):
    level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = 'INFO'
    save_request_body: bool = False
    save_response_body: bool = False
    retention_days: int = Field(default=366, ge=1, le=3650)
    redaction_rules: list[str] = Field(default_factory=list,max_length=20)


class Settings(ConfigSection):
    server: Server = Field(default_factory=Server)
    database: Database
    redis: RedisConfig = Field(default_factory=RedisConfig)
    gateway: Gateway = Field(default_factory=Gateway)
    security: Security
    logging: Logging = Field(default_factory=Logging)


class ConfigurationError(RuntimeError):
    """Configuration error containing field names, never user-supplied values."""


def config_path():
    return Path(os.environ.get('GATEWAY_CONFIG', '/data/config/config.yaml'))


def load_settings(path: Path | None = None):
    try:
        value = yaml.safe_load((path or config_path()).read_text(encoding='utf-8'))
        settings = Settings.model_validate(value)
        if settings.server.port in (settings.database.port, settings.redis.port):
            raise ConfigurationError('Config invalid: server.port conflicts with database/redis')
        if settings.redis.port == settings.database.port:
            raise ConfigurationError('Config invalid: redis.port conflicts with database')
        return settings
    except ValidationError as error:
        fields = ', '.join('.'.join(str(x) for x in item['loc']) for item in error.errors())
        raise ConfigurationError('Config invalid fields: ' + fields) from None
    except (yaml.YAMLError, OSError):
        raise ConfigurationError('Config unreadable or invalid YAML') from None


def ensure_config():
    path = config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        template = Path(os.environ.get('GATEWAY_CONFIG_TEMPLATE', '/app/config/config.yaml.example'))
        value = yaml.safe_load(template.read_text(encoding='utf-8'))
        value['database']['password'] = secrets.token_urlsafe(32)
        value['security']['jwt_secret'] = secrets.token_urlsafe(48)
        # Validate before publishing any generated file.
        Settings.model_validate(value)
        try:
            with path.open('x', encoding='utf-8') as handle:
                os.chmod(path, 0o600)
                yaml.safe_dump(value, handle, allow_unicode=True)
        except FileExistsError:
            pass
    load_settings(path)
    return path


@lru_cache
def get_settings():
    # Service startup snapshot. Restart the container after config edits.
    return load_settings()


if __name__ == '__main__':
    try:
        ensure_config()
        print('Configuration validated.')
    except ConfigurationError as error:
        raise SystemExit(str(error)) from None
