# -*- coding: utf-8 -*-
"""Runtime preparation helpers for external Open API message calls."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import re
from typing import Any

from agentscope_runtime.engine.schemas.agent_schemas import (
    ContentType,
    TextContent,
)
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update

from ..agent_context import (
    reset_current_billing_context,
    set_current_billing_context,
)
from ..billing.open_api import OpenApiBillingSession
from ..billing.open_api import OpenApiBillingCoordinator
from ..billing.model_meter import BillingModelMeter
from ..billing.pricing import PriceCatalogService
from ..billing.usage import (
    InsufficientUsageCreditsError,
    SettleModelCall,
    UsageService,
)
from ..storage.engine import get_app_engine
from ..storage.repos.billing_repo import BillingRepository
from ..storage.repos.open_api_repo import SqlAlchemyOpenApiRepository
from ..storage.repos.price_catalog_repo import PriceCatalogRepository
from ..storage.schema import (
    billing_usage_items,
    billing_usage_orders,
    create_all,
    open_api_invocations,
)

_SAFE_ID_PATTERN = re.compile(r"[^A-Za-z0-9_.:-]+")
_MAX_EXTERNAL_ID_LENGTH = 128
_MAX_MESSAGE_LENGTH = 20_000
_BILLING_MODES = frozenset({"off", "shadow", "observe", "enforced"})
_current_billing_meter: ContextVar[BillingModelMeter | None] = ContextVar(
    "open_api_billing_meter",
    default=None,
)


class OpenMessageRequest(BaseModel):
    external_user_id: str
    external_session_id: str | None = None
    message: str
    stream: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("external_user_id")
    @classmethod
    def validate_external_user_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("external_user_id is required")
        if len(value) > _MAX_EXTERNAL_ID_LENGTH:
            raise ValueError("external_user_id is too long")
        return value

    @field_validator("external_session_id")
    @classmethod
    def validate_external_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) > _MAX_EXTERNAL_ID_LENGTH:
            raise ValueError("external_session_id is too long")
        return value

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message is required")
        if len(value) > _MAX_MESSAGE_LENGTH:
            raise ValueError("message is too long")
        return value


@dataclass
class PreparedOpenRun:
    chat_id: str
    session_id: str
    channel: str
    agent_id: str
    payload: dict[str, Any]
    workspace: Any
    console_channel: Any


@dataclass
class OpenApiBillingRuntime:
    """Explicit request-runtime dependencies for OpenAPI billing."""

    repository: BillingRepository
    pricing: PriceCatalogService
    coordinator: OpenApiBillingCoordinator
    usage_service: UsageService
    open_api_repository: SqlAlchemyOpenApiRepository
    mode: str
    budget_credits: int
    default_max_output_tokens: int = 1024

    def execution(self) -> "OpenApiBillingExecution":
        return OpenApiBillingExecution(self)


class _RequestBillingMeter(BillingModelMeter):
    def __init__(
        self,
        runtime: OpenApiBillingRuntime,
        execution: "OpenApiBillingExecution",
    ) -> None:
        super().__init__(
            runtime.usage_service,
            default_max_output_tokens=runtime.default_max_output_tokens,
        )
        self._execution = execution

    def before_call(self, **kwargs):
        try:
            call = super().before_call(**kwargs)
        except InsufficientUsageCreditsError as exc:
            self._execution.note_insufficient(exc)
            raise
        if call is not None:
            self._execution.note_first_reservation()
        return call


class OpenApiBillingExecution:
    """Per-invocation preflight signal and financial meter."""

    def __init__(self, runtime: OpenApiBillingRuntime) -> None:
        self.runtime = runtime
        self.meter = _RequestBillingMeter(runtime, self)
        self._preflight_ready = asyncio.Event()
        self._initial_failure: InsufficientUsageCreditsError | None = None
        self.insufficient: InsufficientUsageCreditsError | None = None
        self.reservation_succeeded = False

    def note_first_reservation(self) -> None:
        if not self.reservation_succeeded:
            self.reservation_succeeded = True
            self._preflight_ready.set()

    def note_insufficient(self, exc: InsufficientUsageCreditsError) -> None:
        self.insufficient = exc
        if not self.reservation_succeeded:
            self._initial_failure = exc
            self._preflight_ready.set()

    def note_stream_ready(self) -> None:
        """Unblock requests that legitimately complete without a model call."""
        self._preflight_ready.set()

    async def wait_for_preflight(self) -> None:
        await self._preflight_ready.wait()
        if self._initial_failure is not None:
            raise self._initial_failure


def create_open_api_billing_runtime() -> OpenApiBillingRuntime:
    """Build explicit billing services over the configured durable engine."""
    engine = get_app_engine()
    create_all(engine)
    repository = BillingRepository(engine)
    pricing = PriceCatalogService(PriceCatalogRepository(engine))
    mode = _billing_mode()
    return OpenApiBillingRuntime(
        repository=repository,
        pricing=pricing,
        coordinator=OpenApiBillingCoordinator(repository, pricing),
        usage_service=UsageService(repository, pricing, mode=mode),
        open_api_repository=SqlAlchemyOpenApiRepository(engine),
        mode=mode,
        budget_credits=_non_negative_env(
            "DCLAW_OPEN_API_MAX_CREDITS",
            100_000,
        ),
        default_max_output_tokens=_non_negative_env(
            "DCLAW_OPEN_API_DEFAULT_OUTPUT_TOKENS",
            1024,
        ),
    )


def get_current_billing_meter() -> BillingModelMeter | None:
    """Return the request-scoped meter consumed by model construction."""
    return _current_billing_meter.get()


@contextmanager
def open_api_billing_context(
    session: OpenApiBillingSession,
    meter: BillingModelMeter | None = None,
):
    """Scope a committed billing session to an OpenAPI execution path."""
    token = set_current_billing_context(session)
    meter_token: Token[BillingModelMeter | None] = _current_billing_meter.set(
        meter,
    )
    try:
        yield session
    finally:
        _current_billing_meter.reset(meter_token)
        reset_current_billing_context(token)


def recover_open_api_billing(
    runtime: OpenApiBillingRuntime | None = None,
) -> int:
    """Conservatively recover only bridge-created nonterminal orders.

    A held item has no durable provider-contact marker, so it is safe to
    release.  A reconciling item is deliberately left untouched.  Historical
    invocations have ``billing_status='unbilled'`` and never enter this scan.
    """
    active = runtime or create_open_api_billing_runtime()
    engine = active.repository.engine
    with engine.connect() as conn:
        rows = (
            conn.execute(
                select(
                    billing_usage_orders.c.id.label("order_id"),
                    billing_usage_orders.c.status.label("order_status"),
                    open_api_invocations.c.id.label("invocation_id"),
                )
                .join(
                    open_api_invocations,
                    open_api_invocations.c.billing_usage_order_id
                    == billing_usage_orders.c.id,
                )
                .where(
                    billing_usage_orders.c.source_type == "open_api",
                    billing_usage_orders.c.status.in_(
                        ("quoted", "held", "reconciling"),
                    ),
                    open_api_invocations.c.billing_status != "unbilled",
                ),
            )
            .mappings()
            .all()
        )

    recovered = 0
    for row in rows:
        order_id = str(row["order_id"])
        with engine.connect() as conn:
            items = (
                conn.execute(
                    select(billing_usage_items).where(
                        billing_usage_items.c.usage_order_id == order_id,
                    ),
                )
                .mappings()
                .all()
            )
        for item in items:
            if str(item["status"]) != "held":
                continue
            active.usage_service.settle_model_call(
                SettleModelCall(
                    usage_order_id=order_id,
                    item_key=str(item["item_key"]),
                    supplier_reference="",
                    billability="not_billable",
                    evidence={
                        "adapter_version": "open-api-recovery-v1",
                        "response_class": "recovered_before_provider_contact",
                        "timestamp": datetime.now(timezone.utc).isoformat(
                            timespec="seconds",
                        ),
                    },
                ),
            )
            recovered += 1

        with engine.begin() as conn:
            remaining = (
                conn.execute(
                    select(billing_usage_items.c.status).where(
                        billing_usage_items.c.usage_order_id == order_id,
                    ),
                )
                .scalars()
                .all()
            )
            remaining_statuses = {str(value) for value in remaining}
            if not remaining:
                now = datetime.now(timezone.utc)
                conn.execute(
                    update(billing_usage_orders)
                    .where(
                        billing_usage_orders.c.id == order_id,
                        billing_usage_orders.c.status == "quoted",
                    )
                    .values(status="settled", settled_at=now, updated_at=now),
                )
                conn.execute(
                    update(open_api_invocations)
                    .where(
                        open_api_invocations.c.id == row["invocation_id"],
                        open_api_invocations.c.billing_status != "unbilled",
                    )
                    .values(
                        status="failed",
                        status_code=500,
                        error_summary="request interrupted by process restart",
                        billing_status="settled",
                    ),
                )
                recovered += 1
            elif "reconciling" in remaining_statuses:
                conn.execute(
                    update(billing_usage_orders)
                    .where(billing_usage_orders.c.id == order_id)
                    .values(status="reconciling"),
                )
                conn.execute(
                    update(open_api_invocations)
                    .where(
                        open_api_invocations.c.id == row["invocation_id"],
                        open_api_invocations.c.billing_status != "unbilled",
                    )
                    .values(billing_status="reconciling"),
                )
            elif remaining_statuses <= {"captured", "released"}:
                conn.execute(
                    update(open_api_invocations)
                    .where(
                        open_api_invocations.c.id == row["invocation_id"],
                        open_api_invocations.c.status.in_(
                            ("accepted", "running"),
                        ),
                    )
                    .values(
                        status="failed",
                        status_code=500,
                        error_summary="request interrupted by process restart",
                    ),
                )
    return recovered


def _billing_mode() -> str:
    mode = os.environ.get("DCLAW_BILLING_MODE", "shadow").strip().lower()
    if mode not in _BILLING_MODES:
        raise ValueError(
            "DCLAW_BILLING_MODE must be one of off, shadow, observe, enforced",
        )
    return mode


def _non_negative_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return max(0, value)


def build_open_session_id(
    app_id: str,
    public_id: str,
    external_user_id: str,
    external_session_id: str | None,
) -> str:
    external_user = _safe_external_id(external_user_id, fallback="anonymous")
    external_session = _safe_external_id(
        external_session_id or "",
        fallback="default",
    )
    return f"open:{app_id}:{public_id}:{external_user}:{external_session}"


async def get_open_workspace(request: Request, agent_id: str) -> Any:
    app = getattr(request, "app", None)
    state = getattr(app, "state", None)
    manager = getattr(state, "multi_agent_manager", None)
    if manager is None:
        raise HTTPException(
            status_code=500,
            detail="Open API workspace manager is not configured",
        )
    return await manager.get_agent(
        agent_id,
        user_id=str(request.state.user_id),
    )


async def prepare_open_agent_chat(
    request: Request,
    publication: dict[str, Any],
    payload: OpenMessageRequest,
) -> PreparedOpenRun:
    return await _prepare_open_chat(
        request,
        publication,
        payload,
        agent_id=str(publication["target_id"]),
        expert_team_id=None,
    )


async def prepare_open_expert_team_chat(
    request: Request,
    publication: dict[str, Any],
    payload: OpenMessageRequest,
    *,
    leader_agent_id: str,
) -> PreparedOpenRun:
    return await _prepare_open_chat(
        request,
        publication,
        payload,
        agent_id=leader_agent_id,
        expert_team_id=str(publication["target_id"]),
    )


async def _prepare_open_chat(
    request: Request,
    publication: dict[str, Any],
    payload: OpenMessageRequest,
    *,
    agent_id: str,
    expert_team_id: str | None,
) -> PreparedOpenRun:
    user_id = str(request.state.user_id)
    app_id = str(request.state.open_app_id)
    public_id = str(publication["public_id"])
    session_id = build_open_session_id(
        app_id,
        public_id,
        payload.external_user_id,
        payload.external_session_id,
    )
    channel = f"open:{app_id}"
    workspace = await get_open_workspace(request, agent_id)
    console_channel = await workspace.channel_manager.get_channel("console")
    if console_channel is None:
        raise HTTPException(
            status_code=503,
            detail="Channel Console not found",
        )

    chat = await workspace.chat_manager.get_or_create_chat(
        session_id,
        user_id,
        channel,
        name=payload.message[:10] or "Open API",
    )
    native_meta: dict[str, Any] = {
        "session_id": session_id,
        "user_id": user_id,
        "external_user_id": payload.external_user_id,
        "external_session_id": payload.external_session_id or "default",
        "publication_id": str(publication["id"]),
        "public_id": public_id,
        "target_type": str(publication["target_type"]),
        "target_id": str(publication["target_id"]),
        "knowledge_base_id": str(
            publication.get("knowledge_base_id")
            or f"openapi-{publication['id']}",
        ),
        "metadata": dict(payload.metadata or {}),
    }
    if expert_team_id:
        native_meta["expert_team_id"] = expert_team_id
    native_payload = {
        "channel_id": channel,
        "sender_id": user_id,
        "content_parts": [
            TextContent(type=ContentType.TEXT, text=payload.message),
        ],
        "meta": native_meta,
    }

    return PreparedOpenRun(
        chat_id=str(chat.id),
        session_id=session_id,
        channel=channel,
        agent_id=agent_id,
        payload=native_payload,
        workspace=workspace,
        console_channel=console_channel,
    )


def _safe_external_id(value: str, *, fallback: str) -> str:
    normalized = _SAFE_ID_PATTERN.sub("_", value.strip())[
        :_MAX_EXTERNAL_ID_LENGTH
    ]
    normalized = normalized.strip("._:-")
    return normalized or fallback
