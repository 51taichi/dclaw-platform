# -*- coding: utf-8 -*-
"""Request-scoped identities for general model billing."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Iterator, Literal

from ..agent_context import (
    reset_current_billing_context,
    set_current_billing_context,
)
from ..storage.repos.billing_execution_repo import BillingExecutionFence


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


_current_billing_meter: ContextVar[Any | None] = ContextVar(
    "current_billing_meter",
    default=None,
)


def get_current_billing_meter() -> Any | None:
    """Return the request-owned meter used by model construction."""
    return _current_billing_meter.get()


def set_current_billing_meter(meter: Any | None) -> Token[Any | None]:
    """Install a request meter and return its reset token."""
    return _current_billing_meter.set(meter)


def reset_current_billing_meter(token: Token[Any | None]) -> None:
    """Restore the request meter represented by ``token``."""
    _current_billing_meter.reset(token)


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
    "billing_context",
    "get_current_billing_meter",
    "reset_current_billing_meter",
    "set_current_billing_meter",
]
