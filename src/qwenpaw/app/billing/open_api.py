# -*- coding: utf-8 -*-
"""Atomic request-level billing identities for OpenAPI calls."""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import insert, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from .pricing import PriceCatalogService
from .complimentary import is_complimentary_user
from .usage import IdempotencyConflictError
from ..storage.repos.billing_repo import BillingRepository
from ..storage.repos.price_catalog_repo import CatalogNotFoundError
from ..storage.schema import (
    billing_price_catalogs,
    billing_usage_orders,
    billing_wallets,
    open_api_external_apps,
    open_api_invocations,
    open_api_keys,
    open_api_publications,
)


BillingMode = Literal["off", "shadow", "observe", "enforced"]
_BILLING_MODES = frozenset({"off", "shadow", "observe", "enforced"})


class OpenApiBillingError(RuntimeError):
    """Base class for OpenAPI billing-session failures."""


class OpenApiPublicationNotFoundError(OpenApiBillingError):
    """The authenticated publication was removed before billing began."""


class CatalogNotReadyError(OpenApiBillingError):
    """No published retail catalog can be locked for the invocation."""


@dataclass(frozen=True)
class OpenApiBillingCommand:
    """Trusted server-side metadata for one authenticated OpenAPI request.

    `payload` is canonicalized and hashed for idempotency but is never stored,
    so prompts and caller content do not enter accounting records.
    """

    app_id: str
    publication_id: str
    api_key_id: str
    target_type: str
    target_id: str
    external_user_id: str | None
    external_session_id: str | None
    payload: Mapping[str, Any]
    idempotency_key: str | None = None
    chat_id: str | None = None
    mode: BillingMode = "shadow"
    budget_credits: int = 0


@dataclass(frozen=True)
class OpenApiBillingSession:
    invocation_id: str
    usage_order_id: str
    wallet_id: str
    bound_user_id: str
    app_id: str
    api_key_id: str
    publication_id: str
    catalog_version: str
    mode: BillingMode
    replayed: bool = field(default=False, compare=False)


class OpenApiBillingCoordinator:
    """Create or recover an invocation/order pair in a single transaction."""

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

    def begin_invocation(
        self,
        command: OpenApiBillingCommand,
    ) -> OpenApiBillingSession:
        """Atomically persist (or replay) one immutable billing session."""
        normalized = _normalize_command(command)
        payload_hash = _payload_hash(normalized.payload)
        business_key = _business_key(normalized)

        try:
            with self.repository.engine.begin() as conn:
                if business_key is not None:
                    existing = self._existing_session(conn, business_key)
                    if existing is not None:
                        self._assert_payload_replay(existing[0], payload_hash)
                        return self._session_from_rows(*existing)

                publication = self._publication_for_update(
                    conn,
                    normalized,
                )
                bound_user_id = str(publication["bound_user_id"])
                wallet = self.repository.ensure_wallet_in_connection(
                    conn,
                    "user",
                    bound_user_id,
                )
                catalog = self._lock_catalog(conn)
                billing_mode: BillingMode = (
                    "observe"
                    if is_complimentary_user(conn, bound_user_id)
                    else normalized.mode
                )
                invocation_id = str(uuid4())
                usage_order_id = str(uuid4())
                persisted_key = business_key or (
                    f"openapi-invocation:{invocation_id}"
                )
                now = datetime.now(timezone.utc)
                snapshot = json.dumps(
                    {
                        "billing_mode": billing_mode,
                        "complimentary_reason": (
                            "szzz_admin"
                            if billing_mode == "observe"
                            and normalized.mode == "enforced"
                            else None
                        ),
                        "client_idempotency_key": normalized.idempotency_key,
                        "request_sha256": payload_hash,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                price_snapshot = json.dumps(
                    {"catalog_version": str(catalog["version"])},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                conn.execute(
                    insert(billing_usage_orders).values(
                        id=usage_order_id,
                        wallet_id=str(wallet["id"]),
                        catalog_id=str(catalog["id"]),
                        business_key=persisted_key,
                        source_type="open_api",
                        source_id=invocation_id,
                        status="quoted",
                        provider_id="open_api",
                        model_key="invocation",
                        capability="text",
                        quoted_credits=0,
                        budget_credits=normalized.budget_credits,
                        held_credits=0,
                        captured_credits=0,
                        released_credits=0,
                        reconciling_credits=0,
                        request_snapshot_json=snapshot,
                        price_snapshot_json=price_snapshot,
                        billability="unknown",
                        created_at=now,
                        updated_at=now,
                    ),
                )
                if self._after_order_insert is not None:
                    self._after_order_insert()
                conn.execute(
                    insert(open_api_invocations).values(
                        id=invocation_id,
                        app_id=normalized.app_id,
                        publication_id=normalized.publication_id,
                        api_key_id=normalized.api_key_id,
                        target_type=str(publication["target_type"]),
                        target_id=str(publication["target_id"]),
                        chat_id=normalized.chat_id,
                        external_session_id=normalized.external_session_id,
                        external_user_id=normalized.external_user_id,
                        status="accepted",
                        status_code=202,
                        latency_ms=0,
                        token_summary="{}",
                        error_summary="",
                        billing_usage_order_id=usage_order_id,
                        billing_status="quoted",
                        quoted_credits=0,
                        captured_credits=0,
                        released_credits=0,
                        billing_error_code=None,
                        created_at=now,
                    ),
                )
                return OpenApiBillingSession(
                    invocation_id=invocation_id,
                    usage_order_id=usage_order_id,
                    wallet_id=str(wallet["id"]),
                    bound_user_id=bound_user_id,
                    app_id=normalized.app_id,
                    api_key_id=normalized.api_key_id,
                    publication_id=normalized.publication_id,
                    catalog_version=str(catalog["version"]),
                    mode=billing_mode,
                )
        except IntegrityError:
            # A concurrent request can win the namespaced business key. Read
            # the durable pair after rollback and apply the same replay rule.
            if business_key is None:
                raise
            with self.repository.engine.connect() as conn:
                existing = self._existing_session(conn, business_key)
            if existing is None:
                raise
            self._assert_payload_replay(existing[0], payload_hash)
            return self._session_from_rows(*existing)

    @staticmethod
    def _publication_for_update(
        conn: Connection,
        command: OpenApiBillingCommand,
    ) -> dict[str, Any]:
        row = (
            conn.execute(
                select(open_api_publications)
                .join(
                    open_api_keys,
                    open_api_keys.c.publication_id
                    == open_api_publications.c.id,
                )
                .join(
                    open_api_external_apps,
                    open_api_external_apps.c.id == open_api_keys.c.app_id,
                )
                .where(
                    open_api_publications.c.id == command.publication_id,
                    open_api_keys.c.id == command.api_key_id,
                    open_api_keys.c.app_id == command.app_id,
                    open_api_external_apps.c.id == command.app_id,
                )
                .with_for_update(),
            )
            .mappings()
            .first()
        )
        if row is None or not str(row["bound_user_id"]).strip():
            raise OpenApiPublicationNotFoundError(command.publication_id)
        return dict(row)

    def _lock_catalog(self, conn: Connection) -> dict[str, Any]:
        try:
            return self.pricing.lock_effective_catalog(conn)
        except CatalogNotFoundError as exc:
            raise CatalogNotReadyError(
                "no published retail catalog is ready",
            ) from exc

    @staticmethod
    def _existing_session(
        conn: Connection,
        business_key: str,
    ) -> (
        tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]
        | None
    ):
        row = (
            conn.execute(
                select(
                    billing_usage_orders,
                    open_api_invocations,
                    billing_wallets.c.owner_id.label("wallet_owner_id"),
                    billing_price_catalogs.c.version.label("catalog_version"),
                )
                .join(
                    open_api_invocations,
                    open_api_invocations.c.billing_usage_order_id
                    == billing_usage_orders.c.id,
                )
                .join(
                    billing_wallets,
                    billing_wallets.c.id == billing_usage_orders.c.wallet_id,
                )
                .join(
                    billing_price_catalogs,
                    billing_price_catalogs.c.id
                    == billing_usage_orders.c.catalog_id,
                )
                .where(billing_usage_orders.c.business_key == business_key),
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        order = {column.name: row[column] for column in billing_usage_orders.c}
        invocation = {
            column.name: row[column] for column in open_api_invocations.c
        }
        wallet = {"owner_id": row["wallet_owner_id"]}
        catalog = {"version": row["catalog_version"]}
        return order, invocation, wallet, catalog

    @staticmethod
    def _assert_payload_replay(
        order: dict[str, Any], payload_hash: str
    ) -> None:
        try:
            stored = json.loads(order["request_snapshot_json"] or "{}")
        except json.JSONDecodeError as exc:
            raise IdempotencyConflictError(
                "stored OpenAPI request is invalid"
            ) from exc
        if stored.get("request_sha256") != payload_hash:
            raise IdempotencyConflictError(
                "idempotency key is already bound to another request payload",
            )

    @staticmethod
    def _session_from_rows(
        order: dict[str, Any],
        invocation: dict[str, Any],
        wallet: dict[str, Any],
        catalog: dict[str, Any],
    ) -> OpenApiBillingSession:
        snapshot = json.loads(order["request_snapshot_json"] or "{}")
        mode = str(snapshot.get("billing_mode", "shadow"))
        if mode not in _BILLING_MODES:
            raise OpenApiBillingError("stored OpenAPI billing mode is invalid")
        return OpenApiBillingSession(
            invocation_id=str(invocation["id"]),
            usage_order_id=str(order["id"]),
            wallet_id=str(order["wallet_id"]),
            bound_user_id=str(wallet["owner_id"]),
            app_id=str(invocation["app_id"]),
            api_key_id=str(invocation["api_key_id"]),
            publication_id=str(invocation["publication_id"]),
            catalog_version=str(catalog["version"]),
            mode=mode,  # type: ignore[arg-type]
            replayed=True,
        )


def _normalize_command(
    command: OpenApiBillingCommand,
) -> OpenApiBillingCommand:
    values = {
        field: str(getattr(command, field) or "").strip()
        for field in (
            "app_id",
            "publication_id",
            "api_key_id",
            "target_type",
            "target_id",
        )
    }
    if not all(values.values()):
        raise ValueError("OpenAPI billing identity fields must be non-empty")
    mode = str(command.mode).strip().lower()
    if mode not in _BILLING_MODES:
        raise ValueError("OpenAPI billing mode is invalid")
    if (
        not isinstance(command.budget_credits, int)
        or command.budget_credits < 0
    ):
        raise ValueError(
            "OpenAPI billing budget must be a non-negative integer"
        )
    return OpenApiBillingCommand(
        **values,
        external_user_id=_optional_text(command.external_user_id),
        external_session_id=_optional_text(command.external_session_id),
        payload=command.payload,
        idempotency_key=_optional_text(command.idempotency_key),
        chat_id=_optional_text(command.chat_id),
        mode=mode,  # type: ignore[arg-type]
        budget_credits=command.budget_credits,
    )


def _business_key(command: OpenApiBillingCommand) -> str | None:
    if command.idempotency_key is None:
        return None
    return (
        f"openapi:{command.app_id}:{command.publication_id}:"
        f"{command.idempotency_key}"
    )


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _payload_hash(payload: Mapping[str, Any]) -> str:
    if not isinstance(payload, Mapping):
        raise ValueError("OpenAPI request payload must be a JSON object")
    try:
        canonical = json.dumps(
            dict(payload),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        decoded = json.loads(canonical)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(
            "OpenAPI request payload must be strict JSON"
        ) from exc
    if not isinstance(decoded, dict):
        raise ValueError("OpenAPI request payload must be a JSON object")
    return sha256(canonical.encode("utf-8")).hexdigest()
