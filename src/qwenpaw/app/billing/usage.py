# -*- coding: utf-8 -*-
"""Durable usage-order state machine for shadow and enforced billing."""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, OperationalError

from .models import (
    BillingInvariantError,
    DuplicateLedgerTransactionError,
    InsufficientCreditsError,
    LedgerTransaction,
    WalletBalance,
)
from .pricing import PriceCatalogService, QuoteRequest, RetailQuote
from ..storage.repos.billing_repo import BillingRepository
from ..storage.schema import (
    billing_price_catalogs,
    billing_usage_orders,
)


BillingMode = Literal["off", "shadow", "enforced"]
Billability = Literal["unknown", "billable", "not_billable"]
_BILLING_MODES = frozenset({"off", "shadow", "enforced"})
_BILLABILITY_VALUES = frozenset({"unknown", "billable", "not_billable"})


class UsageOrderError(RuntimeError):
    """Base class for rejected usage-order operations."""


class UsageOrderNotFoundError(UsageOrderError):
    """Raised when a usage order does not exist."""


class UsageOrderConflictError(UsageOrderError):
    """Raised when a business key belongs to a different wallet."""


class IdempotencyConflictError(UsageOrderConflictError):
    """Raised when one client key is replayed with a different request."""


class UsageOrderStateError(UsageOrderError):
    """Raised when an order cannot make the requested state transition."""


class InsufficientUsageCreditsError(InsufficientCreditsError):
    """Insufficient-wallet detail suitable for an API response."""

    def __init__(self, required: int, available: int) -> None:
        self.required = required
        self.available = available
        super().__init__(
            f"wallet has {available} available credits; {required} required",
        )


class UsageService:
    """Create price-locked orders and apply mode-aware settlement states."""

    def __init__(
        self,
        repository: BillingRepository,
        pricing: PriceCatalogService,
        *,
        mode: str | None = None,
    ) -> None:
        self.repository = repository
        self.pricing = pricing
        self.mode = _billing_mode(mode)

    def create_quote(
        self,
        owner_id: str,
        request: QuoteRequest,
        *,
        business_key: str,
    ) -> dict[str, Any]:
        """Lock one published retail quote for an authenticated owner."""
        normalized_owner = str(owner_id).strip()
        normalized_key = business_key.strip()
        if not normalized_owner or not normalized_key:
            raise ValueError("owner and business key must be non-empty")

        if self.mode == "off":
            quote = self.pricing.quote(request)
            return _off_order(normalized_key, quote)

        wallet = self.repository.ensure_wallet("user", normalized_owner)
        stored_key = _stored_business_key(str(wallet["id"]), normalized_key)
        existing = self._find_existing_order(
            str(wallet["id"]),
            stored_key,
            normalized_key,
        )
        if existing is not None:
            self._assert_replay_matches(existing, request)
            return self._decode_order(existing)

        quote = self.pricing.quote(request)
        catalog_id = self._catalog_id(quote.catalog_version)
        order_id = str(uuid4())
        now = datetime.now(timezone.utc)
        values = {
            "id": order_id,
            "wallet_id": wallet["id"],
            "catalog_id": catalog_id,
            "price_rule_id": quote.rule_id,
            "business_key": stored_key,
            "status": "quoted",
            "provider_id": request.provider_id,
            "model_key": request.model_key,
            "capability": request.capability,
            "quoted_credits": quote.credits,
            "held_credits": 0,
            "captured_credits": 0,
            "billability": "unknown",
            "request_snapshot_json": _dump_json(
                {
                    **request.to_jsonable(),
                    "billing_mode": self.mode,
                    "client_business_key": normalized_key,
                },
            ),
            "price_snapshot_json": _dump_json(quote.to_jsonable()),
            "created_at": now,
            "updated_at": now,
        }
        try:
            with self.repository.engine.begin() as conn:
                conn.execute(insert(billing_usage_orders).values(**values))
        except IntegrityError as exc:
            existing = self._find_by_business_key(stored_key)
            if existing is None:
                raise
            if existing["wallet_id"] != wallet["id"]:
                raise UsageOrderConflictError(normalized_key) from exc
            self._assert_replay_matches(existing, request)
            return self._decode_order(existing)
        return self.get_order(order_id)

    def hold(self, order_id: str) -> dict[str, Any]:
        """Reserve the locked quote, or record only a shadow reservation."""
        for attempt in range(3):
            try:
                return self._hold_once(order_id)
            except (
                IntegrityError,
                OperationalError,
            ) as exc:
                current = self.get_order(order_id)
                if current["status"] == "held":
                    return current
                if current["status"] != "quoted" or attempt == 2:
                    raise UsageOrderStateError(
                        "concurrent hold did not reach a replayable state",
                    ) from exc
        raise AssertionError("unreachable")

    def _hold_once(self, order_id: str) -> dict[str, Any]:
        wallet_id = ""
        quote_credits = 0
        try:
            with self.repository.engine.begin() as conn:
                order = self._order_row(order_id, conn=conn, for_update=True)
                if order["status"] == "held":
                    return self._decode_order(order)
                if order["status"] != "quoted":
                    raise UsageOrderStateError(
                        f"cannot hold order in state {order['status']}",
                    )
                wallet_id = str(order["wallet_id"])
                quote_credits = int(order["quoted_credits"])
                if self._order_mode(order) == "enforced" and quote_credits:
                    request_snapshot = json.loads(
                        order["request_snapshot_json"] or "{}",
                    )
                    self.repository.append_transaction_in_connection(
                        conn,
                        LedgerTransaction(
                            wallet_id=wallet_id,
                            event_type="usage_hold",
                            credits=quote_credits,
                            business_type="usage",
                            business_key=str(order["business_key"]),
                            idempotency_key=f"usage:{order_id}:hold",
                            metadata={
                                "capability": str(order["capability"]),
                                "tier": str(
                                    request_snapshot.get("parameters", {}).get(
                                        "tier",
                                        "standard",
                                    ),
                                ),
                            },
                        ),
                    )
                self._transition(
                    order_id,
                    from_states=("quoted",),
                    status="held",
                    conn=conn,
                    held_credits=quote_credits,
                )
        except InsufficientCreditsError as exc:
            balance = self.repository.balance(wallet_id)
            raise InsufficientUsageCreditsError(
                quote_credits,
                balance.available,
            ) from exc
        return self.get_order(order_id)

    def settle_supplier(
        self,
        order_id: str,
        *,
        supplier_reference: str,
        evidence: Mapping[str, Any],
        billability: Billability,
        actual_credits: int | None = None,
    ) -> dict[str, Any]:
        """Settle only from durable supplier billability evidence."""
        normalized_reference = supplier_reference.strip()
        if not normalized_reference:
            raise ValueError("supplier reference must be non-empty")
        if billability not in _BILLABILITY_VALUES:
            raise ValueError("unsupported supplier billability")
        stable_evidence = json.loads(_dump_json(dict(evidence)))
        if billability == "billable":
            if actual_credits is None or actual_credits <= 0:
                raise ValueError(
                    "billable settlement requires positive actual credits",
                )
        elif actual_credits is not None:
            raise ValueError(
                "only billable settlement accepts actual credits",
            )

        for attempt in range(3):
            try:
                return self._settle_supplier_once(
                    order_id,
                    supplier_reference=normalized_reference,
                    evidence=stable_evidence,
                    billability=billability,
                    actual_credits=actual_credits,
                )
            except (
                BillingInvariantError,
                DuplicateLedgerTransactionError,
                IntegrityError,
                OperationalError,
            ) as exc:
                current = self.get_order(order_id)
                if current["status"] in {"captured", "released"}:
                    return self._settlement_replay(
                        current,
                        supplier_reference=normalized_reference,
                        evidence=stable_evidence,
                        billability=billability,
                        actual_credits=actual_credits,
                    )
                if attempt == 2:
                    raise UsageOrderStateError(
                        "concurrent settlement did not reach a stable state",
                    ) from exc
        raise AssertionError("unreachable")

    def _settle_supplier_once(
        self,
        order_id: str,
        *,
        supplier_reference: str,
        evidence: Mapping[str, Any],
        billability: Billability,
        actual_credits: int | None,
    ) -> dict[str, Any]:
        with self.repository.engine.begin() as conn:
            order = self._order_row(order_id, conn=conn, for_update=True)
            decoded = self._decode_order(order)
            if order["status"] in {"captured", "released"}:
                return self._settlement_replay(
                    decoded,
                    supplier_reference=supplier_reference,
                    evidence=evidence,
                    billability=billability,
                    actual_credits=actual_credits,
                )
            allowed = ("held", "reconciling")
            if order["status"] not in allowed:
                raise UsageOrderStateError(
                    f"cannot settle order in state {order['status']}",
                )

            common_values = {
                "supplier_reference": supplier_reference,
                "supplier_evidence_json": _dump_json(evidence),
                "billability": billability,
            }
            if billability == "unknown":
                self._transition(
                    order_id,
                    from_states=allowed,
                    status="reconciling",
                    conn=conn,
                    **common_values,
                )
                return self._decode_order(
                    self._order_row(order_id, conn=conn),
                )

            held_credits = int(order["held_credits"])
            if billability == "billable":
                assert actual_credits is not None
                if actual_credits > held_credits:
                    raise ValueError(
                        "actual credits cannot exceed the held quote",
                    )
                if self._order_mode(order) == "enforced":
                    self.repository.append_transaction_in_connection(
                        conn,
                        LedgerTransaction(
                            wallet_id=str(order["wallet_id"]),
                            event_type="usage_capture",
                            credits=actual_credits,
                            business_type="usage",
                            business_key=str(order["business_key"]),
                            idempotency_key=f"usage:{order_id}:capture",
                            metadata={
                                "supplier_reference": supplier_reference,
                                "billability": billability,
                            },
                        ),
                    )
                self._transition(
                    order_id,
                    from_states=allowed,
                    status="captured",
                    conn=conn,
                    held_credits=0,
                    captured_credits=actual_credits,
                    settled_at=datetime.now(timezone.utc),
                    **common_values,
                )
            else:
                if self._order_mode(order) == "enforced" and held_credits:
                    self.repository.append_transaction_in_connection(
                        conn,
                        LedgerTransaction(
                            wallet_id=str(order["wallet_id"]),
                            event_type="usage_release",
                            credits=0,
                            business_type="usage",
                            business_key=str(order["business_key"]),
                            idempotency_key=f"usage:{order_id}:release",
                            metadata={
                                "supplier_reference": supplier_reference,
                                "billability": billability,
                            },
                        ),
                    )
                self._transition(
                    order_id,
                    from_states=allowed,
                    status="released",
                    conn=conn,
                    held_credits=0,
                    settled_at=datetime.now(timezone.utc),
                    **common_values,
                )
            return self._decode_order(
                self._order_row(order_id, conn=conn),
            )

    @staticmethod
    def _settlement_replay(
        current: dict[str, Any],
        *,
        supplier_reference: str,
        evidence: Mapping[str, Any],
        billability: Billability,
        actual_credits: int | None,
    ) -> dict[str, Any]:
        expected_status = (
            "captured" if billability == "billable" else "released"
        )
        expected_credits = actual_credits if actual_credits is not None else 0
        matches_evidence = all(
            (
                current["status"] == expected_status,
                current["supplier_reference"] == supplier_reference,
                current["supplier_evidence"] == evidence,
                current["billability"] == billability,
            ),
        )
        matches_credits = (
            billability != "billable"
            or current["captured_credits"] == expected_credits
        )
        if not matches_evidence or not matches_credits:
            raise UsageOrderStateError(
                "usage order was settled by a different supplier outcome",
            )
        return current

    def get_order(self, order_id: str) -> dict[str, Any]:
        return self._decode_order(self._order_row(order_id))

    def _order_row(
        self,
        order_id: str,
        *,
        conn: Connection | None = None,
        for_update: bool = False,
    ) -> dict[str, Any]:
        statement = select(billing_usage_orders).where(
            billing_usage_orders.c.id == order_id,
        )
        if for_update:
            statement = statement.with_for_update()
        if conn is None:
            with self.repository.engine.connect() as local_conn:
                row = local_conn.execute(statement).mappings().first()
        else:
            row = conn.execute(statement).mappings().first()
        if row is None:
            raise UsageOrderNotFoundError(order_id)
        return dict(row)

    def _find_by_business_key(
        self,
        business_key: str,
    ) -> dict[str, Any] | None:
        with self.repository.engine.connect() as conn:
            row = (
                conn.execute(
                    select(billing_usage_orders).where(
                        billing_usage_orders.c.business_key == business_key,
                    ),
                )
                .mappings()
                .first()
            )
        return dict(row) if row is not None else None

    def _find_existing_order(
        self,
        wallet_id: str,
        stored_key: str,
        client_key: str,
    ) -> dict[str, Any] | None:
        existing = self._find_by_business_key(stored_key)
        if existing is not None:
            if str(existing["wallet_id"]) != wallet_id:
                raise UsageOrderConflictError(client_key)
            return existing
        # Compatibility for Task 5 orders created before keys were
        # namespaced. The wallet predicate prevents another owner's legacy
        # raw key from blocking this owner.
        with self.repository.engine.connect() as conn:
            legacy = (
                conn.execute(
                    select(billing_usage_orders).where(
                        billing_usage_orders.c.business_key == client_key,
                        billing_usage_orders.c.wallet_id == wallet_id,
                    ),
                )
                .mappings()
                .first()
            )
        return dict(legacy) if legacy is not None else None

    @staticmethod
    def _assert_replay_matches(
        order: dict[str, Any],
        request: QuoteRequest,
    ) -> None:
        stored = json.loads(order["request_snapshot_json"] or "{}")
        canonical_stored = {
            key: stored.get(key)
            for key in (
                "provider_id",
                "model_key",
                "capability",
                "parameters",
                "input_tokens",
                "output_tokens",
            )
        }
        if _canonical_json(canonical_stored) != _canonical_json(
            request.to_jsonable(),
        ):
            raise IdempotencyConflictError(
                "idempotency key is already bound to another quote request",
            )

    def _catalog_id(self, version: str) -> str:
        with self.repository.engine.connect() as conn:
            catalog_id = conn.scalar(
                select(billing_price_catalogs.c.id).where(
                    billing_price_catalogs.c.version == version,
                    billing_price_catalogs.c.status == "published",
                ),
            )
        if catalog_id is None:
            raise UsageOrderError(
                f"published catalog disappeared while quoting: {version}",
            )
        return str(catalog_id)

    def _transition(
        self,
        order_id: str,
        *,
        from_states: tuple[str, ...],
        status: str,
        conn: Connection | None = None,
        **values: Any,
    ) -> None:
        statement = (
            update(billing_usage_orders)
            .where(
                billing_usage_orders.c.id == order_id,
                billing_usage_orders.c.status.in_(from_states),
            )
            .values(
                status=status,
                updated_at=datetime.now(timezone.utc),
                **values,
            )
        )
        if conn is None:
            with self.repository.engine.begin() as local_conn:
                changed = local_conn.execute(statement)
        else:
            changed = conn.execute(statement)
        if changed.rowcount != 1:
            current = self._order_row(order_id)
            if current["status"] != status:
                raise UsageOrderStateError(
                    f"order changed during transition to {status}",
                )

    @staticmethod
    def _decode_order(order: dict[str, Any]) -> dict[str, Any]:
        request_snapshot = json.loads(order["request_snapshot_json"] or "{}")
        price_snapshot = json.loads(order["price_snapshot_json"] or "{}")
        supplier_evidence = json.loads(
            order["supplier_evidence_json"] or "{}",
        )
        client_business_key = request_snapshot.pop(
            "client_business_key",
            str(order["business_key"]),
        )
        return {
            "id": str(order["id"]),
            "business_key": client_business_key,
            "status": str(order["status"]),
            "billing_mode": request_snapshot.pop("billing_mode", "shadow"),
            "quoted_credits": int(order["quoted_credits"]),
            "held_credits": int(order["held_credits"]),
            "captured_credits": int(order["captured_credits"]),
            "supplier_reference": order["supplier_reference"],
            "supplier_evidence": supplier_evidence,
            "billability": str(order["billability"] or "unknown"),
            "request": request_snapshot,
            "quote": price_snapshot,
        }

    @staticmethod
    def _order_mode(order: dict[str, Any]) -> BillingMode:
        request_snapshot = json.loads(order["request_snapshot_json"] or "{}")
        return _billing_mode(request_snapshot.get("billing_mode", "shadow"))


def _billing_mode(mode: str | None) -> BillingMode:
    value = (
        mode
        if mode is not None
        else os.environ.get("DCLAW_BILLING_MODE", "shadow")
    )
    normalized = value.strip().lower()
    if normalized not in _BILLING_MODES:
        raise ValueError(
            "DCLAW_BILLING_MODE must be one of off, shadow, enforced",
        )
    return normalized  # type: ignore[return-value]


def _off_order(business_key: str, quote: RetailQuote) -> dict[str, Any]:
    return {
        "id": None,
        "business_key": business_key,
        "status": "off",
        "billing_mode": "off",
        "quoted_credits": quote.credits,
        "held_credits": 0,
        "captured_credits": 0,
        "supplier_reference": None,
        "supplier_evidence": {},
        "billability": "unknown",
        "request": quote.request.to_jsonable(),
        "quote": quote.to_jsonable(),
    }


def wallet_balance_dict(balance: WalletBalance) -> dict[str, int]:
    """Serialize the public wallet projection without exposing an ID."""
    return {
        "available": balance.available,
        "held": balance.held,
        "purchased": balance.purchased,
        "promotional": balance.promotional,
        "package": balance.package,
    }


def _dump_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _canonical_json(value: Any) -> str:
    return _dump_json(value)


def _stored_business_key(wallet_id: str, client_key: str) -> str:
    digest = sha256(client_key.encode("utf-8")).hexdigest()
    return f"user-wallet:{wallet_id}:{digest}"
