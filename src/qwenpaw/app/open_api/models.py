# -*- coding: utf-8 -*-
"""Pydantic models for external Open API publications and calls."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OpenApiTargetType = Literal["agent", "expert_team"]
OpenApiStatus = Literal["enabled", "disabled"]
ApiKeyStatus = Literal["active", "revoked"]
OpenApiInvocationStatus = Literal[
    "accepted",
    "pending",
    "running",
    "succeeded",
    "failed",
    "cancelled",
]
OpenApiScope = Literal["messages:create", "messages:read", "runs:stop"]

SCOPE_MESSAGES_CREATE = "messages:create"
SCOPE_MESSAGES_READ = "messages:read"
SCOPE_RUNS_STOP = "runs:stop"
OPEN_API_SCOPES: tuple[OpenApiScope, ...] = (
    SCOPE_MESSAGES_CREATE,
    SCOPE_MESSAGES_READ,
    SCOPE_RUNS_STOP,
)


class OpenApiPublication(BaseModel):
    id: str
    public_id: str
    target_type: OpenApiTargetType
    target_id: str
    owner_user_id: str
    bound_user_id: str
    knowledge_base_id: str
    name: str
    description: str = ""
    status: OpenApiStatus = "enabled"
    allowed_scopes: list[OpenApiScope] = Field(default_factory=list)
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class ExternalApp(BaseModel):
    id: str
    owner_user_id: str
    name: str
    status: OpenApiStatus = "enabled"
    ip_allowlist: list[str] = Field(default_factory=list)
    quota_policy: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class ExternalApiKey(BaseModel):
    id: str
    app_id: str
    publication_id: str
    key_hash: str
    key_prefix: str
    key_suffix: str
    scopes: list[OpenApiScope] = Field(default_factory=list)
    status: ApiKeyStatus = "active"
    expires_at: datetime | str | None = None
    last_used_at: datetime | str | None = None
    last_used_ip: str | None = None
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class OpenApiInvocation(BaseModel):
    id: str
    app_id: str
    publication_id: str
    api_key_id: str
    target_type: OpenApiTargetType
    target_id: str
    chat_id: str | None = None
    external_session_id: str | None = None
    external_user_id: str | None = None
    status: OpenApiInvocationStatus
    status_code: int | None = None
    latency_ms: int = 0
    token_summary: dict[str, Any] = Field(default_factory=dict)
    error_summary: str | None = None
    created_at: datetime | str | None = None


class GroupHistoryMessageInput(BaseModel):
    """One immutable external group message stored without invoking an Agent."""

    model_config = ConfigDict(extra="forbid")

    external_message_id: str = Field(min_length=1, max_length=160)
    occurred_at: datetime
    sender_id: str = Field(default="", max_length=200)
    sender_name: str = Field(min_length=1, max_length=300)
    participant_role_id: str = Field(default="", max_length=160)
    direction: Literal["inbound", "outbound"]
    source: str = Field(min_length=1, max_length=100)
    message_type: str = Field(min_length=1, max_length=80)
    content: str = Field(default="", max_length=20000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def occurred_at_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value


class AppendGroupHistoryRequest(BaseModel):
    """Bounded append batch for a publication-scoped group history."""

    model_config = ConfigDict(extra="forbid")

    messages: list[GroupHistoryMessageInput] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def enforce_serialized_body_limit(self) -> "AppendGroupHistoryRequest":
        body = json.dumps(
            [message.model_dump(mode="json") for message in self.messages],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > 1_500_000:
            raise ValueError("group history append body exceeds 1.5 MB")
        return self


class AppendGroupHistoryResponse(BaseModel):
    history_id: str
    inserted: int = Field(ge=0)
    duplicates: int = Field(ge=0)


class GroupHistoryMessage(BaseModel):
    external_message_id: str
    occurred_at: datetime
    sender_id: str = ""
    sender_name: str
    participant_role_id: str = ""
    direction: Literal["inbound", "outbound"]
    source: str
    message_type: str
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class GroupHistoryPage(BaseModel):
    messages: list[GroupHistoryMessage] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False
