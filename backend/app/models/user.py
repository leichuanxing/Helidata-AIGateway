from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, UniqueConstraint, Index, Integer, String, Text, func, text as sa_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Role(Base):
    __tablename__ = 'roles'
    __table_args__ = (UniqueConstraint('id', 'code', name='uq_role_id_code'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(80))


class UserGroup(Base):
    __tablename__ = 'user_groups'
    __table_args__ = (
        CheckConstraint('quota_limit >= 0', name='ck_group_quota'),
        CheckConstraint("quota_period IN ('daily','monthly','permanent')", name='ck_group_period'),
        CheckConstraint('max_concurrency >= 0 AND key_max_concurrency >= 0', name='ck_group_concurrency'),
        CheckConstraint("model_access IN ('all','selected')",name='ck_group_access'),
        CheckConstraint("NOT is_default OR status='enabled'",name='ck_default_group_enabled'),
        Index('uq_group_default','is_default',unique=True,postgresql_where=sa_text('is_default')),
        CheckConstraint("status IN ('enabled','disabled')", name='ck_group_status'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    model_access: Mapped[str] = mapped_column(String(20),default='selected',server_default='selected')
    is_default: Mapped[bool] = mapped_column(Boolean,default=False,server_default='false')
    description: Mapped[str] = mapped_column(Text, default='', server_default='')
    status: Mapped[str] = mapped_column(String(20), default='enabled', server_default='enabled')
    quota_limit: Mapped[int] = mapped_column(BigInteger, default=0, server_default='0')
    quota_period: Mapped[str] = mapped_column(String(20), default='monthly', server_default='monthly')
    max_concurrency: Mapped[int] = mapped_column(Integer, default=10, server_default='10')
    key_max_concurrency: Mapped[int] = mapped_column(Integer, default=5, server_default='5')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = 'users'
    auth_version: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (ForeignKeyConstraint(['role_id', 'role'], ['roles.id', 'roles.code'], name='fk_user_role', ondelete='RESTRICT'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(30), default='user')
    role_id: Mapped[int] = mapped_column(Integer, index=True)
    user_group_id: Mapped[int | None] = mapped_column(ForeignKey('user_groups.id', ondelete='RESTRICT'), index=True)
    name: Mapped[str] = mapped_column(String(100), default='', server_default='')
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(30))
    remark: Mapped[str] = mapped_column(Text,default='',server_default='')
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default='enabled')
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemSetting(Base):
    __tablename__ = 'system_settings'
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    scope: Mapped[str] = mapped_column(String(30), default='basic', server_default='basic')
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), index=True)
    action: Mapped[str] = mapped_column(String(80))
    resource_type: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[str | None] = mapped_column(String(100))
    client_ip: Mapped[str | None] = mapped_column(String(45))
    result: Mapped[str] = mapped_column(String(20))
    details: Mapped[dict] = mapped_column(JSONB, default=dict, server_default='{}')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class RefreshSession(Base):
    __tablename__ = 'refresh_sessions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    auth_version: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelGroup(Base):
    __tablename__ = 'model_groups'
    __table_args__ = (CheckConstraint("status IN ('enabled','disabled')", name='ck_model_group_status'),
        CheckConstraint("protocol_type IN ('text','multimodal','image','vector')",name='ck_model_group_protocol'))
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    description: Mapped[str] = mapped_column(Text, default='', server_default='')
    status: Mapped[str] = mapped_column(String(20), default='enabled', server_default='enabled')
    protocol_type: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserGroupModelGroup(Base):
    __tablename__ = 'user_group_model_groups'
    user_group_id: Mapped[int] = mapped_column(ForeignKey('user_groups.id', ondelete='CASCADE'), primary_key=True)
    model_group_id: Mapped[int] = mapped_column(ForeignKey('model_groups.id', ondelete='RESTRICT'), primary_key=True)


class ApiKey(Base):
    __tablename__ = 'api_keys'
    __table_args__ = (CheckConstraint("status IN ('enabled','disabled','deleted')", name='ck_api_key_status'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(80))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(16))
    suffix: Mapped[str] = mapped_column(String(4))
    status: Mapped[str] = mapped_column(String(20), default='enabled', server_default='enabled')
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Provider(Base):
    __tablename__ = 'providers'
    __table_args__ = (
        Index('uq_active_provider_name','name',unique=True,postgresql_where=sa_text('deleted_at IS NULL')),
        CheckConstraint("status IN ('enabled','disabled','deleted')",name='ck_provider_status'),
        CheckConstraint("health_status IN ('unknown','healthy','unhealthy')",name='ck_provider_health'),
        CheckConstraint('max_concurrency > 0 AND failure_count >= 0',name='ck_provider_limits'),
        CheckConstraint("protocol IN ('openai','anthropic','ollama')",name='ck_provider_protocol'),
        CheckConstraint("protocol_type IS NULL OR protocol_type IN ('text','multimodal','image','vector')",name='ck_provider_category'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    provider_type: Mapped[str] = mapped_column(String(40))
    protocol: Mapped[str] = mapped_column(String(20))
    base_url: Mapped[str] = mapped_column(String(2048))
    protocol_config: Mapped[dict[str,Any] | None] = mapped_column(JSONB)
    protocol_type: Mapped[str | None] = mapped_column(String(20))
    account_type: Mapped[str] = mapped_column(String(40),default='standard',server_default='standard')
    default_test_model: Mapped[str | None] = mapped_column(String(100))
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    proxy: Mapped[str | None] = mapped_column(String(2048))
    priority: Mapped[int] = mapped_column(Integer,default=0,server_default='0')
    max_concurrency: Mapped[int] = mapped_column(Integer,default=10,server_default='10')
    status: Mapped[str] = mapped_column(String(20),default='enabled',server_default='enabled')
    health_status: Mapped[str] = mapped_column(String(20),default='unknown',server_default='unknown')
    failure_count: Mapped[int] = mapped_column(Integer,default=0,server_default='0')
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remark: Mapped[str] = mapped_column(Text,default='',server_default='')
    config_version: Mapped[int] = mapped_column(Integer,default=0,server_default='0')
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_http_status: Mapped[int | None] = mapped_column(Integer)
    last_latency_ms: Mapped[int | None] = mapped_column(Integer)
    last_error_code: Mapped[str | None] = mapped_column(String(40))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now())


class LogicalModel(Base):
    __tablename__='logical_models'
    __table_args__=(UniqueConstraint('name','model_type',name='uq_logical_model_type'),
        CheckConstraint("model_type IN ('text','reasoning','multimodal','embedding','rerank','image')",name='ck_logical_model_type'))
    name: Mapped[str]=mapped_column(String(100),primary_key=True)
    model_type: Mapped[str]=mapped_column(String(20))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())


class ProviderModelMapping(Base):
    __tablename__='provider_model_mappings'
    __table_args__=(ForeignKeyConstraint(['logical_model','model_type'],['logical_models.name','logical_models.model_type'],ondelete='RESTRICT',name='fk_mapping_logical_model'),
        CheckConstraint("status IN ('enabled','disabled')",name='ck_mapping_status'))
    id: Mapped[int]=mapped_column(primary_key=True)
    provider_id: Mapped[int]=mapped_column(ForeignKey('providers.id',ondelete='RESTRICT'),index=True)
    logical_model: Mapped[str]=mapped_column(String(100),index=True)
    upstream_model: Mapped[str]=mapped_column(String(200))
    model_type: Mapped[str]=mapped_column(String(20))
    status: Mapped[str]=mapped_column(String(20),default='enabled',server_default='enabled')
    deleted_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now())


class ModelGroupModel(Base):
    __tablename__='model_group_models'
    __table_args__=(UniqueConstraint('model_group_id','position',name='uq_model_group_position'),CheckConstraint('position >= 0',name='ck_model_group_position'))
    model_group_id: Mapped[int]=mapped_column(ForeignKey('model_groups.id',ondelete='CASCADE'),primary_key=True)
    logical_model: Mapped[str]=mapped_column(ForeignKey('logical_models.name',ondelete='RESTRICT'),primary_key=True)
    position: Mapped[int]=mapped_column(Integer)

Index('uq_active_provider_logical',ProviderModelMapping.provider_id,ProviderModelMapping.logical_model,unique=True,postgresql_where=ProviderModelMapping.deleted_at.is_(None))

