from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,field_validator
ModelType=Literal['text','reasoning','multimodal','embedding','rerank','image']


def protocol_category(model_type):
    return 'image' if model_type=='image' else 'vector' if model_type in ('embedding','rerank') else 'text'


class MappingInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    logical_model: str=Field(min_length=1,max_length=100,pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$')
    upstream_model: str=Field(min_length=1,max_length=200)
    model_type: ModelType='text'
    status: Literal['enabled','disabled']='enabled'

    @field_validator('upstream_model')
    @classmethod
    def model_name(cls,value):
        if not value.strip() or any(ord(c)<32 or ord(c)==127 for c in value): raise ValueError('Invalid model name')
        return value.strip()


class ModelGroupInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name: str=Field(min_length=1,max_length=80)
    description: str=Field(default='',max_length=2000)
    status: Literal['enabled','disabled']='enabled'
    protocol_type: Literal['text','image','vector'] | None=None
    logical_models: list[str]=Field(default_factory=list,max_length=100)

    @field_validator('name')
    @classmethod
    def name_trim(cls,value):
        if not value.strip(): raise ValueError('Empty name')
        return value.strip()

    @field_validator('logical_models')
    @classmethod
    def unique_models(cls,value):
        if len(value)!=len(set(value)): raise ValueError('Duplicate models')
        import re
        if any(not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,99}',x) for x in value): raise ValueError('Invalid model name')
        return value


def public_mapping(row):
    return {f:getattr(row,f) for f in ('id','provider_id','logical_model','upstream_model','model_type','status','created_at','updated_at')}
