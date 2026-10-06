"""Public business settings never contain infrastructure credentials."""
import base64, struct
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,field_validator
import regex


class Section(BaseModel):
    model_config=ConfigDict(extra='forbid')


class Basic(Section):
    system_name:str=Field(default='合力数据AI网关',min_length=1,max_length=80)
    logo:str=Field(default='',max_length=350000)
    icon:str=Field(default='',max_length=350000)
    system_url:str=Field(default='',max_length=2048)
    public_api_base_url:str=Field(default='',max_length=2048)
    language:Literal['zh-CN']='zh-CN'
    timezone:str=Field(default='Asia/Shanghai',max_length=80)

    @field_validator('timezone')
    @classmethod
    def zone(cls,value):
        try:ZoneInfo(value)
        except (ZoneInfoNotFoundError,ValueError):raise ValueError('Unknown timezone') from None
        return value

    @field_validator('system_url','public_api_base_url')
    @classmethod
    def url(cls,value):
        if not value:return ''
        parsed=urlsplit(value)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or any(ord(c)<33 for c in value):
            raise ValueError('Invalid public URL')
        if parsed.port is not None and not 1<=parsed.port<=65535:raise ValueError('Invalid port')
        return value.rstrip('/')

    @field_validator('logo','icon')
    @classmethod
    def image(cls,value):
        if not value:return ''
        if not value.startswith('data:image/png;base64,'):raise ValueError('Only PNG images supported')
        try:
            raw=base64.b64decode(value.split(',',1)[1],validate=True)
            if len(raw)>256*1024 or len(raw)<33 or raw[:8]!=b'\x89PNG\r\n\x1a\n' or raw[12:16]!=b'IHDR':raise ValueError()
            width,height=struct.unpack('>II',raw[16:24])
            if not 1<=width<=2048 or not 1<=height<=2048:raise ValueError()
        except Exception:raise ValueError('Invalid PNG image') from None
        return value


class GatewayOptions(Section):
    protocol_conversion:bool=True
    max_concurrency:int=Field(default=500,ge=1,le=100000)
    queue_size:int=Field(default=1000,ge=0,le=100000)
    queue_timeout:int=Field(default=30,ge=1,le=3600)
    nonstream_timeout:int=Field(default=120,ge=1,le=600)
    stream_idle_timeout:int=Field(default=300,ge=1,le=3600)
    max_body_bytes:int=Field(default=10485760,ge=1024,le=10485760)
    sticky_timeout:int=Field(default=1800,ge=1,le=86400)
    health_check_interval:int=Field(default=0,ge=0,le=86400)
    failure_threshold:int=Field(default=2,ge=1,le=100)
    cooldown_seconds:int=Field(default=30,ge=1,le=3600)


class SecurityOptions(Section):
    jwt_expire:int=Field(default=7200,ge=60,le=86400)
    refresh_days:int=Field(default=14,ge=1,le=90)
    login_max_attempts:int=Field(default=5,ge=1,le=50)
    login_lock_seconds:int=Field(default=900,ge=30,le=86400)
    cookie_secure:bool=False


class LogOptions(Section):
    save_request_body:bool=False
    save_response_body:bool=False
    retention_days:int=Field(default=366,ge=1,le=3650)
    redaction_rules:list[str]=Field(default_factory=list,max_length=20)

    @field_validator('redaction_rules')
    @classmethod
    def rules(cls,value):
        for pattern in value:
            if not 1<=len(pattern)<=200:raise ValueError('Invalid redaction pattern length')
            try:regex.compile(pattern)
            except regex.error:raise ValueError('Invalid redaction pattern') from None
        return value


class VectorOptions(Section):
    provider_id:int|None=Field(default=None,gt=0)
    model:str=Field(default='',max_length=100)

class GovernanceOptions(Section):
    smart_route_enabled:bool=True
    compliance_enabled:bool=True
    semantic_threshold:float|None=Field(default=None,ge=0,le=1,allow_inf_nan=False)

class ElasticsearchOptions(Section):
    enabled:bool=False
    url:str=Field(default='',max_length=2048)
    auth_type:Literal['api_key','basic']='api_key'
    username:str=Field(default='',max_length=200)
    secret:str=Field(default='',max_length=4096)
    request_body_kib:int=Field(default=0,ge=0,le=16)
    response_body_kib:int=Field(default=0,ge=0,le=16)
    retention_days:int=Field(default=30,ge=1,le=365)

    @field_validator('url')
    @classmethod
    def endpoint(cls,value):return Basic.url(value)

class SettingsPatch(Section):
    revision:int=Field(ge=0)
    basic:Basic|None=None
    gateway:GatewayOptions|None=None
    security:SecurityOptions|None=None
    logging:LogOptions|None=None
    vector:VectorOptions|None=None
    governance:GovernanceOptions|None=None
    elasticsearch:ElasticsearchOptions|None=None
