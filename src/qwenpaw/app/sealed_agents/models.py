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


class SealedAgentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    icon: str | None = None
    agent_type: Literal["sealed"] = "sealed"
    scope: Literal["global"] = "global"
    enabled: bool = True
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
