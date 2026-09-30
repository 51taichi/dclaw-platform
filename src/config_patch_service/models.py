"""Public API and service identity models."""

from __future__ import annotations

from datetime import datetime

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
