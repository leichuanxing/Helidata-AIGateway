from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel,ConfigDict,Field,SecretStr,field_validator
from app.providers.registry import PROVIDER_TYPES
from app.schemas.models import MappingInput


def unique_mapping_names(value):
    if value is not None and len({m.logical_model for m in value})!=len(value):
        raise ValueError('Duplicate request model names')
    return value


def clean_url(value):
    if any(ord(c)<33 for c in value) or '\\' in value:
        raise ValueError('Invalid URL')
    parsed=urlsplit(value)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('URL requires http/https without credentials/query/fragment')
    if parsed.port is not None and not 1<=parsed.port<=65535:
        raise ValueError('Invalid port')
    return value.rstrip('/')


class ProviderCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name: str=Field(min_length=1,max_length=80)
    provider_type: str=Field(max_length=40)
    protocol: Literal['openai','anthropic','ollama']
    base_url: str=Field(min_length=1,max_length=2048)
    api_key: SecretStr | None=Field(default=None,max_length=4096)
    proxy: str | None=Field(default=None,max_length=2048)
    priority: int=Field(default=0,ge=0,le=100000)
    max_concurrency: int=Field(default=10,ge=1,le=100000)
    status: Literal['enabled','disabled']='enabled'
    remark: str=Field(default='',max_length=2000)
    model_mappings: list[MappingInput] | None=Field(default=None,min_length=1,max_length=100)

    @field_validator('model_mappings')
    @classmethod
    def mapping_names(cls,value):return unique_mapping_names(value)

    @field_validator('name')
    @classmethod
    def trim(cls,value):
        if not value.strip(): raise ValueError('Empty name')
        return value.strip()

    @field_validator('provider_type')
    @classmethod
    def known_type(cls,value):
        if value not in PROVIDER_TYPES: raise ValueError('Unknown provider')
        return value

    @field_validator('base_url')
    @classmethod
    def base(cls,value): return clean_url(value)

    @field_validator('proxy')
    @classmethod
    def proxy_url(cls,value):
        if not value: return None
        value=clean_url(value)
        if urlsplit(value).path not in ('','/'):
            raise ValueError('Proxy path not allowed')
        return value

    @field_validator('api_key')
    @classmethod
    def header_safe(cls,value):
        if value is not None:
            raw=value.get_secret_value()
            if not raw or any(ord(c)<33 or ord(c)>126 for c in raw):
                raise ValueError('Key must be nonempty ASCII without whitespace')
        return value


class ProviderEdit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name: str | None=Field(default=None,min_length=1,max_length=80)
    provider_type: str | None=Field(default=None,max_length=40)
    protocol: Literal['openai','anthropic','ollama'] | None=None
    base_url: str | None=Field(default=None,min_length=1,max_length=2048)
    api_key: SecretStr | None=Field(default=None,max_length=4096)
    clear_api_key: bool=False
    proxy: str | None=Field(default=None,max_length=2048)
    priority: int | None=Field(default=None,ge=0,le=100000)
    max_concurrency: int | None=Field(default=None,ge=1,le=100000)
    status: Literal['enabled','disabled'] | None=None
    remark: str | None=Field(default=None,max_length=2000)
    model_mappings: list[MappingInput] | None=Field(default=None,min_length=1,max_length=100)
    expected_config_version: int | None=Field(default=None,ge=0)

    @field_validator('model_mappings')
    @classmethod
    def mapping_names(cls,value):return unique_mapping_names(value)

    @field_validator('name','provider_type','protocol','base_url','priority','max_concurrency','status','remark')
    @classmethod
    def not_null(cls,value):
        if value is None: raise ValueError('Null not allowed')
        return value


class ProviderDiscovery(ProviderCreate):
    name: str=Field(default='discovery',min_length=1,max_length=80)
    provider_id: int | None=Field(default=None,ge=1)


def public_provider(row):
    from app.gateway.provider_health import state
    fields=('id','name','provider_type','protocol','base_url','proxy','priority','max_concurrency','status','health_status','failure_count','cooldown_until','remark','last_test_at','last_http_status','last_latency_ms','last_error_code','created_at','updated_at')
    return {**{f:getattr(row,f) for f in fields},'config_version':row.config_version,'has_api_key':bool(row.api_key_encrypted),'scheduling_state':state(row)}
