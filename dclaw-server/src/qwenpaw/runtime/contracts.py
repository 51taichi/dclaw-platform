"""Stable request, response, and channel contracts owned by DClaw."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Annotated, Any, Literal, TypeAlias
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MessageType:
    MESSAGE = "message"
    FUNCTION_CALL = "function_call"
    FUNCTION_CALL_OUTPUT = "function_call_output"
    PLUGIN_CALL = "plugin_call"
    PLUGIN_CALL_OUTPUT = "plugin_call_output"
    COMPONENT_CALL = "component_call"
    COMPONENT_CALL_OUTPUT = "component_call_output"
    MCP_LIST_TOOLS = "mcp_list_tools"
    MCP_APPROVAL_REQUEST = "mcp_approval_request"
    MCP_TOOL_CALL = "mcp_call"
    MCP_APPROVAL_RESPONSE = "mcp_approval_response"
    MCP_TOOL_CALL_OUTPUT = "mcp_call_output"
    REASONING = "reasoning"
    HEARTBEAT = "heartbeat"
    ERROR = "error"
    A2UI_RESPONSE = "a2ui_response"
    A2UI_ACTION = "a2ui_action"

    @classmethod
    def all_values(cls) -> list[str]:
        return [
            value
            for name, value in vars(cls).items()
            if not name.startswith("_") and isinstance(value, str)
        ]


class ContentType:
    TEXT = "text"
    DATA = "data"
    IMAGE = "image"
    AUDIO = "audio"
    FILE = "file"
    REFUSAL = "refusal"
    VIDEO = "video"


class Role:
    ASSISTANT = "assistant"
    USER = "user"
    SYSTEM = "system"
    TOOL = "tool"


class RunStatus:
    Created = "created"
    InProgress = "in_progress"
    Completed = "completed"
    Canceled = "canceled"
    Failed = "failed"
    Rejected = "rejected"
    Unknown = "unknown"
    Queued = "queued"
    Incomplete = "incomplete"


class FunctionParameters(BaseModel):
    type: str
    properties: dict[str, Any]
    required: list[str] | None = None


class FunctionTool(BaseModel):
    name: str
    description: str
    parameters: FunctionParameters | dict[str, Any]


class Tool(BaseModel):
    type: str | None = "function"
    function: FunctionTool | None = None


class FunctionCall(BaseModel):
    call_id: str | None = None
    name: str | None = None
    arguments: str | None = None


class FunctionCallOutput(BaseModel):
    call_id: str
    name: str | None = None
    output: str


class Error(BaseModel):
    code: str
    message: str


class Event(BaseModel):
    sequence_number: int | None = None
    object: str
    status: str | None = None
    error: Error | None = None

    def created(self):
        self.status = RunStatus.Created
        return self

    def in_progress(self):
        self.status = RunStatus.InProgress
        return self

    def completed(self):
        self.status = RunStatus.Completed
        return self

    def failed(self, error: Error):
        self.status = RunStatus.Failed
        self.error = error
        return self

    def rejected(self):
        self.status = RunStatus.Rejected
        return self

    def canceled(self):
        self.status = RunStatus.Canceled
        return self


class Content(Event):
    type: str
    object: str = "content"
    index: int | None = None
    delta: bool | None = False
    msg_id: str | None = None


class ImageContent(Content):
    type: Literal[ContentType.IMAGE] = ContentType.IMAGE
    image_url: str | None = None


class TextContent(Content):
    type: Literal[ContentType.TEXT] = ContentType.TEXT
    text: str | None = None


class DataContent(Content):
    type: Literal[ContentType.DATA] = ContentType.DATA
    data: dict[str, Any] | None = None


class AudioContent(Content):
    type: Literal[ContentType.AUDIO] = ContentType.AUDIO
    data: str | None = None
    format: str | None = None


class VideoContent(Content):
    type: Literal[ContentType.VIDEO] = ContentType.VIDEO
    video_url: str | None = None


class FileContent(Content):
    type: Literal[ContentType.FILE] = ContentType.FILE
    file_url: str | None = None
    file_id: str | None = None
    filename: str | None = None
    file_data: str | None = None


class RefusalContent(Content):
    type: Literal[ContentType.REFUSAL] = ContentType.REFUSAL
    refusal: str | None = None


AgentRole: TypeAlias = Literal["assistant", "system", "user", "tool"]
AgentContent = Annotated[
    TextContent
    | ImageContent
    | DataContent
    | AudioContent
    | FileContent
    | RefusalContent
    | VideoContent,
    Field(discriminator="type"),
]


class Message(Event):
    id: str = Field(default_factory=lambda: "msg_" + str(uuid4()))
    object: str = "message"
    type: str = MessageType.MESSAGE
    status: str = RunStatus.Created
    role: AgentRole | None = None
    content: list[AgentContent] | None = None
    code: str | None = None
    message: str | None = None
    usage: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    @staticmethod
    def from_openai_message(value: BaseModel | dict[str, Any]) -> "Message":
        if isinstance(value, Message):
            return value
        data = value.model_dump() if isinstance(value, BaseModel) else value
        if data.get("type") in MessageType.all_values():
            return Message(**data)
        role = data.get("role")
        if role == Role.ASSISTANT and data.get("tool_calls"):
            return Message(
                type=MessageType.FUNCTION_CALL,
                content=[
                    DataContent(
                        data=FunctionCall(
                            call_id=call.get("id"),
                            name=(call.get("function") or {}).get("name"),
                            arguments=(call.get("function") or {}).get(
                                "arguments"
                            ),
                        ).model_dump(),
                    )
                    for call in data["tool_calls"]
                ],
            )
        if role == Role.TOOL:
            return Message(
                type=MessageType.FUNCTION_CALL_OUTPUT,
                content=[
                    DataContent(
                        data=FunctionCallOutput(
                            call_id=data["tool_call_id"],
                            output=str(data.get("content", "")),
                        ).model_dump(),
                    )
                ],
            )
        raw_content = data.get("content")
        if isinstance(raw_content, str):
            content = [TextContent(text=raw_content)]
        else:
            content = []
            for item in raw_content or []:
                if item.get("type") == "image_url":
                    content.append(
                        ImageContent(image_url=(item.get("image_url") or {}).get("url"))
                    )
                elif item.get("type") == "text":
                    content.append(TextContent(text=item.get("text")))
                else:
                    content.append(DataContent(data=item))
        return Message(role=role, content=content)

    def get_text_content(self) -> str | None:
        for item in self.content or []:
            if isinstance(item, TextContent):
                return item.text
        return None

    def get_image_content(self) -> list[str]:
        return [
            item.image_url
            for item in self.content or []
            if isinstance(item, ImageContent) and item.image_url is not None
        ]

    def get_audio_content(self) -> list[str]:
        return [
            item.data
            for item in self.content or []
            if isinstance(item, AudioContent) and item.data is not None
        ]

    def add_delta_content(self, new_content: Content) -> Content | None:
        self.content = self.content or []
        if new_content.index is None:
            item = deepcopy(new_content)
            item.delta = None
            item.index = len(self.content)
            item.msg_id = self.id
            self.content.append(item)
            new_content.index = item.index
            new_content.msg_id = self.id
            return new_content.in_progress()
        if not new_content.delta or new_content.index >= len(self.content):
            return None
        previous = self.content[new_content.index]
        if isinstance(previous, TextContent) and isinstance(new_content, TextContent):
            previous.text = (previous.text or "") + (new_content.text or "")
        elif isinstance(previous, ImageContent) and isinstance(new_content, ImageContent):
            previous.image_url = (previous.image_url or "") + (new_content.image_url or "")
        elif isinstance(previous, DataContent) and isinstance(new_content, DataContent):
            previous.data = {**(previous.data or {}), **(new_content.data or {})}
        new_content.msg_id = self.id
        return new_content.in_progress()

    def content_completed(self, content_index: int) -> Content | None:
        if not self.content or content_index >= len(self.content):
            return None
        item = deepcopy(self.content[content_index])
        item.delta = False
        item.index = content_index
        item.msg_id = self.id
        return item.completed()

    def add_content(self, new_content: Content) -> Content | None:
        self.content = self.content or []
        if new_content.index is not None:
            return None
        self.content.append(deepcopy(new_content))
        new_content.index = len(self.content) - 1
        new_content.msg_id = self.id
        return new_content.completed()


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    input: list[Message]
    stream: bool = True
    id: str | None = None
    model: str | None = None
    top_p: float | None = None
    temperature: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    max_tokens: int | None = None
    stop: str | list[str] | None = None
    n: int | None = Field(default=1, ge=1, le=5)
    seed: int | None = None
    tools: list[Tool | dict[str, Any]] | None = None
    session_id: str | None = None
    user_id: str | None = None


class AgentResponse(Event):
    id: str | None = Field(default_factory=lambda: "response_" + str(uuid4()))
    object: str = "response"
    status: str = RunStatus.Created
    created_at: int = Field(default_factory=lambda: int(datetime.now().timestamp()))
    completed_at: int | None = None
    output: list[Message] | None = None
    usage: dict[str, Any] | None = None
    session_id: str | None = None

    @field_validator("id", mode="before")
    @classmethod
    def validate_id(cls, value):
        return value or "response_" + str(uuid4())

    def add_new_message(self, message: Message) -> None:
        self.output = self.output or []
        self.output.append(message)

    def completed(self):
        self.completed_at = int(datetime.now().timestamp())
        self.output = self.output or []
        return super().completed()


class SequenceNumberGenerator:
    def __init__(self, start: int = 0):
        self._current = start

    def yield_with_sequence(self, event: Event) -> Event:
        event.sequence_number = self._current
        self._current += 1
        return event
