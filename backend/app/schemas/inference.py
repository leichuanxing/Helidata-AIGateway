"""Bounded native protocol inputs; vendor extensions survive native forwarding."""
import json
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,JsonValue,model_validator

class Input(BaseModel):
    model_config=ConfigDict(extra='allow',allow_inf_nan=False)
    model:str=Field(min_length=1,max_length=100,pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$')
    @model_validator(mode='after')
    def bounded(self):
        if len(json.dumps(self.model_dump(exclude_unset=True),ensure_ascii=False,allow_nan=False).encode())>2*1024*1024:
            raise ValueError('payload exceeds 2MiB')
        return self

class ResponsesInput(Input):
    input:str|list[dict[str,JsonValue]]|None=None
    previous_response_id:str|None=Field(default=None,max_length=200)
    stream:bool=Field(default=False,strict=True)
    background:Literal[False]=False
    max_output_tokens:int|None=Field(default=None,strict=True,gt=0)
    @model_validator(mode='after')
    def content(self):
        if self.input is None and not self.previous_response_id:raise ValueError('input or previous response required')
        return self

class Message(BaseModel):
    model_config=ConfigDict(extra='allow')
    role:Literal['user','assistant']
    content:str|list[dict[str,JsonValue]]

class MessagesInput(Input):
    messages:list[Message]=Field(min_length=1,max_length=1000)
    max_tokens:int=Field(strict=True,ge=0)
    stream:bool=Field(default=False,strict=True)
    system:str|list[dict[str,JsonValue]]|None=None

class EmbeddingsInput(Input):
    input:str|list[str]|list[int]|list[list[int]]
    encoding_format:Literal['float','base64']='float'
    dimensions:int|None=Field(default=None,strict=True,gt=0,le=65536)
    @model_validator(mode='after')
    def nonempty(self):
        if not self.input or isinstance(self.input,list) and any(x=='' or x==[] for x in self.input):raise ValueError('empty embedding input')
        if self.model_extra.get('stream'):raise ValueError('embeddings do not stream')
        return self

class RerankInput(Input):
    query:str=Field(min_length=1)
    documents:list[str]=Field(min_length=1,max_length=1000)
    top_n:int|None=Field(default=None,strict=True,gt=0)
    @model_validator(mode='after')
    def limit(self):
        if self.top_n and self.top_n>len(self.documents):raise ValueError('top_n exceeds document count')
        if self.model_extra.get('stream'):raise ValueError('rerank does not stream')
        return self

class ImagesInput(Input):
    prompt:str=Field(min_length=1)
    n:int=Field(default=1,strict=True,ge=1,le=10)
    stream:Literal[False]=False
