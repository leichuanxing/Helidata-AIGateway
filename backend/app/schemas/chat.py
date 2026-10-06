"""OpenAI compatible input; provider extensions survive validation unchanged."""
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra='allow')
    role: Literal['developer', 'system', 'user', 'assistant', 'tool', 'function']
    content: str | list[dict[str, JsonValue]] | None = None
    tool_calls: list[dict[str, JsonValue]] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    function_call: dict[str, JsonValue] | None = None
    refusal: str | None = None

    @model_validator(mode='after')
    def valid_message(self):
        if self.role != 'assistant' and self.content is None:
            raise ValueError('message content required')
        if self.role == 'assistant' and self.content is None and not (self.tool_calls or self.function_call or self.refusal):
            raise ValueError('assistant content or call required')
        if self.role == 'tool' and not self.tool_call_id:
            raise ValueError('tool_call_id required')
        if self.role == 'function' and not self.name:
            raise ValueError('function name required')
        return self


class ChatInput(BaseModel):
    model_config = ConfigDict(extra='allow', allow_inf_nan=False)
    model: str = Field(min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._:/-]*$')
    messages: list[ChatMessage] = Field(min_length=1, max_length=1000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int | None = Field(default=None, strict=True, gt=0)
    max_completion_tokens: int | None = Field(default=None, strict=True, gt=0)
    stream: bool = Field(default=False, strict=True)
    tools: list[dict[str, JsonValue]] | None = None
    tool_choice: Literal['none', 'auto', 'required'] | dict[str, JsonValue] | None = None
    response_format: dict[str, JsonValue] | None = None

    @model_validator(mode='after')
    def bounded_payload(self):
        if len(json.dumps(self.model_dump(exclude_unset=True), ensure_ascii=False, allow_nan=False).encode()) > 2 * 1024 * 1024:
            raise ValueError('chat payload exceeds 2 MiB')
        return self


class CompletionMessage(BaseModel):
    model_config = ConfigDict(extra='allow')
    role: Literal['assistant']
    content: str | None = None
    tool_calls: list[dict[str, JsonValue]] | None = None
    function_call: dict[str, JsonValue] | None = None
    refusal: str | None = None


class CompletionChoice(BaseModel):
    model_config = ConfigDict(extra='allow')
    index: int = Field(strict=True, ge=0)
    message: CompletionMessage
    finish_reason: str | None


class ChatCompletion(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str = Field(min_length=1)
    object: Literal['chat.completion']
    created: int = Field(strict=True, ge=0)
    model: str
    choices: list[CompletionChoice] = Field(min_length=1)


class ChunkChoice(BaseModel):
    model_config = ConfigDict(extra='allow')
    index: int = Field(strict=True, ge=0)
    delta: dict[str, JsonValue]
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    model_config = ConfigDict(extra='allow')
    id: str = Field(min_length=1)
    object: Literal['chat.completion.chunk']
    created: int = Field(strict=True, ge=0)
    model: str
    choices: list[ChunkChoice]  # Usage-only final chunks legitimately have an empty list.
