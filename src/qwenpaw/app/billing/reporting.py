# -*- coding: utf-8 -*-
"""Owner-scoped billing reports and audited administrative reconciliation."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
import os
from typing import Any, Literal, Mapping, Sequence
from uuid import uuid4

from sqlalchemy import (
    Date,
    and_,
    case,
    cast,
    exists,
    func,
    insert,
    literal,
    or_,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError

from .models import LedgerTransaction
from .pricing import PriceCatalogService, QuoteRequest
from .usage import UsageOrderStateError, UsageService
from ..storage.repos.billing_repo import BillingRepository
from ..storage.schema import (
    billing_ledger_entries,
    billing_price_catalogs,
    billing_reconciliation_audits,
    billing_rollout_settings,
    billing_usage_items,
    billing_usage_orders,
    billing_wallets,
    open_api_external_apps,
    open_api_invocations,
    open_api_publications,
)


_BILLING_MODES = frozenset({"off", "shadow", "observe", "enforced"})
_RESOLUTIONS = frozenset({"billable", "not_billable"})
_MAX_CURSOR_LENGTH = 2048
_MAX_BIGINT = (1 << 63) - 1


class ReconciliationNotFoundError(LookupError):
    """The item is absent or is no longer eligible for reconciliation."""


class ReconciliationConflictError(RuntimeError):
    """An idempotency key already names a different resolution."""


@dataclass(frozen=True)
class BillingReportFilters:
    """Bounded, timezone-aware filters shared by user and admin reports."""

    started_at: datetime | None = None
    ended_at: datetime | None = None
    model: str | None = None
    provider: str | None = None
    publication_id: str | None = None
    app_id: str | None = None
    api_key_id: str | None = None
    status: str | None = None
    owner_user_id: str | None = None

    def __post_init__(self) -> None:
        for value in (self.started_at, self.ended_at):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise ValueError("date filters must include a timezone")
        if (
            self.started_at is not None
            and self.ended_at is not None
            and self.started_at >= self.ended_at
        ):
            raise ValueError("started_at must be before ended_at")
        for name in (
            "model",
            "provider",
            "publication_id",
            "app_id",
            "api_key_id",
            "status",
            "owner_user_id",
        ):
            value = getattr(self, name)
            if value is not None and not str(value).strip():
                raise ValueError(f"{name} must be non-empty")


@dataclass(frozen=True)
class ReconciliationResolution:
    """Trusted admin decision without a client-provided actor identity."""

    idempotency_key: str
    billability: Literal["billable", "not_billable"]
    reason: str
    actual_input_tokens: int = 0
    actual_output_tokens: int = 0

    def __post_init__(self) -> None:
        if not self.idempotency_key.strip() or len(self.idempotency_key) > 255:
            raise ValueError(
                "idempotency_key must contain 1 to 255 characters",
            )
        if self.billability not in _RESOLUTIONS:
            raise ValueError("resolution billability must be final")
        if not self.reason.strip() or len(self.reason) > 2000:
            raise ValueError("reason must contain 1 to 2000 characters")
        for value in (self.actual_input_tokens, self.actual_output_tokens):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value <= _MAX_BIGINT
            ):
                raise ValueError(
                    "actual token counts must be non-negative BIGINTs",
                )
        if self.billability == "not_billable" and (
            self.actual_input_tokens or self.actual_output_tokens
        ):
            raise ValueError(
                "not_billable resolution cannot report charged usage",
            )


class BillingReportingService:
    """Read financial truth and resolve ambiguity without leaking evidence."""

    def __init__(
        self,
        repository: BillingRepository,
        pricing: PriceCatalogService,
        *,
        clock=None,
    ) -> None:
        self.repository = repository
        self.pricing = pricing
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def list_usage_orders(
        self,
        *,
        owner_user_id: str | None,
        filters: BillingReportFilters,
        limit: int,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """List bridge orders using stable keyset pagination."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        scope = _filter_scope(owner_user_id, filters)
        anchor = _decode_cursor(cursor, scope) if cursor else None
        statement = self._order_statement(owner_user_id, filters)
        if anchor is not None:
            created_at, order_id = anchor
            statement = statement.where(
                or_(
                    billing_usage_orders.c.created_at < created_at,
                    and_(
                        billing_usage_orders.c.created_at == created_at,
                        billing_usage_orders.c.id < order_id,
                    ),
                ),
            )
        statement = statement.order_by(
            billing_usage_orders.c.created_at.desc(),
            billing_usage_orders.c.id.desc(),
        ).limit(limit + 1)
        with self.repository.engine.connect() as conn:
            rows = [dict(row) for row in conn.execute(statement).mappings()]
            serialized = self._serialize_orders(
                conn,
                rows[:limit],
                detail=False,
                include_internal=owner_user_id is None,
            )
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = _encode_cursor(
                _aware_utc(last["created_at"]),
                str(last["id"]),
                scope,
            )
        return {"items": serialized, "next_cursor": next_cursor}

    def get_usage_order(
        self,
        order_id: str,
        *,
        owner_user_id: str | None,
    ) -> dict[str, Any] | None:
        """Return one order, treating another owner's identifier as absent."""
        filters = BillingReportFilters()
        statement = self._order_statement(owner_user_id, filters).where(
            billing_usage_orders.c.id == order_id,
        )
        with self.repository.engine.connect() as conn:
            row = conn.execute(statement).mappings().first()
            if row is None:
                return None
            return self._serialize_orders(
                conn,
                [dict(row)],
                detail=True,
                include_internal=owner_user_id is None,
            )[0]

    def open_api_summary(
        self,
        owner_user_id: str,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict[str, Any]:
        """Aggregate a bounded UTC financial window in the database."""
        if (date_from is None) != (date_to is None):
            raise ValueError("date_from and date_to must be provided together")
        if date_from is None:
            date_to = _aware_utc(self._clock()).date() + timedelta(days=1)
            date_from = date_to - timedelta(days=30)
        assert date_to is not None
        if date_from >= date_to:
            raise ValueError("date_from must be before date_to")
        if (date_to - date_from).days > 366:
            raise ValueError("summary window cannot exceed 366 days")
        started_at = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        ended_at = datetime.combine(date_to, time.min, tzinfo=timezone.utc)

        eligible = self._order_statement(
            owner_user_id,
            BillingReportFilters(
                started_at=started_at,
                ended_at=ended_at,
            ),
        ).cte("eligible_summary_orders")
        item_totals = (
            select(
                billing_usage_items.c.usage_order_id.label("order_id"),
                func.count().label("model_calls"),
                func.sum(billing_usage_items.c.input_tokens).label(
                    "input_tokens",
                ),
                func.sum(billing_usage_items.c.output_tokens).label(
                    "output_tokens",
                ),
            )
            .select_from(
                billing_usage_items.join(
                    eligible,
                    eligible.c.id == billing_usage_items.c.usage_order_id,
                ),
            )
            .group_by(billing_usage_items.c.usage_order_id)
            .subquery("summary_item_totals")
        )
        item_business_key = (
            literal("open-api-item:")
            + billing_usage_items.c.usage_order_id
            + literal(":")
            + billing_usage_items.c.item_key
        )
        ledger_totals = (
            select(
                billing_usage_items.c.usage_order_id.label("order_id"),
                func.sum(-billing_ledger_entries.c.credit_delta).label(
                    "actual_debited_credits",
                ),
            )
            .select_from(
                billing_usage_items.join(
                    eligible,
                    eligible.c.id == billing_usage_items.c.usage_order_id,
                ).join(
                    billing_ledger_entries,
                    and_(
                        billing_ledger_entries.c.business_key
                        == item_business_key,
                        billing_ledger_entries.c.event_type == "usage_capture",
                    ),
                ),
            )
            .group_by(billing_usage_items.c.usage_order_id)
            .subquery("summary_ledger_totals")
        )
        if self.repository.engine.dialect.name == "postgresql":
            day = cast(
                func.timezone("UTC", eligible.c.created_at),
                Date,
            ).label("day")
        else:
            day = func.date(eligible.c.created_at).label("day")
        estimated = or_(
            eligible.c.request_snapshot_json.like(
                '%"billing_mode":"shadow"%',
            ),
            eligible.c.request_snapshot_json.like(
                '%"billing_mode": "shadow"%',
            ),
            eligible.c.request_snapshot_json.like(
                '%"billing_mode":"observe"%',
            ),
            eligible.c.request_snapshot_json.like(
                '%"billing_mode": "observe"%',
            ),
        )
        daily_statement = (
            select(
                day,
                func.count(eligible.c.id).label("orders"),
                func.coalesce(func.sum(item_totals.c.model_calls), 0).label(
                    "model_calls",
                ),
                func.coalesce(func.sum(item_totals.c.input_tokens), 0).label(
                    "input_tokens",
                ),
                func.coalesce(func.sum(item_totals.c.output_tokens), 0).label(
                    "output_tokens",
                ),
                func.coalesce(func.sum(eligible.c.captured_credits), 0).label(
                    "retail_credits",
                ),
                func.coalesce(
                    func.sum(ledger_totals.c.actual_debited_credits),
                    0,
                ).label("actual_debited_credits"),
                func.coalesce(
                    func.sum(
                        case(
                            (estimated, eligible.c.captured_credits),
                            else_=0,
                        ),
                    ),
                    0,
                ).label("shadow_estimated_credits"),
                func.coalesce(
                    func.sum(eligible.c.reconciling_credits),
                    0,
                ).label("reconciling_credits"),
            )
            .select_from(
                eligible.outerjoin(
                    item_totals,
                    item_totals.c.order_id == eligible.c.id,
                ).outerjoin(
                    ledger_totals,
                    ledger_totals.c.order_id == eligible.c.id,
                ),
            )
            .group_by(day)
            .order_by(day)
        )
        with self.repository.engine.connect() as conn:
            daily_rows = [
                dict(row) for row in conn.execute(daily_statement).mappings()
            ]
        totals = {
            "orders": 0,
            "model_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "retail_credits": 0,
            "actual_debited_credits": 0,
            "shadow_estimated_credits": 0,
            "reconciling_credits": 0,
        }
        by_month: dict[str, dict[str, int]] = {}
        by_day = []
        for row in daily_rows:
            day_value = str(row["day"])
            values = {name: int(row[name] or 0) for name in totals}
            for name, value in values.items():
                totals[name] += value
            by_day.append({"date": day_value, **values})
            month = day_value[:7]
            month_bucket = by_month.setdefault(
                month,
                {
                    "orders": 0,
                    "retail_credits": 0,
                    "actual_debited_credits": 0,
                },
            )
            for name in month_bucket:
                month_bucket[name] += values[name]
        wallet = self.repository.get_wallet("user", owner_user_id)
        balance = (
            self.repository.balance(str(wallet["id"]))
            if wallet is not None
            else None
        )
        rollout = self.get_rollout(include_observe_evaluation=False)
        available = balance.available if balance is not None else 0
        threshold = _non_negative_env("DCLAW_LOW_BALANCE_THRESHOLD", 100)
        qr_code_url = os.environ.get("DCLAW_TOP_UP_QR_URL", "").strip() or None
        instructions = (
            os.environ.get("DCLAW_TOP_UP_INSTRUCTIONS", "").strip() or None
        )
        return {
            "window": {
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "timezone": "UTC",
                "lifetime": False,
            },
            "totals": totals,
            "by_day": by_day,
            "by_month": [
                {"month": month, **values}
                for month, values in sorted(by_month.items())
            ],
            "balance": {
                "available": available,
                "held": balance.held if balance else 0,
            },
            "low_balance": available <= threshold,
            "top_up": {
                "enabled": bool(qr_code_url or instructions),
                "qr_code_url": qr_code_url,
                "instructions": instructions,
                "collects_payment": False,
            },
            "eras": {
                "financial_cutover_at": rollout["billing_cutover_at"],
                "historical_statistics_included": False,
            },
        }

    def list_reconciliation(
        self,
        *,
        filters: BillingReportFilters,
        limit: int,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Return only unresolved, ambiguous OpenAPI items."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        scope = f"reconciliation:{_filter_scope(None, filters)}"
        anchor = _decode_cursor(cursor, scope) if cursor else None
        eligible_orders = self._order_statement(None, filters).subquery(
            "eligible_orders",
        )
        statement = (
            select(
                eligible_orders,
                billing_usage_items.c.id.label("queue_item_id"),
                billing_usage_items.c.reconciliation_id.label(
                    "queue_reconciliation_id",
                ),
                billing_usage_items.c.created_at.label("queue_created_at"),
            )
            .select_from(
                eligible_orders.join(
                    billing_usage_items,
                    billing_usage_items.c.usage_order_id
                    == eligible_orders.c.id,
                ),
            )
            .where(
                billing_usage_items.c.status == "reconciling",
                billing_usage_items.c.billability == "unknown",
            )
        )
        if filters.model is not None:
            statement = statement.where(
                billing_usage_items.c.model_key == filters.model,
            )
        if filters.provider is not None:
            statement = statement.where(
                billing_usage_items.c.provider_id == filters.provider,
            )
        if anchor is not None:
            created_at, item_id = anchor
            statement = statement.where(
                or_(
                    billing_usage_items.c.created_at < created_at,
                    and_(
                        billing_usage_items.c.created_at == created_at,
                        billing_usage_items.c.id < item_id,
                    ),
                ),
            )
        statement = statement.order_by(
            billing_usage_items.c.created_at.desc(),
            billing_usage_items.c.id.desc(),
        ).limit(limit + 1)
        with self.repository.engine.connect() as conn:
            rows = [dict(row) for row in conn.execute(statement).mappings()]
            page_rows = rows[:limit]
            serialized_orders = self._serialize_orders(
                conn,
                page_rows,
                detail=True,
                include_internal=True,
                include_item_internal=True,
            )
            items = []
            for row, order in zip(page_rows, serialized_orders):
                queue_item_id = str(row["queue_item_id"])
                order_items = order.pop("items")
                public_item = next(
                    item
                    for item in order_items
                    if item.pop("_internal_id") == queue_item_id
                )
                items.append(
                    {
                        "reconciliation_id": str(
                            row["queue_reconciliation_id"],
                        ),
                        "order": order,
                        "item": public_item,
                    },
                )
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = _encode_cursor(
                _aware_utc(last["queue_created_at"]),
                str(last["queue_item_id"]),
                scope,
            )
        return {"items": items, "next_cursor": next_cursor}

    def resolve_reconciliation(
        self,
        reconciliation_id: str,
        *,
        actor_id: str,
        resolution: ReconciliationResolution,
    ) -> dict[str, Any]:
        """Resolve ambiguity through ledger primitives and an audit."""
        normalized_actor = str(actor_id).strip()
        if not normalized_actor:
            raise ValueError("admin actor is required")
        request_hash = _resolution_hash(
            reconciliation_id,
            normalized_actor,
            resolution,
        )
        existing = self._resolution_replay(
            resolution.idempotency_key,
            request_hash,
        )
        if existing is not None:
            return existing
        audit_id = str(uuid4())
        now = _aware_utc(self._clock())
        try:
            with self.repository.engine.begin() as conn:
                initial = conn.execute(
                    select(
                        billing_usage_items.c.id,
                        billing_usage_items.c.usage_order_id,
                    ).where(
                        billing_usage_items.c.reconciliation_id
                        == reconciliation_id,
                    ),
                ).first()
                if initial is None:
                    raise ReconciliationNotFoundError(reconciliation_id)
                order = (
                    conn.execute(
                        select(billing_usage_orders)
                        .where(
                            billing_usage_orders.c.id
                            == initial.usage_order_id,
                        )
                        .with_for_update(),
                    )
                    .mappings()
                    .first()
                )
                concurrent_audit = (
                    conn.execute(
                        select(billing_reconciliation_audits).where(
                            billing_reconciliation_audits.c.idempotency_key
                            == resolution.idempotency_key.strip(),
                        ),
                    )
                    .mappings()
                    .first()
                )
                if concurrent_audit is not None:
                    if str(concurrent_audit["request_sha256"]) != request_hash:
                        raise ReconciliationConflictError(
                            resolution.idempotency_key,
                        )
                    winner = (
                        conn.execute(
                            select(billing_usage_items).where(
                                billing_usage_items.c.id
                                == concurrent_audit["usage_item_id"],
                            ),
                        )
                        .mappings()
                        .first()
                    )
                    if winner is None:
                        raise ReconciliationConflictError(
                            resolution.idempotency_key,
                        )
                    return _audit_row(
                        concurrent_audit,
                        reconciliation_id=str(winner["reconciliation_id"]),
                    )
                item = (
                    conn.execute(
                        select(billing_usage_items)
                        .where(
                            billing_usage_items.c.id == initial.id,
                            billing_usage_items.c.usage_order_id
                            == initial.usage_order_id,
                        )
                        .with_for_update(),
                    )
                    .mappings()
                    .first()
                )
                if (
                    order is None
                    or item is None
                    or (
                        str(order["source_type"] or "") != "open_api"
                        or str(item["status"]) != "reconciling"
                        or str(item["billability"]) != "unknown"
                    )
                ):
                    raise ReconciliationNotFoundError(reconciliation_id)
                charged_credits = self._resolution_credits(
                    order,
                    item,
                    resolution,
                )
                status = (
                    "captured"
                    if resolution.billability == "billable"
                    else "released"
                )
                mode = _order_mode(order)
                business_key = _item_business_key(
                    str(order["id"]),
                    str(item["item_key"]),
                )
                if mode == "enforced" and int(item["quoted_credits"]):
                    event_type = (
                        "usage_capture"
                        if resolution.billability == "billable"
                        and charged_credits
                        else "usage_release"
                    )
                    self.repository.append_transaction_in_connection(
                        conn,
                        LedgerTransaction(
                            wallet_id=str(order["wallet_id"]),
                            event_type=event_type,
                            credits=charged_credits
                            if event_type == "usage_capture"
                            else 0,
                            business_type="usage_item",
                            business_key=business_key,
                            idempotency_key=(
                                "admin-reconciliation:"
                                f"{resolution.idempotency_key}:"
                                f"{event_type}"
                            ),
                            actor_type="admin",
                            actor_id=normalized_actor,
                            reason=resolution.reason.strip(),
                            metadata={"reconciliation_audit_id": audit_id},
                        ),
                    )
                conn.execute(
                    insert(billing_reconciliation_audits).values(
                        id=audit_id,
                        usage_item_id=str(item["id"]),
                        usage_order_id=str(order["id"]),
                        idempotency_key=resolution.idempotency_key.strip(),
                        request_sha256=request_hash,
                        actor_id=normalized_actor,
                        reason=resolution.reason.strip(),
                        billability=resolution.billability,
                        actual_input_tokens=resolution.actual_input_tokens,
                        actual_output_tokens=resolution.actual_output_tokens,
                        charged_credits=charged_credits,
                        previous_status=str(item["status"]),
                        resolved_status=status,
                        created_at=now,
                    ),
                )
                conn.execute(
                    update(billing_usage_items)
                    .where(
                        billing_usage_items.c.id == item["id"],
                        billing_usage_items.c.status == "reconciling",
                        billing_usage_items.c.billability == "unknown",
                    )
                    .values(
                        status=status,
                        billability=resolution.billability,
                        input_tokens=resolution.actual_input_tokens,
                        output_tokens=resolution.actual_output_tokens,
                        charged_credits=charged_credits,
                        supplier_evidence_json=_dump_json(
                            {
                                "kind": "manual_reconciliation",
                                "audit_id": audit_id,
                            },
                        ),
                        finished_at=now,
                        updated_at=now,
                    ),
                )
                UsageService(
                    self.repository,
                    self.pricing,
                ).project_open_api_order_in_connection(conn, order)
        except IntegrityError:
            replay = self._resolution_replay(
                resolution.idempotency_key,
                request_hash,
            )
            if replay is not None:
                return replay
            raise
        result = self.get_reconciliation_audit(audit_id)
        if result is None:
            raise ReconciliationNotFoundError(reconciliation_id)
        return result

    def list_reconciliation_audits(  # pylint: disable=too-many-branches
        self,
        *,
        actor_id: str | None = None,
        reconciliation_id: str | None = None,
        order_id: str | None = None,
        outcome: str | None = None,
        idempotency_key: str | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        limit: int,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Page immutable operator decisions without financial evidence."""
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        for value in (started_at, ended_at):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise ValueError("audit dates must include a timezone")
        if started_at and ended_at and started_at >= ended_at:
            raise ValueError("started_at must be before ended_at")
        scope_payload = {
            "actor_id": actor_id,
            "reconciliation_id": reconciliation_id,
            "order_id": order_id,
            "outcome": outcome,
            "idempotency_key": idempotency_key,
            "started_at": started_at.isoformat() if started_at else None,
            "ended_at": ended_at.isoformat() if ended_at else None,
        }
        scope = (
            "audit:"
            + sha256(
                _dump_json(scope_payload).encode("utf-8"),
            ).hexdigest()
        )
        anchor = _decode_cursor(cursor, scope) if cursor else None
        statement = select(
            billing_reconciliation_audits,
            billing_usage_items.c.reconciliation_id,
        ).join(
            billing_usage_items,
            billing_reconciliation_audits.c.usage_item_id
            == billing_usage_items.c.id,
        )
        predicates = []
        if actor_id is not None:
            predicates.append(
                billing_reconciliation_audits.c.actor_id == actor_id,
            )
        if reconciliation_id is not None:
            predicates.append(
                billing_usage_items.c.reconciliation_id == reconciliation_id,
            )
        if order_id is not None:
            predicates.append(
                billing_reconciliation_audits.c.usage_order_id == order_id,
            )
        if outcome is not None:
            predicates.append(
                billing_reconciliation_audits.c.resolved_status == outcome,
            )
        if idempotency_key is not None:
            predicates.append(
                billing_reconciliation_audits.c.idempotency_key
                == idempotency_key,
            )
        if started_at is not None:
            predicates.append(
                billing_reconciliation_audits.c.created_at
                >= started_at.astimezone(timezone.utc),
            )
        if ended_at is not None:
            predicates.append(
                billing_reconciliation_audits.c.created_at
                < ended_at.astimezone(timezone.utc),
            )
        if anchor is not None:
            created_at, audit_id = anchor
            predicates.append(
                or_(
                    billing_reconciliation_audits.c.created_at < created_at,
                    and_(
                        billing_reconciliation_audits.c.created_at
                        == created_at,
                        billing_reconciliation_audits.c.id < audit_id,
                    ),
                ),
            )
        statement = (
            statement.where(*predicates)
            .order_by(
                billing_reconciliation_audits.c.created_at.desc(),
                billing_reconciliation_audits.c.id.desc(),
            )
            .limit(limit + 1)
        )
        with self.repository.engine.connect() as conn:
            rows = [dict(row) for row in conn.execute(statement).mappings()]
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = page[-1]
            next_cursor = _encode_cursor(
                _aware_utc(last["created_at"]),
                str(last["id"]),
                scope,
            )
        return {
            "items": [
                _audit_row(
                    row,
                    reconciliation_id=str(row["reconciliation_id"]),
                )
                for row in page
            ],
            "next_cursor": next_cursor,
        }

    def get_reconciliation_audit(
        self,
        audit_id: str,
    ) -> dict[str, Any] | None:
        """Return one safe immutable decision by its opaque audit UUID."""
        statement = (
            select(
                billing_reconciliation_audits,
                billing_usage_items.c.reconciliation_id,
            )
            .join(
                billing_usage_items,
                billing_reconciliation_audits.c.usage_item_id
                == billing_usage_items.c.id,
            )
            .where(billing_reconciliation_audits.c.id == audit_id)
        )
        with self.repository.engine.connect() as conn:
            row = conn.execute(statement).mappings().first()
        if row is None:
            return None
        return _audit_row(
            row,
            reconciliation_id=str(row["reconciliation_id"]),
        )

    def activate_rollout(self, mode: str, *, actor_id: str) -> dict[str, Any]:
        """Persist mode and CAS the first enforced cutover instant."""
        normalized_mode = str(mode).strip().lower()
        normalized_actor = str(actor_id).strip()
        if normalized_mode not in _BILLING_MODES:
            raise ValueError("unsupported billing rollout mode")
        if not normalized_actor:
            raise ValueError("admin actor is required")
        now = _aware_utc(self._clock())
        for attempt in range(2):
            try:
                with self.repository.engine.begin() as conn:
                    row = (
                        conn.execute(
                            select(billing_rollout_settings)
                            .where(billing_rollout_settings.c.id == "global")
                            .with_for_update(),
                        )
                        .mappings()
                        .first()
                    )
                    if row is None:
                        conn.execute(
                            insert(billing_rollout_settings).values(
                                id="global",
                                mode=normalized_mode,
                                billing_cutover_at=(
                                    now
                                    if normalized_mode == "enforced"
                                    else None
                                ),
                                cutover_actor_id=(
                                    normalized_actor
                                    if normalized_mode == "enforced"
                                    else None
                                ),
                                updated_by=normalized_actor,
                                created_at=now,
                                updated_at=now,
                            ),
                        )
                    else:
                        values: dict[str, Any] = {
                            "mode": normalized_mode,
                            "updated_by": normalized_actor,
                            "updated_at": now,
                        }
                        if (
                            normalized_mode == "enforced"
                            and row["billing_cutover_at"] is None
                        ):
                            values.update(
                                billing_cutover_at=now,
                                cutover_actor_id=normalized_actor,
                            )
                        conn.execute(
                            update(billing_rollout_settings)
                            .where(billing_rollout_settings.c.id == "global")
                            .values(**values),
                        )
                break
            except IntegrityError:
                if attempt:
                    raise
        return self.get_rollout()

    def get_rollout(
        self,
        *,
        include_observe_evaluation: bool = True,
    ) -> dict[str, Any]:
        """Return rollout state, defaulting to non-mutating shadow."""
        row = self.repository.get_rollout_setting()
        result: dict[str, Any]
        if row is None:
            result = {
                "mode": "shadow",
                "billing_cutover_at": None,
                "cutover_actor_id": None,
                "updated_by": None,
            }
        else:
            result = {
                "mode": str(row["mode"]),
                "billing_cutover_at": (
                    _aware_utc(row["billing_cutover_at"]).isoformat()
                    if row["billing_cutover_at"] is not None
                    else None
                ),
                "cutover_actor_id": row["cutover_actor_id"],
                "updated_by": str(row["updated_by"]),
            }
        if include_observe_evaluation:
            result["observe_evaluation"] = self._observe_evaluation()
        return result

    def _observe_evaluation(self) -> dict[str, Any]:
        evaluated = billing_usage_items.c.would_pass.is_not(None)
        with self.repository.engine.connect() as conn:
            totals = conn.execute(
                select(
                    func.count().label("calls"),
                    func.coalesce(
                        func.sum(
                            case(
                                (billing_usage_items.c.would_pass, 1),
                                else_=0,
                            ),
                        ),
                        0,
                    ).label("would_pass"),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    billing_usage_items.c.would_pass.is_(
                                        False,
                                    ),
                                    1,
                                ),
                                else_=0,
                            ),
                        ),
                        0,
                    ).label("would_block"),
                ).where(evaluated),
            ).one()
            reasons = conn.execute(
                select(
                    billing_usage_items.c.would_block_reason,
                    func.count(),
                )
                .where(
                    billing_usage_items.c.would_pass.is_(False),
                    billing_usage_items.c.would_block_reason.is_not(None),
                )
                .group_by(billing_usage_items.c.would_block_reason),
            ).all()
        return {
            "calls": int(totals.calls),
            "would_pass": int(totals.would_pass),
            "would_block": int(totals.would_block),
            "would_block_reasons": {
                str(reason): int(count) for reason, count in reasons
            },
        }

    def _order_statement(
        self,
        owner_user_id: str | None,
        filters: BillingReportFilters,
    ):
        item_filter = billing_usage_items.alias("filtered_item")
        statement = (
            select(
                billing_usage_orders,
                open_api_invocations.c.id.label("invocation_id"),
                open_api_invocations.c.billing_status.label(
                    "invocation_billing_status",
                ),
                open_api_invocations.c.publication_id,
                open_api_invocations.c.app_id,
                open_api_invocations.c.api_key_id,
                open_api_publications.c.name.label("publication_name"),
                open_api_external_apps.c.name.label("app_name"),
                billing_price_catalogs.c.version.label("catalog_version"),
                billing_wallets.c.owner_id.label("owner_user_id"),
            )
            .select_from(
                billing_usage_orders.join(
                    billing_wallets,
                    billing_usage_orders.c.wallet_id == billing_wallets.c.id,
                )
                .join(
                    open_api_invocations,
                    open_api_invocations.c.billing_usage_order_id
                    == billing_usage_orders.c.id,
                )
                .join(
                    open_api_publications,
                    open_api_invocations.c.publication_id
                    == open_api_publications.c.id,
                )
                .join(
                    open_api_external_apps,
                    open_api_invocations.c.app_id
                    == open_api_external_apps.c.id,
                )
                .join(
                    billing_price_catalogs,
                    billing_usage_orders.c.catalog_id
                    == billing_price_catalogs.c.id,
                ),
            )
            .where(
                billing_usage_orders.c.source_type == "open_api",
                open_api_invocations.c.billing_status != "unbilled",
                billing_wallets.c.owner_type == "user",
            )
        )
        selected_owner = owner_user_id or filters.owner_user_id
        if selected_owner is not None:
            statement = statement.where(
                billing_wallets.c.owner_id == selected_owner,
            )
        if filters.started_at is not None:
            statement = statement.where(
                billing_usage_orders.c.created_at
                >= filters.started_at.astimezone(timezone.utc),
            )
        if filters.ended_at is not None:
            statement = statement.where(
                billing_usage_orders.c.created_at
                < filters.ended_at.astimezone(timezone.utc),
            )
        if filters.publication_id is not None:
            statement = statement.where(
                open_api_invocations.c.publication_id
                == filters.publication_id,
            )
        if filters.app_id is not None:
            statement = statement.where(
                open_api_invocations.c.app_id == filters.app_id,
            )
        if filters.api_key_id is not None:
            statement = statement.where(
                open_api_invocations.c.api_key_id == filters.api_key_id,
            )
        if filters.status is not None:
            statement = statement.where(
                billing_usage_orders.c.status == filters.status,
            )
        item_predicates = [
            item_filter.c.usage_order_id == billing_usage_orders.c.id,
        ]
        if filters.model is not None:
            item_predicates.append(item_filter.c.model_key == filters.model)
        if filters.provider is not None:
            item_predicates.append(
                item_filter.c.provider_id == filters.provider,
            )
        if len(item_predicates) > 1:
            statement = statement.where(
                exists(select(1).where(*item_predicates)),
            )
        return statement

    def _serialize_orders(
        self,
        conn,
        rows: Sequence[Mapping[str, Any]],
        *,
        detail: bool,
        include_internal: bool,
        include_item_internal: bool = False,
    ) -> list[dict[str, Any]]:
        if not rows:
            return []
        order_ids = tuple({str(row["id"]) for row in rows})
        all_items = [
            dict(item)
            for item in conn.execute(
                select(billing_usage_items)
                .where(billing_usage_items.c.usage_order_id.in_(order_ids))
                .order_by(
                    billing_usage_items.c.usage_order_id,
                    billing_usage_items.c.created_at,
                    billing_usage_items.c.id,
                ),
            ).mappings()
        ]
        items_by_order: dict[str, list[dict[str, Any]]] = {}
        business_to_order: dict[str, str] = {}
        for item in all_items:
            order_id = str(item["usage_order_id"])
            items_by_order.setdefault(order_id, []).append(item)
            business_to_order[
                _item_business_key(order_id, str(item["item_key"]))
            ] = order_id
        actual_by_order: dict[str, int] = {}
        if business_to_order:
            ledger_rows = conn.execute(
                select(
                    billing_ledger_entries.c.business_key,
                    func.sum(
                        -billing_ledger_entries.c.credit_delta,
                    ).label("debited"),
                )
                .where(
                    billing_ledger_entries.c.event_type == "usage_capture",
                    billing_ledger_entries.c.business_key.in_(
                        tuple(business_to_order),
                    ),
                )
                .group_by(billing_ledger_entries.c.business_key),
            ).mappings()
            for ledger in ledger_rows:
                order_id = business_to_order[str(ledger["business_key"])]
                actual_by_order[order_id] = actual_by_order.get(
                    order_id,
                    0,
                ) + int(ledger["debited"] or 0)
        return [
            self._serialize_prefetched_order(
                row,
                items_by_order.get(str(row["id"]), []),
                actual_by_order.get(str(row["id"]), 0),
                detail=detail,
                include_internal=include_internal,
                include_item_internal=include_item_internal,
            )
            for row in rows
        ]

    @staticmethod
    def _serialize_prefetched_order(
        row: Mapping[str, Any],
        item_rows: Sequence[Mapping[str, Any]],
        actual_debited: int,
        *,
        detail: bool,
        include_internal: bool,
        include_item_internal: bool,
    ) -> dict[str, Any]:
        mode = str(
            _load_json(row["request_snapshot_json"]).get("billing_mode")
            or "shadow",
        )
        result: dict[str, Any] = {
            "id": str(row["id"]),
            "invocation_id": str(row["invocation_id"]),
            "publication": {
                "id": str(row["publication_id"]),
                "name": str(row["publication_name"]),
            },
            "application": {
                "id": str(row["app_id"]),
                "name": str(row["app_name"]),
            },
            "status": str(row["status"]),
            "billing_status": str(row["invocation_billing_status"]),
            "billing_mode": mode,
            "is_estimate": mode in {"shadow", "observe"},
            "catalog_version": str(row["catalog_version"]),
            "quoted_credits": int(row["quoted_credits"]),
            "captured_credits": int(row["captured_credits"]),
            "released_credits": int(row["released_credits"]),
            "reconciling_credits": int(row["reconciling_credits"]),
            "actual_debited_credits": actual_debited,
            "item_count": len(item_rows),
            "tokens": {
                "input": sum(int(item["input_tokens"]) for item in item_rows),
                "output": sum(
                    int(item["output_tokens"]) for item in item_rows
                ),
            },
            "created_at": _aware_utc(row["created_at"]).isoformat(),
            "updated_at": _aware_utc(row["updated_at"]).isoformat(),
        }
        if include_internal:
            result.update(
                owner_user_id=str(row["owner_user_id"]),
                api_key_id=str(row["api_key_id"]),
            )
        if detail:
            result["items"] = [
                _public_item_row(
                    item,
                    call_sequence=sequence,
                    catalog_version=str(row["catalog_version"]),
                    include_internal=include_item_internal,
                )
                for sequence, item in enumerate(item_rows, start=1)
            ]
        return result

    def _resolution_credits(
        self,
        order: Mapping[str, Any],
        item: Mapping[str, Any],
        resolution: ReconciliationResolution,
    ) -> int:
        if resolution.billability == "not_billable":
            return 0
        reservation = _load_json(item["usage_snapshot_json"]).get(
            "reservation",
            {},
        )
        parameters = (
            reservation.get("parameters", {})
            if isinstance(reservation, Mapping)
            else {}
        )
        quote = self.pricing.quote_locked_catalog(
            str(order["catalog_id"]),
            QuoteRequest(
                provider_id=str(item["provider_id"]),
                model_key=str(item["model_key"]),
                capability=str(item["capability"]),
                parameters=parameters
                if isinstance(parameters, Mapping)
                else {},
                input_tokens=resolution.actual_input_tokens,
                output_tokens=resolution.actual_output_tokens,
            ),
        )
        if quote.credits > int(item["quoted_credits"]):
            raise UsageOrderStateError(
                "actual retail credits exceed the reserved quote",
            )
        return int(quote.credits)

    def _resolution_replay(
        self,
        key: str,
        request_hash: str,
    ) -> dict[str, Any] | None:
        with self.repository.engine.connect() as conn:
            row = (
                conn.execute(
                    select(
                        billing_reconciliation_audits,
                        billing_usage_items.c.reconciliation_id,
                    )
                    .join(
                        billing_usage_items,
                        billing_reconciliation_audits.c.usage_item_id
                        == billing_usage_items.c.id,
                    )
                    .where(
                        billing_reconciliation_audits.c.idempotency_key
                        == key.strip(),
                    ),
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        if str(row["request_sha256"]) != request_hash:
            raise ReconciliationConflictError(key)
        return _audit_row(
            row,
            reconciliation_id=str(row["reconciliation_id"]),
        )


def _public_item_row(
    item: Mapping[str, Any],
    *,
    call_sequence: int,
    catalog_version: str,
    include_internal: bool = False,
) -> dict[str, Any]:
    result = {
        "call_sequence": call_sequence,
        "model": {
            "provider": str(item["provider_id"]),
            "id": str(item["model_key"]),
            "capability": str(item["capability"]),
        },
        "tokens": {
            "input": int(item["input_tokens"]),
            "output": int(item["output_tokens"]),
        },
        "credits": {
            "quoted": int(item["quoted_credits"]),
            "charged": int(item["charged_credits"]),
        },
        "status": str(item["status"]),
        "catalog_version": catalog_version,
    }
    if include_internal:
        result["_internal_id"] = str(item["id"])
    if item["would_pass"] is not None:
        result["would_pass"] = bool(item["would_pass"])
        result["would_block_reason"] = item["would_block_reason"]
    return result


def _audit_row(
    audit: Mapping[str, Any],
    *,
    reconciliation_id: str,
) -> dict[str, Any]:
    """Allowlist the immutable administrative decision."""
    return {
        "audit_id": str(audit["id"]),
        "reconciliation_id": reconciliation_id,
        "order_id": str(audit["usage_order_id"]),
        "actor_id": str(audit["actor_id"]),
        "reason": str(audit["reason"]),
        "idempotency_key": str(audit["idempotency_key"]),
        "resolution": {
            "status": str(audit["resolved_status"]),
            "billability": str(audit["billability"]),
            "actual_tokens": {
                "input": int(audit["actual_input_tokens"]),
                "output": int(audit["actual_output_tokens"]),
            },
            "charged_credits": int(audit["charged_credits"]),
        },
        "created_at": _aware_utc(audit["created_at"]).isoformat(),
    }


def persisted_billing_mode(
    repository: BillingRepository,
    fallback: str = "shadow",
) -> str:
    """Read durable rollout state with an explicit bootstrap fallback."""
    row = repository.get_rollout_setting()
    mode = str(row["mode"] if row is not None else fallback).strip().lower()
    if mode not in _BILLING_MODES:
        raise ValueError("unsupported billing rollout mode")
    if row is None and mode == "enforced":
        # Enforcement is a financial cutover, not a process-level feature
        # flag.  Only activate_rollout() may durably record that transition.
        return "shadow"
    return mode


def _filter_scope(
    owner_user_id: str | None,
    filters: BillingReportFilters,
) -> str:
    payload = {
        "owner": owner_user_id,
        **{
            name: (
                value.astimezone(timezone.utc).isoformat()
                if isinstance(value, datetime)
                else value
            )
            for name, value in filters.__dict__.items()
        },
    }
    return sha256(_dump_json(payload).encode("utf-8")).hexdigest()


def _encode_cursor(created_at: datetime, order_id: str, scope: str) -> str:
    raw = _dump_json(
        {"at": created_at.isoformat(), "id": order_id, "scope": scope},
    )
    return (
        base64.urlsafe_b64encode(raw.encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
    )


def _decode_cursor(cursor: str, scope: str) -> tuple[datetime, str]:
    if not cursor or len(cursor) > _MAX_CURSOR_LENGTH:
        raise ValueError("invalid cursor")
    try:
        padding = "=" * (-len(cursor) % 4)
        payload = json.loads(
            base64.b64decode(cursor + padding, altchars=b"-_", validate=True),
        )
        if payload.get("scope") != scope or not str(payload.get("id") or ""):
            raise ValueError
        created_at = datetime.fromisoformat(str(payload["at"]))
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError
        return created_at.astimezone(timezone.utc), str(payload["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid cursor") from exc


def _resolution_hash(
    reconciliation_id: str,
    actor_id: str,
    resolution: ReconciliationResolution,
) -> str:
    return sha256(
        _dump_json(
            {
                "reconciliation_id": reconciliation_id,
                "actor_id": actor_id,
                "billability": resolution.billability,
                "reason": resolution.reason.strip(),
                "actual_input_tokens": resolution.actual_input_tokens,
                "actual_output_tokens": resolution.actual_output_tokens,
            },
        ).encode("utf-8"),
    ).hexdigest()


def _order_mode(order: Mapping[str, Any]) -> str:
    return str(
        _load_json(order["request_snapshot_json"]).get("billing_mode")
        or "shadow",
    )


def _item_business_key(order_id: str, item_key: str) -> str:
    return f"open-api-item:{order_id}:{item_key}"


def _load_json(value: Any) -> dict[str, Any]:
    try:
        loaded = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _dump_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _non_negative_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return max(0, value)


__all__ = [
    "BillingReportFilters",
    "BillingReportingService",
    "ReconciliationConflictError",
    "ReconciliationNotFoundError",
    "ReconciliationResolution",
    "persisted_billing_mode",
]
