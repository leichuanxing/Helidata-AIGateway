"""Bounded administrator inputs for the Stage16 management layer."""
import csv
import io
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.core.exceptions import APIError

MODEL_PATTERN = r'^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$'


class RouteConfigInput(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    virtual_model: str = Field(min_length=1, max_length=100, pattern=MODEL_PATTERN)
    embedding_model: str = Field(min_length=1, max_length=100, pattern=MODEL_PATTERN)
    simple_model_group: int = Field(gt=0, strict=True)
    complex_model_group: int = Field(gt=0, strict=True)
    top_k: int = Field(default=5, ge=1, le=50, strict=True)
    similarity_threshold: float = Field(default=.75, ge=0, le=1, strict=True)
    confidence_gap: float = Field(default=.1, ge=0, le=1, strict=True)
    fallback: Literal['error', 'simple', 'complex'] = 'error'
    status: Literal['enabled', 'disabled'] = 'disabled'

    @model_validator(mode='after')
    def distinct_targets(self):
        if self.simple_model_group == self.complex_model_group:
            raise ValueError('Simple and complex groups must differ')
        if self.virtual_model == self.embedding_model:
            raise ValueError('Virtual and embedding models must differ')
        return self


class RouteSampleInput(BaseModel):
    model_config = ConfigDict(extra='forbid',allow_inf_nan=False)
    prompt: str = Field(min_length=1, max_length=65536)
    classification: Literal['simple', 'complex']
    similarity_threshold: float | None=Field(default=None,ge=0,le=1)
    remark: str=Field(default='',max_length=2000)
    build_vector: bool=True

    @field_validator('prompt')
    @classmethod
    def prompt_text(cls, value):
        value = value.strip()
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
        if reader.fieldnames is None or set(reader.fieldnames) != {'prompt', 'classification'} or len(reader.fieldnames) != 2:
            raise APIError(400, 'ROUTE_CSV_INVALID', 'CSV表头必须为prompt,classification')
        samples = []
        prompts = set()
        for row in reader:
            if len(samples) >= 500:
                raise APIError(400, 'ROUTE_CSV_INVALID', '一次最多导入500条样本')
            if None in row or any(value is None for value in row.values()):
                raise APIError(400, 'ROUTE_CSV_INVALID', f'CSV第{reader.line_num}行列数不正确')
            try:
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
