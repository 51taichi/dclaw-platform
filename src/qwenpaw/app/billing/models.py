# -*- coding: utf-8 -*-
"""Typed commands and results for credit ledger accounting."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping


class BillingError(RuntimeError):
    """Base class for rejected billing transactions."""


class DuplicateLedgerTransactionError(BillingError):
    """Raised when a ledger idempotency key has already been committed."""


class InsufficientCreditsError(BillingError):
    """Raised when a debit would make the available projection negative."""


class BillingInvariantError(BillingError):
    """Raised when a command conflicts with the wallet ledger state."""


@dataclass(frozen=True)
class WalletBalance:
    available: int
    held: int
    purchased: int
    promotional: int
    package: int
    debt: int = 0
    held_overdraft: int = 0

    @property
    def funded_available(self) -> int:
        """Return spendable funded credits before debt projections."""
        return self.available + self.debt + self.held_overdraft


@dataclass(frozen=True)
class LedgerTransaction:
    wallet_id: str
    event_type: str
    credits: int
    business_type: str
    business_key: str
    idempotency_key: str
    credit_type: str | None = None
    expires_at: datetime | None = None
    cash_delta_fen: int = 0
    actor_type: str = "system"
    actor_id: str | None = None
    reason: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)
