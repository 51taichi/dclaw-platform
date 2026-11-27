# -*- coding: utf-8 -*-
"""Audited state machine for fixed-product manual top-ups."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..storage.repos.billing_repo import BillingRepository
from ..storage.repos.top_up_repo import TopUpRepository
from .models import LedgerTransaction


class TopUpConflictError(RuntimeError):
    """A top-up transition conflicts with durable state or replay payload."""


@dataclass(frozen=True)
class SubmitClaimCommand:
    product_id: str
    payment_channel: str
    payer_reference: str
    customer_note: str | None
    idempotency_key: str


@dataclass(frozen=True)
class ReviewCommand:
    idempotency_key: str
    reason: str


def _hash(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TopUpService:
    """Coordinate claim state and wallet ledger effects atomically."""

    def __init__(
        self,
        top_up_repository: TopUpRepository,
        billing_repository: BillingRepository,
    ) -> None:
        if top_up_repository.engine is not billing_repository.engine:
            raise ValueError("top-up and billing repositories must share one engine")
        self.top_up_repository = top_up_repository
        self.billing_repository = billing_repository
        self.engine = top_up_repository.engine

    def submit_claim(
        self, owner_id: str, command: SubmitClaimCommand
    ) -> dict[str, Any]:
        if not command.idempotency_key.strip():
            raise ValueError("idempotency_key is required")
        wallet = self.billing_repository.get_wallet("user", owner_id)
        if wallet is None:
            raise KeyError(owner_id)
        with self.engine.begin() as conn:
            claim = self.top_up_repository.create_claim(
                owner_id=owner_id,
                wallet_id=str(wallet["id"]),
                product_public_id=command.product_id,
                payment_channel=command.payment_channel,
                payer_reference=command.payer_reference,
                customer_note=command.customer_note,
                idempotency_key=command.idempotency_key,
                conn=conn,
            )
            audit_key = f"submit:{command.idempotency_key}"
            if (
                self.top_up_repository.get_audit_by_idempotency_key(conn, audit_key)
                is None
            ):
                snapshot = claim["product_snapshot"]
                self.top_up_repository.append_audit(
                    conn,
                    {
                        "claim_id": claim["id"],
                        "action": "submitted",
                        "actor_id": owner_id,
                        "reason": "submitted",
                        "idempotency_key": audit_key,
                        "request_sha256": claim["submission_request_sha256"],
                        "payment_amount_fen": snapshot["payment_amount_fen"],
                        "purchased_credits": snapshot["purchased_credits"],
                        "promotional_credits": snapshot["promotional_credits"],
                        "claim_snapshot_json": json.dumps(snapshot),
                    },
                )
            return claim

    def approve_claim(
        self, public_id: str, actor_id: str, command: ReviewCommand
    ) -> dict[str, Any]:
        return self._review(public_id, actor_id, command, action="approved")

    def reject_claim(
        self, public_id: str, actor_id: str, command: ReviewCommand
    ) -> dict[str, Any]:
        return self._review(public_id, actor_id, command, action="rejected")

    def _review(  # pylint: disable=too-many-locals
        self,
        public_id: str,
        actor_id: str,
        command: ReviewCommand,
        *,
        action: str,
    ) -> dict[str, Any]:
        if not actor_id.strip() or not command.reason.strip():
            raise ValueError("actor and reason are required")
        digest = _hash(
            {"claim_id": public_id, "action": action, "reason": command.reason}
        )
        now = datetime.now(timezone.utc)
        with self.engine.begin() as conn:
            claim = self.top_up_repository.lock_pending_claim(conn, public_id)
            if claim is None:
                raise KeyError(public_id)
            existing_audit = self.top_up_repository.get_audit_by_idempotency_key(
                conn, command.idempotency_key
            )
            if claim["status"] != "pending":
                if (
                    existing_audit
                    and existing_audit["request_sha256"] == digest
                    and claim["status"] == action
                ):
                    return claim
                raise TopUpConflictError(public_id)
            if existing_audit is not None:
                raise TopUpConflictError(command.idempotency_key)

            snapshot = claim["product_snapshot"]
            self.top_up_repository.append_audit(
                conn,
                {
                    "claim_id": claim["id"],
                    "action": action,
                    "actor_id": actor_id,
                    "reason": command.reason,
                    "idempotency_key": command.idempotency_key,
                    "request_sha256": digest,
                    "payment_amount_fen": snapshot["payment_amount_fen"],
                    "purchased_credits": snapshot["purchased_credits"],
                    "promotional_credits": snapshot["promotional_credits"],
                    "claim_snapshot_json": json.dumps(snapshot),
                },
            )
            business_key = f"top-up:{claim['public_id']}"
            if action == "approved":
                self._grant_snapshot(
                    conn,
                    claim,
                    snapshot,
                    actor_id,
                    command.reason,
                    business_key,
                    now,
                )
            return self.top_up_repository.transition_claim(
                conn,
                public_id,
                status=action,
                reviewed_by=actor_id,
                review_reason=command.reason,
                reviewed_at=now,
                ledger_business_key=business_key if action == "approved" else None,
            )

    def _grant_snapshot(  # pylint: disable=too-many-arguments
        self,
        conn,
        claim: dict[str, Any],
        snapshot: dict[str, Any],
        actor_id: str,
        reason: str,
        business_key: str,
        now: datetime,
    ) -> None:
        self.billing_repository.append_transaction_in_connection(
            conn,
            LedgerTransaction(
                wallet_id=claim["wallet_id"],
                event_type="purchase_grant",
                credits=int(snapshot["purchased_credits"]),
                business_type="manual_top_up",
                business_key=business_key,
                idempotency_key=f"{business_key}:purchased",
                credit_type="purchased",
                expires_at=None,
                cash_delta_fen=int(snapshot["payment_amount_fen"]),
                actor_type="admin",
                actor_id=actor_id,
                reason=reason,
            ),
        )
        promotional = int(snapshot["promotional_credits"])
        if promotional <= 0:
            return
        expiry_days = int(snapshot["promotional_expiry_days"])
        self.billing_repository.append_transaction_in_connection(
            conn,
            LedgerTransaction(
                wallet_id=claim["wallet_id"],
                event_type="promotion_grant",
                credits=promotional,
                business_type="manual_top_up",
                business_key=business_key,
                idempotency_key=f"{business_key}:promotional",
                credit_type="promotional",
                expires_at=now + timedelta(days=expiry_days),
                actor_type="admin",
                actor_id=actor_id,
                reason=reason,
            ),
        )
