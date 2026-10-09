"""Session-authenticated playground using the complete metered gateway pipeline."""
from typing import Literal
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.core.database import get_session
from app.core.dependencies import administrator
from app.gateway.pipeline import GatewayPipeline
from app.schemas.chat import ChatInput
from app.services.model_catalog import catalog

router = APIRouter(prefix='/api/admin/chat-test', tags=['对话测试'])
pipeline = GatewayPipeline()

class Message(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['system', 'user', 'assistant']
    content: str = Field(min_length=1, max_length=16000)

class ChatTestInput(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    model: str = Field(min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$')
    messages: list[Message] = Field(min_length=1, max_length=100)
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=512, ge=1, le=4096, strict=True)
    stream: bool = Field(default=True, strict=True)

    @model_validator(mode='after')
    def bounded_payload(self):
        ChatInput.model_validate(self.model_dump())
        return self

@router.get('/models')
async def models(user=Depends(administrator), db=Depends(get_session)):
    groups = await catalog(db, user.user_group_id)
    result = {}
    for group in groups:
        for model in group['models']:
            if model['model_type'] not in ('text', 'reasoning', 'multimodal'):
                continue
            name = model['logical_model']
            if name not in result:
                result[name] = {**model, 'groups': []}
            result[name]['configured'] |= model['configured']
            if group['name'] not in result[name]['groups']:
                result[name]['groups'].append(group['name'])
    return {'data': {'models': sorted(result.values(), key=lambda item: item['logical_model'])}}

@router.post('/completions')
async def completion(body: ChatTestInput, request: Request, user=Depends(administrator), db=Depends(get_session)):
    payload = body.model_dump()
    if body.stream:
        payload['stream_options'] = {'include_usage': True}
    validated = ChatInput.model_validate(payload)
    return await pipeline.run(request, db, 'chat', body.model, validated.model_dump(exclude_unset=True))
