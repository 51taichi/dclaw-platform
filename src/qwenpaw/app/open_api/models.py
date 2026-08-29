# -*- coding: utf-8 -*-
"""Pydantic models for external Open API publications and calls."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

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
    billing_usage_order_id: str | None = None
    billing_status: str = "unbilled"
    quoted_credits: int = 0
    captured_credits: int = 0
    released_credits: int = 0
    billing_error_code: str | None = None
    created_at: datetime | str | None = None
