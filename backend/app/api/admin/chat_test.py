"""Session-authenticated playground using the complete metered gateway pipeline."""
import base64
import binascii
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from app.core.database import get_session
from app.core.dependencies import administrator
from app.gateway.pipeline import GatewayPipeline
from app.schemas.chat import ChatInput
from app.services.model_catalog import catalog

router = APIRouter(prefix='/api/admin/chat-test', tags=['对话测试'])
pipeline = GatewayPipeline()

MAX_ATTACHMENT_BYTES = 1024 * 1024

def decoded_data(value, mime):
    prefix = f'data:{mime};base64,'
    if not value.startswith(prefix):
        raise ValueError('附件必须使用受支持的内嵌文件格式')
    encoded = value[len(prefix):]
    if len(encoded) > (MAX_ATTACHMENT_BYTES + 2) // 3 * 4:
        raise ValueError('附件最大为1 MiB')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('附件Base64格式无效') from None
    if not raw or len(raw) > MAX_ATTACHMENT_BYTES:
        raise ValueError('附件为空或超过1 MiB')
    valid = {'image/png': raw.startswith(b'\x89PNG\r\n\x1a\n'),
             'image/jpeg': raw.startswith(b'\xff\xd8\xff'),
             'image/gif': raw.startswith((b'GIF87a', b'GIF89a')),
             'image/webp': raw.startswith(b'RIFF') and raw[8:12] == b'WEBP',
             'application/pdf': raw.startswith(b'%PDF-')}
    if not valid.get(mime):
        raise ValueError('附件内容与文件类型不匹配')
    return raw

class TextPart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['text']
    text: str = Field(min_length=1, max_length=66000)

class ImageData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str = Field(max_length=1400000)

    @field_validator('url')
    @classmethod
    def valid_image(cls, value):
        mime = value.split(';', 1)[0].removeprefix('data:')
        if mime not in ('image/png', 'image/jpeg', 'image/gif', 'image/webp'):
            raise ValueError('仅支持PNG、JPEG、GIF和WebP图片')
        decoded_data(value, mime)
        return value

class ImagePart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['image_url']
    image_url: ImageData

class FileData(BaseModel):
    model_config = ConfigDict(extra='forbid')
    filename: str = Field(min_length=1, max_length=200)
    file_data: str = Field(max_length=1400000)

    @field_validator('filename')
    @classmethod
    def valid_name(cls, value):
        if any(ord(c) < 32 for c in value) or '/' in value or '\\' in value or not value.lower().endswith('.pdf'):
            raise ValueError('PDF文件名无效')
        return value

    @field_validator('file_data')
    @classmethod
    def valid_pdf(cls, value):
        decoded_data(value, 'application/pdf')
        return value

class FilePart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: Literal['file']
    file: FileData

Part = Annotated[TextPart | ImagePart | FilePart, Field(discriminator='type')]

class Message(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['system', 'user', 'assistant']
    content: str | list[Part]

    @model_validator(mode='after')
    def valid_content(self):
        if isinstance(self.content, str):
            if not 1 <= len(self.content) <= 16000:
                raise ValueError('消息文本须为1至16000字符')
        else:
            if self.role != 'user' or not 1 <= len(self.content) <= 5:
                raise ValueError('只有用户消息可以包含附件，每条最多5个内容块')
            size = 0
            count = 0
            for part in self.content:
                if isinstance(part, ImagePart):
                    count += 1
                    mime = part.image_url.url.split(';', 1)[0].removeprefix('data:')
                    size += len(decoded_data(part.image_url.url, mime))
                elif isinstance(part, FilePart):
                    count += 1
                    size += len(decoded_data(part.file.file_data, 'application/pdf'))
            if count > 4 or size > MAX_ATTACHMENT_BYTES:
                raise ValueError('每条消息最多4个附件，附件总大小不超过1 MiB')
        return self

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
    if any(isinstance(item.content, list) for item in body.messages):
        from app.models.user import LogicalModel
        from app.core.exceptions import APIError
        model = await db.get(LogicalModel, body.model)
        if not model or model.model_type != 'multimodal':
            raise APIError(400, 'MULTIMODAL_MODEL_REQUIRED', '请选用多模态模型发送附件')
    payload = body.model_dump()
    if body.stream:
        payload['stream_options'] = {'include_usage': True}
    validated = ChatInput.model_validate(payload)
    return await pipeline.run(request, db, 'chat', body.model, validated.model_dump(exclude_unset=True))
