"""Bounded administrator inputs for the Stage16 management layer."""
import csv
import io
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, SecretStr
from app.core.exceptions import APIError

MODEL_PATTERN = r'^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$'


def decision_url(value):
    if not value:return value
    from app.schemas.provider import clean_url
    from urllib.parse import urlsplit
    value=clean_url(value.strip())
    if urlsplit(value).scheme!='https':raise ValueError('决策服务地址必须使用HTTPS')
    return value


class DecisionTarget(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=80)
    model_group_id:int=Field(gt=0,strict=True)
    description:str=Field(min_length=1,max_length=1000)
    exclusion:str=Field(default='',max_length=1000)

    @field_validator('name','description','exclusion')
    @classmethod
    def clean(cls,value):
        value=value.strip()
        if any(ord(c)<32 and c not in '\n\t' for c in value):raise ValueError('不支持的控制字符')
        return value

class RouteConfigInput(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    virtual_model: str = Field(min_length=1, max_length=100, pattern=MODEL_PATTERN)
    embedding_model: str | None = Field(default=None,min_length=1, max_length=100, pattern=MODEL_PATTERN)
    simple_model_group: int | None = Field(default=None,gt=0, strict=True)
    complex_model_group: int | None = Field(default=None,gt=0, strict=True)
    top_k: int = Field(default=5, ge=1, le=50, strict=True)
    similarity_threshold: float = Field(default=.75, ge=0, le=1, strict=True)
    confidence_gap: float = Field(default=.1, ge=0, le=1, strict=True)
    fallback: Literal['error', 'simple', 'complex'] = 'error'
    status: Literal['enabled', 'disabled'] = 'disabled'
    route_mode:Literal['vector','model']='vector'
    decision_provider:Literal['typesafe','aliyun']='typesafe'
    decision_service_url:str=Field(default='',max_length=2048)
    _service_url=field_validator('decision_service_url')(decision_url)
    decision_workspace:str=Field(default='',max_length=63,pattern=r'^([a-zA-Z0-9][a-zA-Z0-9-]{0,62})?$')
    decision_region:Literal['cn-beijing','ap-southeast-1']='cn-beijing'
    decision_api_key:SecretStr | None=Field(default=None,min_length=1,max_length=4096)
    clear_decision_key:bool=Field(default=False,strict=True)
    decision_timeout:int=Field(default=15,ge=1,le=60,strict=True)
    decision_threshold:float=Field(default=.5,ge=0,le=1)
    decision_fallback_group:int | None=Field(default=None,gt=0,strict=True)
    decision_targets:list[DecisionTarget]=Field(default_factory=list,max_length=10)
    expected_updated_at: datetime | None = None

    @field_validator('expected_updated_at')
    @classmethod
    def aware_version(cls,value):
        if value is not None and value.tzinfo is None:
            raise ValueError('规则版本时间必须包含时区')
        return value

    @model_validator(mode='after')
    def distinct_targets(self):
        if self.route_mode=='vector' and not all((self.embedding_model,self.simple_model_group,self.complex_model_group)):raise ValueError('本地/向量模式需要向量模型及两个目标组')
        if self.simple_model_group is not None and self.simple_model_group == self.complex_model_group:
            raise ValueError('Simple and complex groups must differ')
        if self.virtual_model == self.embedding_model:
            raise ValueError('Virtual and embedding models must differ')
        if self.route_mode=='model' and (not self.decision_fallback_group or len(self.decision_targets)<2):raise ValueError('模型决策需要兜底组及2至10个路由目标')
        if self.route_mode=='model' and self.decision_provider=='aliyun' and not (self.decision_service_url or self.decision_workspace):raise ValueError('阿里云决策模型需要完整服务地址')
        if any(not t.name or not t.description for t in self.decision_targets):raise ValueError('目标名称与适用说明不能为空')
        if len({t.name for t in self.decision_targets})!=len(self.decision_targets):raise ValueError('路由目标名称不能重复')
        if len({t.model_group_id for t in self.decision_targets})!=len(self.decision_targets):raise ValueError('路由目标模型组不能重复')
        if self.decision_api_key and (self.clear_decision_key or any(ord(c)<33 or ord(c)>126 for c in self.decision_api_key.get_secret_value())):raise ValueError('决策密钥格式无效或与清除选项冲突')
        return self


class RouteSampleInput(BaseModel):
    model_config = ConfigDict(extra='forbid',allow_inf_nan=False)
    prompt: str = Field(min_length=1, max_length=65536)
    classification: Literal['simple', 'complex']
    similarity_threshold: float | None=Field(default=None,ge=0,le=1)
    remark: str=Field(default='',max_length=2000)
    build_vector: bool=True
    expected_revision: int | None=Field(default=None,ge=1,strict=True)

    @field_validator('prompt')
    @classmethod
    def prompt_text(cls, value):
        from app.services.route_vectors import normalize_prompt
        value = normalize_prompt(value)
        if not value or len(value.encode('utf-8')) > 262144:
            raise ValueError('Prompt is empty or exceeds the byte limit')
        if any(ord(char) < 32 and char not in '\n\r\t' for char in value) or '\x7f' in value:
            raise ValueError('Prompt contains unsupported control characters')
        return value


class RouteSamplesInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    config_id: int = Field(gt=0, strict=True)
    samples: list[RouteSampleInput] = Field(min_length=1, max_length=500)


def parse_samples_csv(raw):
    """UTF-8/BOM CSV with an explicit two-column template; no partial import.

The management API must parse before starting its transaction and return row
numbers only. Raw prompt contents must never be included in errors or audits.
"""
    if not isinstance(raw, bytes) or len(raw) > 2 * 1024 * 1024:
        raise APIError(400, 'ROUTE_CSV_INVALID', 'CSV必须为UTF-8文件，且不超过2MB')
    try:
        content = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise APIError(400, 'ROUTE_CSV_INVALID', 'CSV必须为UTF-8编码') from None
    try:
        reader = csv.DictReader(io.StringIO(content), strict=True)
        required={'prompt','classification'};allowed=required|{'similarity_threshold','remark'}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames) or not set(reader.fieldnames).issubset(allowed) or len(set(reader.fieldnames))!=len(reader.fieldnames):
            raise APIError(400, 'ROUTE_CSV_INVALID', 'CSV需包含prompt,classification，可选similarity_threshold,remark')
        samples = []
        prompts = set()
        for row in reader:
            if len(samples) >= 500:
                raise APIError(400, 'ROUTE_CSV_INVALID', '一次最多导入500条样本')
            if None in row or any(value is None for value in row.values()):
                raise APIError(400, 'ROUTE_CSV_INVALID', f'CSV第{reader.line_num}行列数不正确')
            try:
                if row.get('similarity_threshold')=='':row['similarity_threshold']=None
                sample = RouteSampleInput.model_validate(row)
            except ValueError:
                raise APIError(400, 'ROUTE_CSV_INVALID', f'CSV第{reader.line_num}行内容或类别无效') from None
            if sample.prompt in prompts:
                raise APIError(409, 'ROUTE_SAMPLE_DUPLICATE', f'CSV第{reader.line_num}行样本重复')
            prompts.add(sample.prompt)
            samples.append(sample)
        if not samples:
            raise APIError(400, 'ROUTE_CSV_INVALID', 'CSV没有样本')
        return samples
    except csv.Error:
        raise APIError(400, 'ROUTE_CSV_INVALID', 'CSV格式无效，请检查引号和字段长度') from None


class DecisionModelTestInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    config_id:int | None=Field(default=None,gt=0,strict=True)
    decision_provider:Literal['typesafe','aliyun']='typesafe'
    decision_service_url:str=Field(default='',max_length=2048)
    _service_url=field_validator('decision_service_url')(decision_url)
    decision_workspace:str=Field(default='',max_length=63,pattern=r'^([a-zA-Z0-9][a-zA-Z0-9-]{0,62})?$')
    decision_region:Literal['cn-beijing','ap-southeast-1']='cn-beijing'
    decision_api_key:SecretStr | None=Field(default=None,min_length=1,max_length=4096)
    decision_timeout:int=Field(default=15,ge=1,le=60,strict=True)
    expected_updated_at:datetime | None=None
    consent:Literal[True]

    @model_validator(mode='after')
    def valid_connection(self):
        if self.decision_provider=='aliyun' and not (self.decision_service_url or self.decision_workspace):raise ValueError('请填写完整服务地址')
        if self.expected_updated_at is not None and self.expected_updated_at.tzinfo is None:raise ValueError('版本时间必须包含时区')
        if self.decision_api_key and any(ord(c)<33 or ord(c)>126 for c in self.decision_api_key.get_secret_value()):raise ValueError('密钥格式无效')
        return self
