# -*- coding: utf-8 -*-
"""Personal-wallet service and verified-mobile signup trial boundary."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .models import (
    DuplicateLedgerTransactionError,
    LedgerTransaction,
    WalletBalance,
)
from .policies import (
    SIGNUP_TRIAL_CREDITS,
    signup_trial_expires_at,
    signup_trial_idempotency_key,
    signup_trial_metadata,
)
from ..storage.engine import get_app_engine
from ..storage.repos.billing_repo import BillingRepository
from ..storage.schema import create_all


@dataclass(frozen=True)
class GrantResult:
    """Outcome of an idempotent signup-trial grant request."""

    granted: bool
    balance: WalletBalance


class WalletService:
    """Operations for one user's personal credit wallet."""

    def __init__(self, repository: BillingRepository) -> None:
        self._repository = repository

    def get_or_create_personal_wallet(self, user_id: int) -> WalletBalance:
        """Return an existing user's personal wallet, creating an empty one."""
        wallet = self._repository.ensure_wallet("user", str(user_id))
        return self._repository.balance(wallet["id"])

    def grant_signup_trial(
        self,
        user_id: int,
        verified_mobile: str,
        risk_key: str,
    ) -> GrantResult:
        """Grant the verified-mobile trial once for a durable risk identity.

        The caller is responsible for establishing verified_mobile through a
        trusted verification flow. A blank value is never treated as verified.
        """
        wallet = self._repository.ensure_wallet("user", str(user_id))
        if not verified_mobile.strip():
            return GrantResult(
                granted=False,
                balance=self._repository.balance(wallet["id"]),
            )

        idempotency_key = signup_trial_idempotency_key(risk_key)
        command = LedgerTransaction(
            wallet_id=wallet["id"],
            event_type="promotion_grant",
            credits=SIGNUP_TRIAL_CREDITS,
            business_type="signup_trial",
            business_key=idempotency_key,
            idempotency_key=idempotency_key,
            credit_type="promotional",
            expires_at=signup_trial_expires_at(datetime.now(timezone.utc)),
            actor_type="system",
            actor_id=str(user_id),
            reason="verified_mobile_signup_trial",
            metadata=signup_trial_metadata(),
        )
        try:
            balance = self._repository.append_transaction(command)
        except DuplicateLedgerTransactionError:
            balance = self._repository.balance(wallet["id"])
            return GrantResult(granted=False, balance=balance)
        return GrantResult(granted=True, balance=balance)


def get_wallet_service() -> WalletService:
    """Build the default service after ensuring durable tables exist."""
    engine = get_app_engine()
    create_all(engine)
    return WalletService(BillingRepository(engine))
