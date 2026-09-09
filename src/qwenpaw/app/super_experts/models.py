"""Domain models shared by super-expert platform capabilities."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from qwenpaw.aigc.workflow_compiler import WorkflowGuideStepDefinition
from qwenpaw.aigc.workflow_contract import WorkflowBlueprint


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


class AigcTaskScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    installation_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    agent_task_id: str = Field(min_length=1)
    content_revision: int = Field(ge=0)
    material_task_id: str = Field(min_length=1)


class AigcTaskBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    installation_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    agent_task_id: str = Field(min_length=1)
    content_revision: int = Field(ge=0)
    material_task_id: str = Field(min_length=1)
    canvas_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    workflow_id: str | None = Field(default=None, min_length=1)
    execution_mode: Literal[
        "LEGACY",
        "PREBUILT_WORKFLOW",
        "MANUAL_BUILD",
    ] = "LEGACY"
    node_bindings: dict[str, str] = Field(default_factory=dict)
    output_node_id: str | None = Field(default=None, min_length=1)
    workflow_revision: int | None = Field(default=None, ge=1)
    guide_revision: int | None = Field(default=None, ge=1)


class AigcWorkflowGuideEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    action: Literal["SKIP_OPTIONAL"]
    workflow_id: str = Field(min_length=1)
    guide_revision: int = Field(ge=1)
    step_id: str = Field(min_length=1)
    logical_node_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AigcWorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workflow_id: str = Field(min_length=1)
    schema_version: Literal[1]
    execution_mode: Literal["PREBUILT_WORKFLOW", "MANUAL_BUILD"]
    workflow_revision: int = Field(ge=1)
    guide_revision: int = Field(ge=1)
    blueprint: WorkflowBlueprint
    guide_steps: tuple[WorkflowGuideStepDefinition, ...]
    manual_reason: str | None = Field(default=None, min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AigcTaskEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    from_status: AigcTaskStatus | None
    to_status: AigcTaskStatus
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AigcReviewAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)


class AigcMaterialTask(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    binding: AigcTaskBinding
    status: AigcTaskStatus
    asset_id: str | None = None
    review_assets: tuple[AigcReviewAsset, ...] = ()
    version: int = Field(ge=1)
    events: tuple[AigcTaskEvent, ...]
    operation_id: str | None = Field(default=None, min_length=1)
    operation_version: str | None = Field(default=None, min_length=1)
    operation_arguments: dict = Field(default_factory=dict)
    workflow: AigcWorkflowDefinition | None = None
    guide_events: tuple[AigcWorkflowGuideEvent, ...] = ()
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
