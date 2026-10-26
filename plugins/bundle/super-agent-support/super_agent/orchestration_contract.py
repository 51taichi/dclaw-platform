"""Strict contracts shared by generic workspace-turn orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    field_validator,
    model_validator,
)

from qwenpaw.config.config import (
    OrchestrationConfig,
    WORKSPACE_RUNTIME_HOST_CAPABILITIES_V1,
)

HOST_CAPABILITIES_V1 = WORKSPACE_RUNTIME_HOST_CAPABILITIES_V1


class WorkspaceTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    release_id: str = Field(min_length=1)
    release_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    installation_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    normalized_input: dict[str, Any]
    history: list[dict[str, Any]]
    safe_metadata: dict[str, Any]
    diagnostics_authorized: bool = False
    granted_capabilities: dict[str, str]
    state_root: Path
    transaction_root: Path

    # Assigned by WorkspaceTurnOrchestrator after request validation.  These
    # values are deliberately absent from the wire/model schema: customer
    # input cannot forge or extend the host's monotonic execution budget.
    _runtime_deadline_monotonic: float | None = PrivateAttr(default=None)
    _runtime_deadline_reserve_seconds: float = PrivateAttr(default=0.0)
    _runtime_continuation: bool = PrivateAttr(default=False)

    @field_validator("state_root", "transaction_root")
    @classmethod
    def state_path_is_absolute(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("workspace state path must be absolute")
        return value

    @model_validator(mode="after")
    def transaction_is_not_committed_root(self) -> "WorkspaceTurnRequest":
        if self.state_root == self.transaction_root:
            raise ValueError("transaction root must differ from state root")
        return self


class WorkspaceTurnCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: str = Field(min_length=1)
    message: dict[str, Any]
    diagnostics: dict[str, Any] | None = None


class WorkspaceTurnFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: str = Field(min_length=1)
    error_code: str = Field(
        pattern=(
            r"^(orchestration_error|orchestration_timeout|runtime_failed|"
            r"unauthorized_capability|invalid_completion)$"
        ),
    )
    diagnostic_ref: str | None = Field(default=None, max_length=200)


__all__ = [
    "HOST_CAPABILITIES_V1",
    "OrchestrationConfig",
    "WorkspaceTurnCompletion",
    "WorkspaceTurnFailure",
    "WorkspaceTurnRequest",
]
