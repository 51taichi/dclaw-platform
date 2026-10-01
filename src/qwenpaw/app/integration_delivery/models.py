"""Public-safe contracts returned to the independent integration client."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class IntegrationModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
    )


class Readiness(IntegrationModel):
    ready: bool
    missing_items: list[str] = Field(default_factory=list)


class DclawConfigurationContext(IntegrationModel):
    agent_id: str
    agent_type: Literal["standard", "sealed", "unknown"]
    agent_profile_id: str | None = None
    enabled: bool
    source_version: str | None = None
    publication_id: str | None = None
    openapi_public_id: str | None = None
    knowledge_base_id: str | None = None
    billing_account_configured: bool = False
    readiness: Readiness
