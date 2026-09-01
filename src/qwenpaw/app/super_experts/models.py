"""Domain models shared by super-expert platform capabilities."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AigcTaskStatus(str, Enum):
    WAITING_TO_START = "WAITING_TO_START"
    IN_PROGRESS = "IN_PROGRESS"
    PAUSED = "PAUSED"
    SUBMITTED = "SUBMITTED"
    REVIEWING = "REVIEWING"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"
    INVALIDATED = "INVALIDATED"


class AigcTaskBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    installation_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    agent_task_id: str = Field(min_length=1)
    content_revision: int = Field(ge=0)
    material_task_id: str = Field(min_length=1)
    canvas_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)


class AigcTaskEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    from_status: AigcTaskStatus | None
    to_status: AigcTaskStatus
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AigcMaterialTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    binding: AigcTaskBinding
    status: AigcTaskStatus
    asset_id: str | None = None
    version: int = Field(ge=1)
    events: tuple[AigcTaskEvent, ...]
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
