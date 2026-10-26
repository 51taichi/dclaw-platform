"""Data contracts for application-layer sealed agents."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SealedCapability(str, Enum):
    INVOKE = "invoke"
    PUBLIC_METADATA = "public_metadata"
    INSPECT = "inspect"
    EDIT = "edit"
    CLONE = "clone"
    EXPORT = "export"
    DOWNLOAD = "download"
    TRACE = "trace"


class AgentCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    invoke: bool
    public_metadata: bool
    inspect: bool
    edit: bool
    clone: bool
    export: bool
    download: bool
    trace: bool

    @classmethod
    def for_sealed_global(cls) -> "AgentCapabilities":
        return cls(
            invoke=True,
            public_metadata=True,
            inspect=False,
            edit=False,
            clone=False,
            export=False,
            download=False,
            trace=False,
        )

    @classmethod
    def for_standard(cls) -> "AgentCapabilities":
        return cls(
            invoke=True,
            public_metadata=True,
            inspect=True,
            edit=True,
            clone=True,
            export=True,
            download=True,
            trace=True,
        )


class SealedReleaseRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    release_id: str
    version: str
    content_digest: str
    signer_id: str
    package_type: str = Field(
        default="sealed_agent",
        pattern=r"^[a-z][a-z0-9_]{0,63}$",
    )
    capability_digest: str | None = None
    declared_capabilities: tuple[tuple[str, str], ...] = ()
    orchestration_capability_id: str | None = None
    orchestration_contract_version: str | None = None
    orchestration_entrypoint: str | None = None
    orchestration_required_host_capabilities: tuple[str, ...] = ()
    entrypoint: str | None = None
    runtime_adapter: str | None = None
    runtime_contract_version: str | None = None
    runtime_failure_policy: Literal["fail_closed"] | None = None
    runtime_validation: "RuntimeValidationRecord | None" = None
    state: Literal[
        "uploaded",
        "validating",
        "staged",
        "testing",
        "ready",
        "active",
        "rejected",
        "failed",
        "superseded",
        "disabled",
    ] = "ready"
    installed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


class RuntimeValidationRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["valid", "invalid"]
    validated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    adapter: str
    contract_version: str
    error_code: str | None = None


class SealedAgentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    icon: str | None = None
    avatar: str | None = None
    banner_image: str | None = None
    agent_type: Literal["sealed"] = "sealed"
    scope: Literal["global"] = "global"
    enabled: bool = True
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    active_release_id: str | None = None
    releases: list[SealedReleaseRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def active_release_must_exist(self) -> "SealedAgentRecord":
        if self.active_release_id and self.active_release_id not in {
            release.release_id for release in self.releases
        }:
            raise ValueError("active release does not exist")
        return self

    @property
    def active_release(self) -> SealedReleaseRecord | None:
        return next(
            (
                release
                for release in self.releases
                if release.release_id == self.active_release_id
            ),
            None,
        )
