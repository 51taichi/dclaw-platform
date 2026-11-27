# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


MobileDisplayStatus = Literal[
    "running",
    "pending_confirmation",
    "completed",
    "failed",
    "idle",
]


class MobileTaskSummary(BaseModel):
    id: str
    session_id: str
    name: str
    agent_id: str | None = None
    expert_team_id: str | None = None
    active_mode: str | None = None
    runtime_status: str | None = None
    task_status: str | None = None
    display_status: MobileDisplayStatus
    pending_confirmation_count: int = 0
    artifact_count: int = 0
    message_count: int = 0
    has_assistant_response: bool = False
    updated_at: float | None = None


class MobilePendingConfirmation(BaseModel):
    request_id: str
    session_id: str
    root_session_id: str
    owner_agent_id: str | None = None
    agent_id: str
    tool_name: str
    severity: str
    findings_count: int = 0
    findings_summary: str = ""
    tool_params: dict[str, Any] = Field(default_factory=dict)
    created_at: float
    timeout_seconds: int


class MobileArtifactSummary(BaseModel):
    name: str
    path: str
    size: int | None = None
    modified_time: str | None = None
    kind: str = "file"


class MobileWorkbenchResponse(BaseModel):
    user_id: str
    pending_confirmation_count: int
    running_task_count: int
    recent_tasks: list[MobileTaskSummary]
    recent_results: list[MobileArtifactSummary]


class MobileTaskDetailResponse(BaseModel):
    task: MobileTaskSummary
    messages: list[dict[str, Any]]
    confirmations: list[MobilePendingConfirmation]
    artifacts: list[MobileArtifactSummary]


class MobileConfirmationActionResponse(BaseModel):
    success: bool
    message: str
    request_id: str
    tool_name: str | None = None
