from typing import Literal,Annotated
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from app.schemas.models import ModelType

class NodeInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mapping_id:Annotated[int,Field(strict=True,gt=0,le=2147483647)]
    weight:Annotated[int,Field(strict=True,ge=1,le=100)]=1
    priority:Annotated[int,Field(strict=True,ge=0,le=100000)]=0
    max_concurrency:Annotated[int,Field(strict=True,ge=1,le=10000)]=10
    status:Literal['enabled','disabled']='enabled'

class RouteInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=80)
    model_name:str=Field(min_length=1,max_length=100,pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$')
    model_type:ModelType='text'
    strategy:Literal['round_robin','weighted_round_robin','least_concurrency','random','priority']='round_robin'
    status:Literal['enabled','disabled']='enabled'
    description:str=Field(default='',max_length=2000)
    max_concurrency:Annotated[int,Field(strict=True,ge=1,le=10000)]=100
    max_retries:Annotated[int,Field(strict=True,ge=0,le=7)]=2
    timeout_seconds:Annotated[int,Field(strict=True,ge=1,le=3600)]=60
    retry_uncertain:bool=False
    health_interval:Annotated[int,Field(strict=True,ge=10,le=3600)]=30
    cooldown_seconds:Annotated[int,Field(strict=True,ge=1,le=3600)]=30
    failure_threshold:Annotated[int,Field(strict=True,ge=1,le=20)]=3
    expected_config_version:Annotated[int,Field(strict=True,ge=0,le=2147483647)]|None=None
    nodes:list[NodeInput]=Field(min_length=1,max_length=100)

    @field_validator('name')
    @classmethod
    def clean_name(cls,value):
        if not value.strip() or any(ord(c)<32 for c in value):raise ValueError('无效名称')
        return value.strip()

    @model_validator(mode='after')
    def unique_nodes(self):
        if len({node.mapping_id for node in self.nodes})!=len(self.nodes):raise ValueError('不能重复关联同一模型实例')
        return self

def matching_type(wanted,actual):
    return wanted==actual or wanted in ('text','reasoning') and actual in ('text','reasoning')
