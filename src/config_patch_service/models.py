"""Public API and service identity models."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class StaffTokenView(ApiModel):
    token_id: str
    employee_name: str
    token_name: str
    token_prefix: str
    token_suffix: str
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class IssuedStaffToken(StaffTokenView):
    token: str = Field(repr=False)


class AuthenticatedStaffToken(ApiModel):
    token_id: str
    employee_name: str
    token_name: str


class CreateStaffTokenRequest(ApiModel):
    employee_name: str = Field(min_length=1, max_length=120)
    token_name: str = Field(min_length=1, max_length=120)
    expires_at: datetime | None = None


class StaffTokenList(ApiModel):
    tokens: list[StaffTokenView]


class UpstreamReadiness(ApiModel):
    ready: bool
    checks: dict[str, bool] = Field(default_factory=dict)
    missing_items: list[str] = Field(default_factory=list)


class DclawLocation(ApiModel):
    base_url: str
    public_id: str


class OmnichannelBotSummary(ApiModel):
    bot_id: str
    bot_name: str
    enabled: bool
    agent_id: str
    agent_name: str
    dclaw: DclawLocation
    readiness: UpstreamReadiness
    configuration_digest: str


class OmnichannelBotIdentity(ApiModel):
    bot_id: str
    bot_name: str
    enabled: bool


class OmnichannelAgentIdentity(ApiModel):
    agent_id: str
    agent_name: str
    enabled: bool
    dclaw: DclawLocation


class OmnichannelBotSnapshot(ApiModel):
    schema_version: str
    bot: OmnichannelBotIdentity
    agent: OmnichannelAgentIdentity
    flow_machine: dict[str, Any]
    tags: dict[str, Any]
    source: dict[str, Any]
    readiness: UpstreamReadiness
    digests: dict[str, str]


class DclawConfigurationContext(ApiModel):
    agent_id: str
    agent_type: Literal["standard", "sealed", "unknown"]
    agent_profile_id: str | None = None
    enabled: bool
    source_version: str | None = None
    publication_id: str | None = None
    openapi_public_id: str | None = None
    knowledge_base_id: str | None = None
    billing_account_configured: bool = False
    readiness: UpstreamReadiness


class DclawSnapshotArchive(ApiModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    archive: bytes = Field(repr=False)
    agent_id: str
    profile_id: str
    source_version: str
    agent_digest: str
    knowledge_digest: str


class ConfigurationReadiness(ApiModel):
    status: Literal["ready", "not_ready", "unavailable"]
    ready: bool
    missing_items: list[str] = Field(default_factory=list)
    code: str | None = None


class BotConfigurationTarget(ApiModel):
    bot_id: str
    bot_name: str
    enabled: bool
    bound_agent_id: str
    agent_profile_id: str | None = None
    openapi_publication_id: str | None = None
    openapi_public_id: str | None = None
    knowledge_base_id: str | None = None
    readiness: ConfigurationReadiness
    current_release_id: str | None = None


class BotConfigurationContext(BotConfigurationTarget):
    agent_type: Literal["standard", "sealed", "unknown"] | None = None
    source_version: str | None = None
    flow_machine: dict[str, Any]
    tags: dict[str, Any]


class BotConfigurationTargetList(ApiModel):
    bots: list[BotConfigurationTarget]
