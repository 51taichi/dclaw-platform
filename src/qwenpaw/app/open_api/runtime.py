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
from uuid import uuid4

from agentscope_runtime.engine.schemas.agent_schemas import (
    ContentType,
    TextContent,
)
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select

from ..agent_context import (
    reset_current_billing_context,
    set_current_billing_context,
)
from ..billing.open_api import OpenApiBillingSession
from ..billing.open_api import OpenApiBillingCoordinator
from ..billing.execution import (
    OpenApiBillingExecutionContext,
    OpenApiExecutionFence,
)
from ..billing.model_meter import BillingModelMeter
from ..billing.pricing import PriceCatalogService
from ..billing.reporting import persisted_billing_mode
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

    def execution(
        self,
        invocation_id: str,
        fence: OpenApiExecutionFence,
        lease_seconds: float,
    ) -> "OpenApiBillingExecution":
        return OpenApiBillingExecution(
            self,
            invocation_id,
            fence,
            lease_seconds,
        )


class ExecutionLeaseLostError(RuntimeError):
    """The current worker no longer owns the invocation execution."""


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
        self._execution.renew_lease()
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

    def __init__(
        self,
        runtime: OpenApiBillingRuntime,
        invocation_id: str,
        fence: OpenApiExecutionFence,
        lease_seconds: float,
    ) -> None:
        self.runtime = runtime
        self.invocation_id = invocation_id
        self.fence = fence
        self.lease_seconds = lease_seconds
        self.lease_lost = False
        self.finalizing = False
        self.producer_task: asyncio.Task | None = None
        self.meter = _RequestBillingMeter(runtime, self)
        self._preflight_ready = asyncio.Event()
        self._initial_failure: InsufficientUsageCreditsError | None = None
        self.insufficient: InsufficientUsageCreditsError | None = None
        self.reservation_succeeded = False
        self._finalized = asyncio.Event()
        self.terminal_snapshot: dict[str, Any] | None = None

    def renew_lease(self) -> None:
        if (
            self.lease_lost
            or not self.runtime.open_api_repository.renew_invocation_execution(
                self.invocation_id,
                self.fence,
                lease_seconds=self.lease_seconds,
            )
        ):
            self.lease_lost = True
            raise ExecutionLeaseLostError(
                "Open API invocation execution lease was lost",
            )

    def note_lease_lost(self) -> None:
        self.lease_lost = True

    def begin_finalizing(self) -> None:
        """Hand lease ownership from heartbeat to the atomic finalizer."""
        self.finalizing = True

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

    def note_finalized(self, terminal: dict[str, Any]) -> None:
        self.finalizing = True
        self.terminal_snapshot = dict(terminal)
        self._finalized.set()

    async def wait_for_finalization(self) -> dict[str, Any]:
        await self._finalized.wait()
        assert self.terminal_snapshot is not None
        return dict(self.terminal_snapshot)


def create_open_api_billing_runtime() -> OpenApiBillingRuntime:
    """Build explicit billing services over the configured durable engine."""
    engine = get_app_engine()
    create_all(engine)
    repository = BillingRepository(engine)
    pricing = PriceCatalogService(PriceCatalogRepository(engine))
    mode = persisted_billing_mode(repository, fallback=_billing_mode())
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
    fence: OpenApiExecutionFence,
    meter: BillingModelMeter | None = None,
):
    """Scope a committed billing session to an OpenAPI execution path."""
    context = OpenApiBillingExecutionContext(session=session, fence=fence)
    token = set_current_billing_context(context)
    meter_token: Token[BillingModelMeter | None] = _current_billing_meter.set(
        meter,
    )
    try:
        yield context
    finally:
        _current_billing_meter.reset(meter_token)
        reset_current_billing_context(token)


def recover_open_api_billing(
    runtime: OpenApiBillingRuntime | None = None,
) -> int:
    # pylint: disable=too-many-branches,too-many-statements
    """Idempotently close incomplete OpenAPI invocation/order bridge pairs."""
    active = runtime or create_open_api_billing_runtime()
    engine = active.repository.engine
    with engine.connect() as conn:
        rows = (
            conn.execute(
                select(
                    billing_usage_orders.c.id.label("order_id"),
                    billing_usage_orders.c.wallet_id.label("wallet_id"),
                    billing_usage_orders.c.status.label("order_status"),
                    open_api_invocations.c.id.label("invocation_id"),
                    open_api_invocations.c.terminal_event_json.label(
                        "terminal_event_json",
                    ),
                )
                .join(
                    open_api_invocations,
                    open_api_invocations.c.billing_usage_order_id
                    == billing_usage_orders.c.id,
                )
                .where(
                    billing_usage_orders.c.source_type == "open_api",
                    open_api_invocations.c.billing_status != "unbilled",
                    or_(
                        billing_usage_orders.c.status.in_(
                            ("quoted", "held", "reconciling"),
                        ),
                        open_api_invocations.c.status.in_(
                            ("accepted", "running"),
                        ),
                        open_api_invocations.c.terminal_event_json.is_(None),
                    ),
                ),
            )
            .mappings()
            .all()
        )

    recovered = 0
    for row in rows:
        invocation_id = str(row["invocation_id"])
        invocation = active.open_api_repository.get_invocation(invocation_id)
        if invocation is None:
            continue
        terminal = invocation.get("terminal_event_json")
        if isinstance(terminal, dict):
            order_id = str(row["order_id"])
            order_before = active.usage_service.get_order(order_id)
            durable_items = active.usage_service.list_items(order_id)
            order_changed = False
            if durable_items and all(
                str(item.get("status")) != "held" for item in durable_items
            ):
                order_after = active.usage_service.reproject_open_api_order(
                    order_id,
                )
                order_changed = any(
                    order_before.get(key) != order_after.get(key)
                    for key in (
                        "status",
                        "captured_credits",
                        "released_credits",
                        "reconciling_credits",
                    )
                )
            state = _state_from_sealed_terminal(terminal)
            state_changed = (
                active.open_api_repository.repair_invocation_from_terminal(
                    invocation_id,
                    terminal_event=terminal,
                    status=state["status"],
                    status_code=state["status_code"],
                    error_summary=state["error_summary"],
                    billing_error_code=state["billing_error_code"],
                )
            )
            if state_changed or order_changed:
                recovered += 1
            continue

        owner_token = f"recovery:{uuid4().hex}"
        lease_seconds = _positive_float_env(
            "DCLAW_OPEN_API_EXECUTION_LEASE_SECONDS",
            30.0,
        )
        recovery_fence = (
            active.open_api_repository.takeover_invocation_execution(
                invocation_id,
                owner_token,
                lease_seconds=lease_seconds,
            )
        )
        if recovery_fence is None:
            continue

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
            if not active.open_api_repository.renew_invocation_execution(
                invocation_id,
                recovery_fence,
                lease_seconds=lease_seconds,
            ):
                break
            active.usage_service.settle_model_call(
                SettleModelCall(
                    usage_order_id=order_id,
                    item_key=str(item["item_key"]),
                    supplier_reference="",
                    billability="not_billable",
                    execution_outcome="failed",
                    evidence={
                        "adapter_version": "open-api-recovery-v1",
                        "response_class": "recovered_before_provider_contact",
                        "timestamp": datetime.now(timezone.utc).isoformat(
                            timespec="seconds",
                        ),
                    },
                    invocation_id=invocation_id,
                    execution_fence=recovery_fence,
                ),
            )

        items = active.usage_service.list_items(order_id)
        empty_order = not items
        if not empty_order:
            active.usage_service.reproject_open_api_order(order_id)

        order = active.usage_service.get_order(order_id)
        succeeded = sum(
            1
            for item in items
            if str(item.get("execution_outcome")) == "succeeded"
        )
        failed = sum(
            1
            for item in items
            if str(item.get("execution_outcome")) != "succeeded"
        )
        status = (
            "partially_completed"
            if succeeded and failed
            else "succeeded"
            if succeeded
            else "failed"
        )
        balance = active.repository.balance(str(row["wallet_id"]))
        durable_billing_status = (
            "settled" if empty_order else str(order["status"])
        )
        terminal_billing_status = durable_billing_status
        if durable_billing_status == "settled" and int(
            order["captured_credits"],
        ):
            terminal_billing_status = "captured"
        status_code = 200 if status == "succeeded" else 500
        error_summary = (
            ""
            if status == "succeeded"
            else "request interrupted by process restart"
        )
        code = "completed" if status == "succeeded" else "request_interrupted"
        terminal = {
            "type": "billing.completed",
            "invocation_id": invocation_id,
            "credits_used": int(order["captured_credits"]),
            "credits_remaining": balance.available,
            "billing_status": terminal_billing_status,
            "status": status,
            "http_status": status_code,
            "code": code,
            "message": error_summary or "request completed",
            "required_credits": None,
            "headers": {
                "X-DClaw-Invocation-Id": invocation_id,
                "X-DClaw-Billing-Status": terminal_billing_status,
            },
        }
        if empty_order:
            finalized = (
                active.open_api_repository.finalize_empty_invocation_execution(
                    invocation_id,
                    order_id,
                    recovery_fence,
                    status=status,
                    status_code=status_code,
                    error_summary=error_summary,
                    billing_error_code=(
                        None if status == "succeeded" else code
                    ),
                    terminal_event=terminal,
                )
            )
        else:
            finalized = (
                active.open_api_repository.finalize_invocation_execution(
                    invocation_id,
                    recovery_fence,
                    status=status,
                    status_code=status_code,
                    error_summary=error_summary,
                    billing_status=durable_billing_status,
                    billing_error_code=(
                        None if status == "succeeded" else code
                    ),
                    terminal_event=terminal,
                )
            )
        if finalized is not None:
            recovered += 1
    return recovered


def _state_from_sealed_terminal(terminal: dict[str, Any]) -> dict[str, Any]:
    status_code = int(terminal.get("http_status") or 200)
    status = str(terminal.get("status") or "").strip()
    if status not in {
        "succeeded",
        "partially_completed",
        "failed",
        "cancelled",
    }:
        status = "succeeded" if status_code < 400 else "failed"
    message = str(terminal.get("message") or "")
    code = str(terminal.get("code") or "").strip() or None
    return {
        "status": status,
        "status_code": status_code,
        "error_summary": "" if status == "succeeded" else message,
        "billing_error_code": None if status == "succeeded" else code,
    }


def _positive_float_env(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return value if value > 0 else default


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
