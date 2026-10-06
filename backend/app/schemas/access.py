from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class GroupInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name: str=Field(min_length=1,max_length=80)
    description: str=Field(default='',max_length=2000)
    status: Literal['enabled','disabled']='enabled'
    quota_limit: int=Field(default=0,ge=0,le=9007199254740991)
    quota_period: Literal['daily','monthly','permanent']='monthly'
    max_concurrency: int=Field(default=0,ge=0,le=100000)
    key_max_concurrency: int=Field(default=0,ge=0,le=100000)
    model_access: Literal['all','selected'] | None=None
    model_group_ids: list[int]=Field(default_factory=list,max_length=1000)

    @field_validator('name')
    @classmethod
    def trim_name(cls,value):
        if not value.strip():
            raise ValueError('名称不能为空')
        return value.strip()


class KeyCreate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name: str=Field(min_length=1,max_length=80)

    @field_validator('name')
    @classmethod
    def trim_name(cls,value):
        if not value.strip():
            raise ValueError('名称不能为空')
        return value.strip()


class KeyEdit(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name: str | None=Field(default=None,min_length=1,max_length=80)
    status: Literal['enabled','disabled'] | None=None

    @field_validator('name','status')
    @classmethod
    def non_null(cls,value):
        if value is None or not value.strip():
            raise ValueError('字段不能为空')
        return value.strip()


def public_key(key):
    return {field:getattr(key,field) for field in ('id','name','prefix','suffix','status','last_used_at','created_at')}
