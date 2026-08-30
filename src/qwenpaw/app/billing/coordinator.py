# -*- coding: utf-8 -*-
"""Atomic request identities for non-OpenAPI model billing."""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import insert, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from .context import BillingMode, BillingSession, BillingSource
from .complimentary import is_complimentary_user
from .pricing import PriceCatalogService
from ..storage.repos.billing_repo import BillingRepository
from ..storage.schema import billing_executions, billing_usage_orders


class BillingRequestConflictError(RuntimeError):
    """A request key was replayed with different trusted input."""


@dataclass(frozen=True)
class BillingCommand:
    """Trusted payer, source, and fingerprint input for one request."""

    payer_user_id: str
    source: BillingSource
    request_key: str
    payload: Mapping[str, Any]


class BillingCoordinator:
    """Create or replay a wallet/order/execution tuple atomically."""

    def __init__(
        self,
        repository: BillingRepository,
        pricing: PriceCatalogService,
        *,
        after_order_insert: Callable[[], None] | None = None,
    ) -> None:
        self.repository = repository
        self.pricing = pricing
        self._after_order_insert = after_order_insert

    def begin_execution(self, command: BillingCommand) -> BillingSession:
        normalized = _normalize(command)
        request_hash = _payload_hash(normalized.payload)
        business_key = _business_key(normalized)
        try:
            with self.repository.engine.begin() as conn:
                existing = self._existing(conn, business_key)
                if existing is not None:
                    return self._replay(existing, normalized, request_hash)

                wallet = self.repository.ensure_wallet_in_connection(
                    conn,
                    "user",
                    normalized.payer_user_id,
                )
                catalog = self.pricing.lock_effective_catalog(conn)
                billing_mode: BillingMode = (
                    "observe"
                    if is_complimentary_user(conn, normalized.payer_user_id)
                    else "enforced"
                )
                execution_id = str(uuid4())
                usage_order_id = str(uuid4())
                snapshot = _dump_json(
                    {
                        "billing_mode": billing_mode,
                        "complimentary_reason": (
                            "szzz_admin" if billing_mode == "observe" else None
                        ),
                        "request_sha256": request_hash,
                        "source": _source_snapshot(normalized.source),
                    },
                )
                conn.execute(
                    insert(billing_usage_orders).values(
                        id=usage_order_id,
                        wallet_id=str(wallet["id"]),
                        catalog_id=str(catalog["id"]),
                        business_key=business_key,
                        source_type=normalized.source.type,
                        source_id=execution_id,
                        status="quoted",
                        provider_id="request",
                        model_key="request",
                        capability="text",
                        request_snapshot_json=snapshot,
                        price_snapshot_json=_dump_json(
                            {"catalog_version": str(catalog["version"])},
                        ),
                        billability="unknown",
                    ),
                )
                if self._after_order_insert is not None:
                    self._after_order_insert()
                conn.execute(
                    insert(billing_executions).values(
                        id=execution_id,
                        usage_order_id=usage_order_id,
                        payer_user_id=normalized.payer_user_id,
                        source_type=normalized.source.type,
                        source_id=normalized.source.id,
                        request_sha256=request_hash,
                        state="accepted",
                    ),
                )
                return BillingSession(
                    execution_id=execution_id,
                    usage_order_id=usage_order_id,
                    wallet_id=str(wallet["id"]),
                    payer_user_id=normalized.payer_user_id,
                    catalog_version=str(catalog["version"]),
                    source=normalized.source,
                    mode=billing_mode,
                )
        except IntegrityError:
            with self.repository.engine.connect() as conn:
                existing = self._existing(conn, business_key)
            if existing is None:
                raise
            return self._replay(existing, normalized, request_hash)

    @staticmethod
    def _existing(
        conn: Connection,
        business_key: str,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        row = conn.execute(
            select(billing_usage_orders, billing_executions)
            .join(
                billing_executions,
                billing_executions.c.usage_order_id
                == billing_usage_orders.c.id,
            )
            .where(billing_usage_orders.c.business_key == business_key),
        ).mappings().one_or_none()
        if row is None:
            return None
        order = {
            column.name: row[column.name]
            for column in billing_usage_orders.c
        }
        execution = {
            column.name: row[f"{column.name}_1"]
            if f"{column.name}_1" in row
            else row[column.name]
            for column in billing_executions.c
        }
        return order, execution

    @staticmethod
    def _replay(
        existing: tuple[dict[str, Any], dict[str, Any]],
        command: BillingCommand,
        request_hash: str,
    ) -> BillingSession:
        order, execution = existing
        if (
            str(execution["request_sha256"]) != request_hash
            or str(execution["payer_user_id"]) != command.payer_user_id
            or str(execution["source_type"]) != command.source.type
            or str(execution["source_id"]) != command.source.id
        ):
            raise BillingRequestConflictError(command.request_key)
        price_snapshot = json.loads(order["price_snapshot_json"] or "{}")
        request_snapshot = json.loads(order["request_snapshot_json"] or "{}")
        return BillingSession(
            execution_id=str(execution["id"]),
            usage_order_id=str(order["id"]),
            wallet_id=str(order["wallet_id"]),
            payer_user_id=command.payer_user_id,
            catalog_version=str(price_snapshot["catalog_version"]),
            source=command.source,
            mode=cast(
                BillingMode,
                str(request_snapshot.get("billing_mode") or "enforced"),
            ),
        )


def _normalize(command: BillingCommand) -> BillingCommand:
    payer = _required(command.payer_user_id, "payer_user_id")
    request_key = _required(command.request_key, "request_key")
    source_type = _required(command.source.type, "source.type")
    source_id = _required(command.source.id, "source.id")
    return BillingCommand(
        payer_user_id=payer,
        source=BillingSource(
            type=source_type,
            id=source_id,
            expert_id=_optional(command.source.expert_id),
            expert_team_run_id=_optional(
                command.source.expert_team_run_id,
            ),
        ),
        request_key=request_key,
        payload=command.payload,
    )


def _business_key(command: BillingCommand) -> str:
    return (
        f"billing:{command.source.type}:{command.source.id}:"
        f"{command.request_key}"
    )


def _payload_hash(payload: Mapping[str, Any]) -> str:
    return sha256(_dump_json(payload).encode("utf-8")).hexdigest()


def _source_snapshot(source: BillingSource) -> dict[str, str | None]:
    return {
        "type": source.type,
        "id": source.id,
        "expert_id": source.expert_id,
        "expert_team_run_id": source.expert_team_run_id,
    }


def _dump_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _required(value: str, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} must be non-empty")
    return normalized


def _optional(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


__all__ = [
    "BillingCommand",
    "BillingCoordinator",
    "BillingRequestConflictError",
]
