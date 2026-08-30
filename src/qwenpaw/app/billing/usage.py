# -*- coding: utf-8 -*-
"""Durable usage-order state machine for shadow and enforced billing."""
from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, OperationalError

from ..storage.repos.billing_repo import BillingRepository
from ..storage.schema import (
    billing_executions,
    billing_price_catalogs,
    billing_usage_items,
    billing_usage_orders,
    open_api_invocations,
)
from .complimentary import COMPLIMENTARY_UNPRICED_CATALOG_VERSION
from .execution import OpenApiExecutionFence
from .models import (
    BillingInvariantError,
    DuplicateLedgerTransactionError,
    InsufficientCreditsError,
    LedgerTransaction,
    WalletBalance,
)
from .pricing import PriceCatalogService, QuoteRequest, RetailQuote

BillingMode = Literal["off", "shadow", "observe", "enforced"]
Billability = Literal["unknown", "billable", "not_billable"]
ExecutionOutcome = Literal["pending", "succeeded", "failed"]
_BILLING_MODES = frozenset({"off", "shadow", "observe", "enforced"})
_BILLABILITY_VALUES = frozenset({"unknown", "billable", "not_billable"})
_EXECUTION_OUTCOMES = frozenset({"pending", "succeeded", "failed"})


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


class BillingExecutionFencedError(UsageOrderError):
    """The invocation execution claim is missing, stale, or expired."""


@dataclass(frozen=True)
class UsageExecutionGuard:
    """Discriminated durable owner used by reserve and settlement."""

    kind: Literal["open_api", "general"]
    execution_id: str
    owner_token: str
    generation: int


@dataclass(frozen=True)
class ReserveModelCall:
    """Trusted reservation request for one call inside an OpenAPI order."""

    usage_order_id: str
    item_key: str
    provider_id: str
    model_key: str
    capability: str
    parameters: Mapping[str, Any]
    input_tokens: int = 0
    max_output_tokens: int = 0
    invocation_id: str = ""
    execution_fence: OpenApiExecutionFence | None = None
    execution_guard: UsageExecutionGuard | None = None


@dataclass(frozen=True)
class SettleModelCall:
    """Supplier-evidenced terminal outcome for one reserved model call."""

    usage_order_id: str
    item_key: str
    supplier_reference: str
    billability: Billability
    evidence: Mapping[str, Any]
    execution_outcome: ExecutionOutcome = "succeeded"
    actual_input_tokens: int = 0
    actual_output_tokens: int = 0
    invocation_id: str = ""
    execution_fence: OpenApiExecutionFence | None = None
    execution_guard: UsageExecutionGuard | None = None


@dataclass(frozen=True)
class ReservedUsageItem:
    usage_order_id: str
    item_key: str
    quoted_credits: int
    status: str


@dataclass(frozen=True)
class UsageItemResult:
    usage_order_id: str
    item_key: str
    status: str
    quoted_credits: int
    captured_credits: int
    released_credits: int
    reconciling_credits: int


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
            "price_rule_id": quote.storage_rule_id or quote.rule_id,
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
                    price_snapshot = json.loads(
                        order["price_snapshot_json"] or "{}",
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
                                "tier": _economic_tier(price_snapshot),
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

    def reserve_model_call(
        self,
        command: ReserveModelCall,
    ) -> ReservedUsageItem:
        """Atomically hold the locked retail quote before supplier contact."""
        normalized = _normalize_reserve_model_call(command)
        for attempt in range(3):
            try:
                return self._reserve_model_call_once(normalized)
            except (
                BillingInvariantError,
                DuplicateLedgerTransactionError,
                IntegrityError,
                OperationalError,
            ) as exc:
                with self.repository.engine.connect() as conn:
                    existing = self._item_row(
                        conn,
                        normalized.usage_order_id,
                        normalized.item_key,
                    )
                if existing is not None:
                    self._assert_reservation_replay(existing, normalized)
                    return _reserved_item(existing)
                if attempt == 2:
                    raise UsageOrderStateError(
                        "concurrent model reservation did not become "
                        "replayable",
                    ) from exc
        raise AssertionError("unreachable")

    def _reserve_model_call_once(
        self,
        normalized: ReserveModelCall,
    ) -> ReservedUsageItem:
        with self.repository.engine.begin() as conn:
            order = self._order_row(
                normalized.usage_order_id,
                conn=conn,
                for_update=True,
            )
            self._validate_execution_fence(conn, order, normalized)
            existing = self._item_row(
                conn,
                normalized.usage_order_id,
                normalized.item_key,
                for_update=True,
            )
            if existing is not None:
                self._assert_reservation_replay(existing, normalized)
                return _reserved_item(existing)

            request = QuoteRequest(
                provider_id=normalized.provider_id,
                model_key=normalized.model_key,
                capability=normalized.capability,
                parameters=normalized.parameters,
                input_tokens=normalized.input_tokens,
                output_tokens=normalized.max_output_tokens,
            )
            quote = self._quote_for_order(order, request)
            economic_tier = _economic_tier(quote.snapshot)
            budget = int(order["budget_credits"])
            budget_blocked = bool(
                budget
                and int(order["captured_credits"])
                + int(order["held_credits"])
                + quote.credits
                > budget,
            )
            mode = self._order_mode(order)
            if budget_blocked and mode == "enforced":
                raise InsufficientUsageCreditsError(
                    quote.credits,
                    max(
                        budget
                        - int(order["captured_credits"])
                        - int(order["held_credits"]),
                        0,
                    ),
                )

            source_type = str(order.get("source_type") or "")
            item_business_key = _item_business_key(
                source_type,
                normalized.usage_order_id,
                normalized.item_key,
            )
            idempotency_namespace = _item_idempotency_namespace(source_type)
            would_pass: bool | None = None
            would_block_reason: str | None = None
            if mode == "observe":
                if budget_blocked:
                    would_pass = False
                    would_block_reason = "invocation_budget_exceeded"
                else:
                    (
                        would_pass,
                        would_block_reason,
                    ) = self.repository.evaluate_hold_in_connection(
                        conn,
                        str(order["wallet_id"]),
                        quote.credits,
                        capability=normalized.capability,
                        tier=economic_tier,
                    )
            if mode == "enforced" and quote.credits:
                try:
                    self.repository.append_transaction_in_connection(
                        conn,
                        LedgerTransaction(
                            wallet_id=str(order["wallet_id"]),
                            event_type="usage_hold",
                            credits=quote.credits,
                            business_type="usage_item",
                            business_key=item_business_key,
                            idempotency_key=(
                                f"{idempotency_namespace}:"
                                f"{normalized.usage_order_id}:"
                                f"{normalized.item_key}:hold"
                            ),
                            metadata={
                                "capability": normalized.capability,
                                "tier": economic_tier,
                                "source_type": source_type,
                                "source_id": str(order["source_id"]),
                                "item_key": normalized.item_key,
                            },
                        ),
                    )
                except InsufficientCreditsError as exc:
                    balance = self.repository.balance(str(order["wallet_id"]))
                    raise InsufficientUsageCreditsError(
                        quote.credits,
                        balance.available,
                    ) from exc

            now = datetime.now(timezone.utc)
            conn.execute(
                insert(billing_usage_items).values(
                    id=str(uuid4()),
                    usage_order_id=normalized.usage_order_id,
                    price_rule_id=(
                        None
                        if _is_complimentary_unpriced(order)
                        else quote.storage_rule_id or quote.rule_id
                    ),
                    item_key=normalized.item_key,
                    status="held",
                    provider_id=normalized.provider_id,
                    model_key=normalized.model_key,
                    capability=normalized.capability,
                    input_tokens=normalized.input_tokens,
                    output_tokens=normalized.max_output_tokens,
                    quantity=0,
                    quoted_credits=quote.credits,
                    charged_credits=0,
                    usage_snapshot_json=_dump_json(
                        _reservation_snapshot(order, normalized),
                    ),
                    price_snapshot_json=_dump_json(quote.to_jsonable()),
                    supplier_evidence_json="{}",
                    billability="unknown",
                    would_pass=would_pass,
                    would_block_reason=would_block_reason,
                    started_at=now,
                    created_at=now,
                    updated_at=now,
                ),
            )
            self._project_open_api_order(conn, order)
            return ReservedUsageItem(
                usage_order_id=normalized.usage_order_id,
                item_key=normalized.item_key,
                quoted_credits=quote.credits,
                status="held",
            )

    def settle_model_call(
        self,
        command: SettleModelCall,
    ) -> UsageItemResult:
        """Settle one item without treating supplier activity as retail.

        Supplier activity never becomes a retail price input.
        """
        normalized = _normalize_settle_model_call(command)
        with self.repository.engine.begin() as conn:
            order = self._order_row(
                normalized.usage_order_id,
                conn=conn,
                for_update=True,
            )
            self._validate_execution_fence(conn, order, normalized)
            item = self._item_row(
                conn,
                normalized.usage_order_id,
                normalized.item_key,
                for_update=True,
            )
            if item is None:
                raise UsageOrderNotFoundError(normalized.item_key)
            if str(item["status"]) in {"captured", "released"}:
                self._assert_settlement_replay(item, normalized)
                return _usage_item_result(item)
            if (
                str(item["status"]) == "reconciling"
                and normalized.billability == "unknown"
            ):
                if not _is_provider_call_started_marker(item):
                    self._assert_settlement_replay(item, normalized)
                    return _usage_item_result(item)

            if str(item["status"]) not in {"held", "reconciling"}:
                raise UsageOrderStateError(
                    f"cannot settle item in state {item['status']}",
                )
            quoted = int(item["quoted_credits"])
            actual_credits = 0
            if normalized.billability == "billable":
                actual_quote = self._quote_for_order(
                    order,
                    QuoteRequest(
                        provider_id=str(item["provider_id"]),
                        model_key=str(item["model_key"]),
                        capability=str(item["capability"]),
                        parameters=_item_parameters(item),
                        input_tokens=normalized.actual_input_tokens,
                        output_tokens=normalized.actual_output_tokens,
                    ),
                )
                actual_credits = actual_quote.credits
                if actual_credits > quoted:
                    raise UsageOrderStateError(
                        "actual retail credits exceed the pre-call hold",
                    )

            source_type = str(order.get("source_type") or "")
            item_business_key = _item_business_key(
                source_type,
                normalized.usage_order_id,
                normalized.item_key,
            )
            idempotency_namespace = _item_idempotency_namespace(source_type)
            if self._order_mode(order) == "enforced" and quoted:
                if normalized.billability == "billable" and actual_credits:
                    self.repository.append_transaction_in_connection(
                        conn,
                        LedgerTransaction(
                            wallet_id=str(order["wallet_id"]),
                            event_type="usage_capture",
                            credits=actual_credits,
                            business_type="usage_item",
                            business_key=item_business_key,
                            idempotency_key=(
                                f"{idempotency_namespace}:"
                                f"{normalized.usage_order_id}:"
                                f"{normalized.item_key}:capture"
                            ),
                            metadata={
                                "supplier_reference": (
                                    normalized.supplier_reference
                                ),
                            },
                        ),
                    )
                elif normalized.billability in {"billable", "not_billable"}:
                    self.repository.append_transaction_in_connection(
                        conn,
                        LedgerTransaction(
                            wallet_id=str(order["wallet_id"]),
                            event_type="usage_release",
                            credits=0,
                            business_type="usage_item",
                            business_key=item_business_key,
                            idempotency_key=(
                                f"{idempotency_namespace}:"
                                f"{normalized.usage_order_id}:"
                                f"{normalized.item_key}:release"
                            ),
                            metadata={
                                "supplier_reference": (
                                    normalized.supplier_reference
                                ),
                            },
                        ),
                    )

            status = {
                "billable": "captured",
                "not_billable": "released",
                "unknown": "reconciling",
            }[normalized.billability]
            now = datetime.now(timezone.utc)
            conn.execute(
                update(billing_usage_items)
                .where(billing_usage_items.c.id == item["id"])
                .values(
                    status=status,
                    reconciliation_id=(
                        str(item["reconciliation_id"] or uuid4())
                        if normalized.billability == "unknown"
                        else item["reconciliation_id"]
                    ),
                    supplier_reference=normalized.supplier_reference or None,
                    input_tokens=normalized.actual_input_tokens,
                    output_tokens=normalized.actual_output_tokens,
                    charged_credits=actual_credits,
                    supplier_evidence_json=_dump_json(normalized.evidence),
                    billability=normalized.billability,
                    execution_outcome=normalized.execution_outcome,
                    finished_at=now,
                    updated_at=now,
                ),
            )
            self._project_open_api_order(conn, order)
            settled = self._item_row(
                conn,
                normalized.usage_order_id,
                normalized.item_key,
            )
            assert settled is not None
            return _usage_item_result(settled)

    def _quote_for_order(
        self,
        order: Mapping[str, Any],
        request: QuoteRequest,
    ) -> RetailQuote:
        if not _is_complimentary_unpriced(order):
            return self.pricing.quote_locked_catalog(
                str(order["catalog_id"]),
                request,
            )
        return RetailQuote(
            catalog_version=COMPLIMENTARY_UNPRICED_CATALOG_VERSION,
            rule_id="complimentary-unpriced",
            credits=0,
            unit_breakdown={},
            snapshot={
                "pricing_status": "unpriced",
                "complimentary_reason": "szzz_admin",
                "rule": {"metadata": {"economic_tier": "standard"}},
            },
            request=request,
        )

    @staticmethod
    def _validate_execution_fence(
        conn: Connection,
        order: Mapping[str, Any],
        command: ReserveModelCall | SettleModelCall,
    ) -> None:
        """Validate and lock the invocation claim in this transaction."""
        source_type = str(order.get("source_type") or "")
        if source_type != "open_api":
            if source_type in {
                "client",
                "mobile",
                "expert_team",
                "automation",
                "schedule",
                "channel",
            }:
                UsageService._validate_general_execution_guard(
                    conn,
                    order,
                    command,
                )
            return
        invocation_id = str(command.invocation_id or "").strip()
        fence = command.execution_fence
        if not invocation_id or fence is None or fence.generation <= 0:
            raise BillingExecutionFencedError(
                "Open API billing command has no execution fence",
            )
        dialect = conn.engine.dialect.name
        database_now = (
            func.strftime("%Y-%m-%d %H:%M:%f", "now")
            if dialect == "sqlite"
            else func.current_timestamp()
        )
        guarded = conn.execute(
            update(open_api_invocations)
            .where(
                open_api_invocations.c.id == invocation_id,
                open_api_invocations.c.billing_usage_order_id
                == str(order["id"]),
                open_api_invocations.c.status == "running",
                open_api_invocations.c.execution_owner_token
                == fence.owner_token,
                open_api_invocations.c.execution_fence_generation
                == fence.generation,
                open_api_invocations.c.execution_lease_expires_at
                > database_now,
                open_api_invocations.c.terminal_event_json.is_(None),
            )
            .values(
                execution_fence_generation=(
                    open_api_invocations.c.execution_fence_generation
                ),
            ),
        )
        if guarded.rowcount != 1:
            raise BillingExecutionFencedError(
                "Open API invocation execution fence is stale or expired",
            )

    @staticmethod
    def _validate_general_execution_guard(
        conn: Connection,
        order: Mapping[str, Any],
        command: ReserveModelCall | SettleModelCall,
    ) -> None:
        guard = command.execution_guard
        if (
            guard is None
            or guard.kind != "general"
            or not guard.execution_id
            or not guard.owner_token
            or guard.generation <= 0
        ):
            raise BillingExecutionFencedError(
                "general billing command has no execution fence",
            )
        dialect = conn.engine.dialect.name
        database_now = (
            func.strftime("%Y-%m-%d %H:%M:%f", "now")
            if dialect == "sqlite"
            else func.current_timestamp()
        )
        guarded = conn.execute(
            update(billing_executions)
            .where(
                billing_executions.c.id == guard.execution_id,
                billing_executions.c.usage_order_id == str(order["id"]),
                billing_executions.c.state == "running",
                billing_executions.c.owner_token == guard.owner_token,
                billing_executions.c.fence_generation == guard.generation,
                billing_executions.c.lease_expires_at > database_now,
            )
            .values(
                fence_generation=billing_executions.c.fence_generation,
            ),
        )
        if guarded.rowcount != 1:
            raise BillingExecutionFencedError(
                "general billing execution fence is stale or expired",
            )

    def list_items(self, usage_order_id: str) -> list[dict[str, Any]]:
        """Read durable model-call items without analytics queues."""
        with self.repository.engine.connect() as conn:
            rows = (
                conn.execute(
                    select(billing_usage_items)
                    .where(
                        billing_usage_items.c.usage_order_id == usage_order_id,
                    )
                    .order_by(
                        billing_usage_items.c.created_at,
                        billing_usage_items.c.id,
                    ),
                )
                .mappings()
                .all()
            )
        return [_decode_usage_item(dict(row)) for row in rows]

    @staticmethod
    def _item_row(
        conn: Connection,
        usage_order_id: str,
        item_key: str,
        *,
        for_update: bool = False,
    ) -> dict[str, Any] | None:
        statement = select(billing_usage_items).where(
            billing_usage_items.c.usage_order_id == usage_order_id,
            billing_usage_items.c.item_key == item_key,
        )
        if for_update:
            statement = statement.with_for_update()
        row = conn.execute(statement).mappings().first()
        return dict(row) if row is not None else None

    @staticmethod
    def _assert_reservation_replay(
        item: Mapping[str, Any],
        command: ReserveModelCall,
    ) -> None:
        stored = json.loads(str(item["usage_snapshot_json"]) or "{}")
        expected = {
            "provider_id": command.provider_id,
            "model_key": command.model_key,
            "capability": command.capability,
            "parameters": dict(command.parameters),
            "input_tokens": command.input_tokens,
            "max_output_tokens": command.max_output_tokens,
        }
        if _canonical_json(stored.get("reservation", {})) != _canonical_json(
            expected,
        ):
            raise UsageOrderConflictError(
                "model item key is already bound to another reservation",
            )

    @staticmethod
    def _assert_settlement_replay(
        item: Mapping[str, Any],
        command: SettleModelCall,
    ) -> None:
        stored_evidence = json.loads(
            str(item["supplier_evidence_json"]) or "{}",
        )
        expected_status = {
            "billable": "captured",
            "not_billable": "released",
            "unknown": "reconciling",
        }[command.billability]
        stored_outcome = (
            str(item["status"]),
            str(item["billability"]),
            item["supplier_reference"] or "",
            stored_evidence,
            int(item["input_tokens"]),
            int(item["output_tokens"]),
            str(item["execution_outcome"]),
        )
        requested_outcome = (
            expected_status,
            command.billability,
            command.supplier_reference,
            dict(command.evidence),
            command.actual_input_tokens,
            command.actual_output_tokens,
            command.execution_outcome,
        )
        if stored_outcome != requested_outcome:
            raise UsageOrderConflictError(
                "model item key is already settled by another outcome",
            )

    def _project_open_api_order(
        self,
        conn: Connection,
        order: Mapping[str, Any],
    ) -> None:
        """Rebuild order/invocation totals from items and allocations only."""
        rows = [
            dict(row)
            for row in conn.execute(
                select(billing_usage_items).where(
                    billing_usage_items.c.usage_order_id == order["id"],
                ),
            ).mappings()
        ]
        source_type = str(order.get("source_type") or "")
        active_keys = [
            _item_business_key(
                source_type,
                str(order["id"]),
                str(row["item_key"]),
            )
            for row in rows
            if str(row["status"]) in {"held", "reconciling"}
        ]
        held = (
            self.repository.held_usage_credits_in_connection(
                conn,
                str(order["wallet_id"]),
                active_keys,
            )
            if self._order_mode(order) == "enforced"
            else sum(
                int(row["quoted_credits"])
                for row in rows
                if str(row["status"]) in {"held", "reconciling"}
            )
        )
        captured = sum(int(row["charged_credits"]) for row in rows)
        released = sum(
            int(row["quoted_credits"]) - int(row["charged_credits"])
            for row in rows
            if str(row["status"]) in {"captured", "released"}
        )
        reconciling = (
            self.repository.held_usage_credits_in_connection(
                conn,
                str(order["wallet_id"]),
                [
                    _item_business_key(
                        source_type,
                        str(order["id"]),
                        str(row["item_key"]),
                    )
                    for row in rows
                    if str(row["status"]) == "reconciling"
                ],
            )
            if self._order_mode(order) == "enforced"
            else sum(
                int(row["quoted_credits"])
                for row in rows
                if str(row["status"]) == "reconciling"
            )
        )
        statuses = {str(row["status"]) for row in rows}
        status = (
            "quoted"
            if not rows
            else "reconciling"
            if "reconciling" in statuses
            else "held"
            if "held" in statuses
            else "settled"
        )
        billabilities = {str(row["billability"]) for row in rows}
        billability = (
            billabilities.pop() if len(billabilities) == 1 else "unknown"
        )
        now = datetime.now(timezone.utc)
        conn.execute(
            update(billing_usage_orders)
            .where(billing_usage_orders.c.id == order["id"])
            .values(
                status=status,
                quoted_credits=sum(int(row["quoted_credits"]) for row in rows),
                held_credits=held,
                captured_credits=captured,
                released_credits=released,
                reconciling_credits=reconciling,
                billability=billability,
                settled_at=now if status == "settled" else None,
                updated_at=now,
            ),
        )
        token_summary = _token_summary(rows)
        conn.execute(
            update(open_api_invocations)
            .where(
                open_api_invocations.c.billing_usage_order_id == order["id"],
            )
            .values(
                billing_status=status,
                quoted_credits=sum(int(row["quoted_credits"]) for row in rows),
                captured_credits=captured,
                released_credits=released,
                token_summary=_dump_json(token_summary),
            ),
        )

    def project_open_api_order_in_connection(
        self,
        conn: Connection,
        order: Mapping[str, Any],
    ) -> None:
        """Project one OpenAPI order inside a trusted caller transaction.

        Recovery and administrative reconciliation share the same durable
        item/ledger projection.  Keeping the transaction caller-owned avoids
        exposing a balance mutation shortcut or committing half a resolution.
        """
        if str(order.get("source_type") or "") != "open_api":
            raise UsageOrderStateError("only open_api orders can reproject")
        self._project_open_api_order(conn, order)

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

    def reproject_open_api_order(self, order_id: str) -> dict[str, Any]:
        """Rebuild a bridge order from durable item and ledger state."""
        with self.repository.engine.begin() as conn:
            order = self._order_row(order_id, conn=conn, for_update=True)
            if str(order.get("source_type")) != "open_api":
                raise UsageOrderStateError(
                    "only open_api orders can reproject",
                )
            self._project_open_api_order(conn, order)
        return self.get_order(order_id)

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
            "released_credits": int(order["released_credits"]),
            "reconciling_credits": int(order["reconciling_credits"]),
            "supplier_reference": order["supplier_reference"],
            "supplier_evidence": supplier_evidence,
            "billability": str(order["billability"] or "unknown"),
            "request": request_snapshot,
            "quote": price_snapshot,
        }

    @staticmethod
    def _order_mode(order: Mapping[str, Any]) -> BillingMode:
        request_snapshot = json.loads(order["request_snapshot_json"] or "{}")
        return _billing_mode(request_snapshot.get("billing_mode", "shadow"))


def _normalize_reserve_model_call(
    command: ReserveModelCall,
) -> ReserveModelCall:
    values = {
        name: str(getattr(command, name) or "").strip()
        for name in (
            "usage_order_id",
            "item_key",
            "provider_id",
            "model_key",
            "capability",
        )
    }
    if not all(values.values()):
        raise ValueError("model reservation identity fields must be non-empty")
    if any(
        not isinstance(value, int) or value < 0
        for value in (command.input_tokens, command.max_output_tokens)
    ):
        raise ValueError("model reservation token counts must be non-negative")
    return ReserveModelCall(
        **values,
        parameters=json.loads(_dump_json(dict(command.parameters))),
        input_tokens=command.input_tokens,
        max_output_tokens=command.max_output_tokens,
        invocation_id=str(command.invocation_id or "").strip(),
        execution_fence=command.execution_fence,
        execution_guard=command.execution_guard,
    )


def _normalize_settle_model_call(command: SettleModelCall) -> SettleModelCall:
    usage_order_id = str(command.usage_order_id or "").strip()
    item_key = str(command.item_key or "").strip()
    supplier_reference = str(command.supplier_reference or "").strip()
    if not usage_order_id or not item_key:
        raise ValueError("model settlement identity fields must be non-empty")
    if command.billability not in _BILLABILITY_VALUES:
        raise ValueError("unsupported supplier billability")
    if command.execution_outcome not in _EXECUTION_OUTCOMES:
        raise ValueError("unsupported execution outcome")
    if any(
        not isinstance(value, int) or value < 0
        for value in (
            command.actual_input_tokens,
            command.actual_output_tokens,
        )
    ):
        raise ValueError("model settlement token counts must be non-negative")
    evidence = json.loads(_dump_json(dict(command.evidence)))
    if command.billability == "billable" and (
        not supplier_reference or not evidence
    ):
        raise ValueError(
            "billable settlement requires supplier reference and evidence",
        )
    return SettleModelCall(
        usage_order_id=usage_order_id,
        item_key=item_key,
        supplier_reference=supplier_reference,
        billability=command.billability,
        evidence=evidence,
        execution_outcome=command.execution_outcome,
        actual_input_tokens=command.actual_input_tokens,
        actual_output_tokens=command.actual_output_tokens,
        invocation_id=str(command.invocation_id or "").strip(),
        execution_fence=command.execution_fence,
        execution_guard=command.execution_guard,
    )


def _item_business_key(
    source_type: str,
    usage_order_id: str,
    item_key: str,
) -> str:
    namespace = "open-api-item" if source_type == "open_api" else "billing-item"
    return f"{namespace}:{usage_order_id}:{item_key}"


def _item_idempotency_namespace(source_type: str) -> str:
    return "open-api" if source_type == "open_api" else "billing"


def _is_complimentary_unpriced(order: Mapping[str, Any]) -> bool:
    if str(order.get("source_type") or "") != "open_api":
        return False
    try:
        snapshot = json.loads(
            str(order.get("request_snapshot_json") or "{}"),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return bool(
        snapshot.get("complimentary_reason") == "szzz_admin"
        and snapshot.get("complimentary_unpriced") is True
    )


def _economic_tier(snapshot: Mapping[str, Any]) -> str:
    """Read the trusted catalog tier, failing closed for restricted trials."""
    nested = snapshot.get("snapshot")
    catalog_snapshot = nested if isinstance(nested, Mapping) else snapshot
    rule = catalog_snapshot.get("rule")
    metadata = rule.get("metadata") if isinstance(rule, Mapping) else None
    value = (
        str(metadata.get("economic_tier") or "").strip().lower()
        if isinstance(metadata, Mapping)
        else ""
    )
    return value if value in {"standard", "high_cost"} else "high_cost"


def _reservation_snapshot(
    order: Mapping[str, Any],
    command: ReserveModelCall,
) -> dict[str, Any]:
    return {
        "source_type": str(order["source_type"] or "open_api"),
        "source_id": str(order["source_id"] or ""),
        "item_key": command.item_key,
        "catalog_id": str(order["catalog_id"]),
        "reservation": {
            "provider_id": command.provider_id,
            "model_key": command.model_key,
            "capability": command.capability,
            "parameters": dict(command.parameters),
            "input_tokens": command.input_tokens,
            "max_output_tokens": command.max_output_tokens,
        },
    }


def _item_parameters(item: Mapping[str, Any]) -> Mapping[str, Any]:
    snapshot = json.loads(str(item["usage_snapshot_json"]) or "{}")
    parameters = snapshot.get("reservation", {}).get("parameters", {})
    if not isinstance(parameters, Mapping):
        raise UsageOrderStateError("stored model item parameters are invalid")
    return parameters


def _is_provider_call_started_marker(item: Mapping[str, Any]) -> bool:
    """Return whether this is the sole mutable reconciling marker.

    A provider-call-start marker is deliberately replaced by the later
    supplier outcome.  Other unknown outcomes remain strict idempotent
    replays, so a caller cannot rewrite durable reconciliation evidence.
    """
    if str(item.get("billability") or "") != "unknown":
        return False
    try:
        evidence = json.loads(str(item.get("supplier_evidence_json") or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return evidence.get("response_class") == "provider_call_started"


def _reserved_item(item: Mapping[str, Any]) -> ReservedUsageItem:
    return ReservedUsageItem(
        usage_order_id=str(item["usage_order_id"]),
        item_key=str(item["item_key"]),
        quoted_credits=int(item["quoted_credits"]),
        status=str(item["status"]),
    )


def _usage_item_result(item: Mapping[str, Any]) -> UsageItemResult:
    quoted = int(item["quoted_credits"])
    captured = int(item["charged_credits"])
    status = str(item["status"])
    return UsageItemResult(
        usage_order_id=str(item["usage_order_id"]),
        item_key=str(item["item_key"]),
        status=status,
        quoted_credits=quoted,
        captured_credits=captured,
        released_credits=(
            quoted - captured if status in {"captured", "released"} else 0
        ),
        reconciling_credits=quoted if status == "reconciling" else 0,
    )


def _decode_usage_item(item: Mapping[str, Any]) -> dict[str, Any]:
    result = _usage_item_result(item)
    return {
        "id": str(item["id"]),
        "usage_order_id": result.usage_order_id,
        "item_key": result.item_key,
        "status": result.status,
        "quoted_credits": result.quoted_credits,
        "captured_credits": result.captured_credits,
        "released_credits": result.released_credits,
        "reconciling_credits": result.reconciling_credits,
        "billability": str(item["billability"]),
        "execution_outcome": str(item["execution_outcome"]),
        "would_pass": item["would_pass"],
        "would_block_reason": item["would_block_reason"],
    }


def _token_summary(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "input_tokens": sum(int(item["input_tokens"]) for item in items),
        "output_tokens": sum(int(item["output_tokens"]) for item in items),
        "model_calls": len(items),
    }


def _billing_mode(mode: str | None) -> BillingMode:
    value = (
        mode
        if mode is not None
        else os.environ.get("DCLAW_BILLING_MODE", "shadow")
    )
    normalized = value.strip().lower()
    if normalized not in _BILLING_MODES:
        raise ValueError(
            "DCLAW_BILLING_MODE must be one of off, shadow, observe, enforced",
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
