# -*- coding: utf-8 -*-
"""Request-scoped identities for general model billing."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Iterator, Literal
from uuid import uuid4

from ..agent_context import (
    reset_current_billing_context,
    set_current_billing_context,
)
from ..storage.repos.billing_execution_repo import BillingExecutionFence
from ..storage.repos.billing_execution_repo import (
    BillingExecutionCommand,
    BillingExecutionRepository,
)


BillingMode = Literal["enforced"]


@dataclass(frozen=True)
class BillingSource:
    """Safe business identity for one user-triggered execution."""

    type: str
    id: str
    expert_id: str | None = None
    expert_team_run_id: str | None = None


@dataclass(frozen=True)
class BillingSession:
    """Immutable wallet and catalog selection for one execution."""

    execution_id: str
    usage_order_id: str
    wallet_id: str
    payer_user_id: str
    catalog_version: str
    source: BillingSource
    mode: BillingMode = "enforced"


@dataclass(frozen=True)
class BillingExecutionContext:
    """A committed session combined with its current execution owner."""

    session: BillingSession
    fence: BillingExecutionFence


@dataclass(frozen=True)
class SystemBillingExemption:
    """A durable, explicitly allowlisted non-user model operation."""

    execution_id: str
    actor: str
    reason: str


_current_billing_meter: ContextVar[Any | None] = ContextVar(
    "current_billing_meter",
    default=None,
)
_billing_required: ContextVar[bool] = ContextVar(
    "billing_required",
    default=False,
)
_billing_item_prefix: ContextVar[str | None] = ContextVar(
    "billing_item_prefix",
    default=None,
)

_SYSTEM_EXEMPTION_REASONS = frozenset({"model_catalog_validation"})


def get_current_billing_meter() -> Any | None:
    """Return the request-owned meter used by model construction."""
    return _current_billing_meter.get()


def set_current_billing_meter(meter: Any | None) -> Token[Any | None]:
    """Install a request meter and return its reset token."""
    return _current_billing_meter.set(meter)


def reset_current_billing_meter(token: Token[Any | None]) -> None:
    """Restore the request meter represented by ``token``."""
    _current_billing_meter.reset(token)


def is_billing_required() -> bool:
    """Return whether the active entry point represents a user operation."""
    return _billing_required.get()


@contextmanager
def billing_required() -> Iterator[None]:
    """Mark a user-originated call chain as requiring durable billing."""
    token = _billing_required.set(True)
    try:
        yield
    finally:
        _billing_required.reset(token)


def get_billing_item_prefix() -> str | None:
    """Return the durable item-key prefix selected by an orchestrator."""
    return _billing_item_prefix.get()


@contextmanager
def billing_item_prefix(prefix: str) -> Iterator[None]:
    """Install a stable per-stage prefix for actual model calls."""
    normalized = str(prefix).strip()
    if not normalized:
        raise ValueError("billing item prefix is required")
    token = _billing_item_prefix.set(normalized)
    try:
        yield
    finally:
        _billing_item_prefix.reset(token)


@contextmanager
def system_billing_exemption(
    repository: BillingExecutionRepository,
    *,
    actor: str,
    reason: str,
) -> Iterator[SystemBillingExemption]:
    """Audit an allowlisted system operation before installing its context."""
    normalized_actor = str(actor).strip()
    normalized_reason = str(reason).strip()
    if not normalized_actor:
        raise ValueError("system billing exemption actor is required")
    if normalized_reason not in _SYSTEM_EXEMPTION_REASONS:
        raise ValueError("system billing exemption reason is not allowlisted")
    execution_id = str(uuid4())
    request_hash = sha256(
        f"{normalized_actor}\0{normalized_reason}\0{execution_id}".encode(),
    ).hexdigest()
    repository.create_or_replay(
        BillingExecutionCommand(
            execution_id=execution_id,
            usage_order_id=None,
            payer_user_id=None,
            source_type="system_exemption",
            source_id=normalized_actor,
            request_sha256=request_hash,
            exemption_actor=normalized_actor,
            exemption_reason=normalized_reason,
        ),
    )
    fence = repository.claim(
        execution_id,
        f"system-exemption:{execution_id}",
        lease_seconds=60,
    )
    if fence is None or not repository.finalize(
        execution_id,
        fence,
        state="succeeded",
        error_code=None,
    ):
        raise RuntimeError("system billing exemption audit could not finalize")
    exemption = SystemBillingExemption(
        execution_id=execution_id,
        actor=normalized_actor,
        reason=normalized_reason,
    )
    token = set_current_billing_context(exemption)
    try:
        yield exemption
    finally:
        reset_current_billing_context(token)


@contextmanager
def billing_context(
    session: BillingSession,
    fence: BillingExecutionFence,
    meter: Any | None = None,
) -> Iterator[BillingExecutionContext]:
    """Install and reliably restore one general billing execution."""
    context = BillingExecutionContext(session=session, fence=fence)
    context_token = set_current_billing_context(context)
    meter_token = set_current_billing_meter(meter)
    try:
        yield context
    finally:
        reset_current_billing_meter(meter_token)
        reset_current_billing_context(context_token)


__all__ = [
    "BillingExecutionContext",
    "BillingSession",
    "BillingSource",
    "SystemBillingExemption",
    "billing_context",
    "billing_item_prefix",
    "billing_required",
    "get_current_billing_meter",
    "get_billing_item_prefix",
    "is_billing_required",
    "reset_current_billing_meter",
    "set_current_billing_meter",
    "system_billing_exemption",
]
