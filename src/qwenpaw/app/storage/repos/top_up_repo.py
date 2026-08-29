# -*- coding: utf-8 -*-
"""Durable repository for fixed-product manual top-up claims."""

from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from typing import Any
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from ..schema import (
    billing_top_up_audits,
    billing_top_up_claims,
    billing_top_up_products,
)


class TopUpIdempotencyConflict(RuntimeError):
    """An idempotency key was reused for a different canonical request."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _request_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class TopUpRepository:  # pylint: disable=too-many-public-methods
    """Persist products, customer claims, and append-only review audits."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_product(
        self,
        values: dict[str, Any],
        *,
        conn: Connection | None = None,
    ) -> dict[str, Any]:
        row = self._product_values(values)
        row.update(id=str(uuid4()), public_id=str(uuid4()))
        with self._connection(conn) as connection:
            connection.execute(insert(billing_top_up_products).values(**row))
            return self._get_product(connection, row["public_id"])

    def replace_product(
        self,
        public_id: str,
        values: dict[str, Any],
        *,
        conn: Connection | None = None,
    ) -> dict[str, Any]:
        row = self._product_values(values)
        with self._connection(conn) as connection:
            result = connection.execute(
                update(billing_top_up_products)
                .where(billing_top_up_products.c.public_id == public_id)
                .values(**row),
            )
            if result.rowcount != 1:
                raise KeyError(public_id)
            return self._get_product(connection, public_id)

    def list_products(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        statement = select(billing_top_up_products)
        if active_only:
            statement = statement.where(
                billing_top_up_products.c.status == "active",
            )
        statement = statement.order_by(
            billing_top_up_products.c.display_order.asc(),
            billing_top_up_products.c.created_at.asc(),
        )
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings()]

    def get_product_by_public_id(
        self,
        public_id: str,
        *,
        conn: Connection | None = None,
    ) -> dict[str, Any] | None:
        with self._connection(conn, write=False) as connection:
            row = (
                connection.execute(
                    select(billing_top_up_products).where(
                        billing_top_up_products.c.public_id == public_id,
                    ),
                )
                .mappings()
                .first()
            )
            return dict(row) if row else None

    def create_claim(  # pylint: disable=too-many-arguments
        self,
        *,
        owner_id: str,
        wallet_id: str,
        product_public_id: str,
        payment_channel: str,
        payer_reference: str,
        customer_note: str | None,
        idempotency_key: str,
        conn: Connection | None = None,
    ) -> dict[str, Any]:
        request = {
            "owner_id": owner_id,
            "product_public_id": product_public_id,
            "payment_channel": payment_channel,
            "payer_reference": payer_reference,
            "customer_note": customer_note,
        }
        digest = _request_hash(request)
        with self._connection(conn) as connection:
            existing = self._claim_by_submission_key(connection, idempotency_key)
            if existing:
                if existing["submission_request_sha256"] != digest:
                    raise TopUpIdempotencyConflict(idempotency_key)
                return self._decode_claim(existing)
            product = self._get_product(connection, product_public_id)
            if product["status"] != "active":
                raise ValueError("top-up product is disabled")
            snapshot = {
                key: product[key]
                for key in (
                    "public_id",
                    "name",
                    "description",
                    "payment_amount_fen",
                    "purchased_credits",
                    "promotional_credits",
                    "promotional_expiry_days",
                )
            }
            values = {
                "id": str(uuid4()),
                "public_id": str(uuid4()),
                "wallet_id": wallet_id,
                "product_id": product["id"],
                "owner_type": "user",
                "owner_id": owner_id,
                "product_snapshot_json": _canonical_json(snapshot),
                "payment_amount_fen": snapshot["payment_amount_fen"],
                "payment_channel": payment_channel,
                "payer_reference": payer_reference,
                "customer_note": customer_note,
                "submission_idempotency_key": idempotency_key,
                "submission_request_sha256": digest,
                "status": "pending",
            }
            try:
                with connection.begin_nested():
                    connection.execute(
                        insert(billing_top_up_claims).values(**values),
                    )
            except IntegrityError as exc:
                existing = self._claim_by_submission_key(
                    connection,
                    idempotency_key,
                )
                if existing and existing["submission_request_sha256"] == digest:
                    return self._decode_claim(existing)
                raise TopUpIdempotencyConflict(idempotency_key) from exc
            return self._get_claim(connection, values["public_id"])

    def get_claim_by_public_id(
        self,
        public_id: str,
        *,
        owner_id: str | None = None,
        conn: Connection | None = None,
    ) -> dict[str, Any] | None:
        with self._connection(conn, write=False) as connection:
            statement = select(billing_top_up_claims).where(
                billing_top_up_claims.c.public_id == public_id,
            )
            if owner_id is not None:
                statement = statement.where(
                    billing_top_up_claims.c.owner_id == owner_id,
                )
            row = connection.execute(statement).mappings().first()
            return self._decode_claim(dict(row)) if row else None

    def list_claims(
        self,
        *,
        owner_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        statement = select(billing_top_up_claims)
        if owner_id is not None:
            statement = statement.where(billing_top_up_claims.c.owner_id == owner_id)
        if status is not None:
            statement = statement.where(billing_top_up_claims.c.status == status)
        statement = statement.order_by(
            billing_top_up_claims.c.created_at.desc(),
            billing_top_up_claims.c.id.desc(),
        ).limit(max(1, min(limit, 200)))
        with self.engine.connect() as connection:
            return [
                self._decode_claim(dict(row))
                for row in connection.execute(statement).mappings()
            ]

    def lock_pending_claim(
        self,
        conn: Connection,
        public_id: str,
    ) -> dict[str, Any] | None:
        statement = select(billing_top_up_claims).where(
            billing_top_up_claims.c.public_id == public_id,
        )
        if conn.dialect.name == "postgresql":
            statement = statement.with_for_update()
        row = conn.execute(statement).mappings().first()
        return self._decode_claim(dict(row)) if row else None

    def append_audit(
        self,
        conn: Connection,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        row = {"id": str(uuid4()), **values}
        conn.execute(insert(billing_top_up_audits).values(**row))
        return dict(
            conn.execute(
                select(billing_top_up_audits).where(
                    billing_top_up_audits.c.id == row["id"],
                ),
            )
            .mappings()
            .one(),
        )

    def list_audits(self, claim_id: str) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    select(billing_top_up_audits)
                    .where(billing_top_up_audits.c.claim_id == claim_id)
                    .order_by(billing_top_up_audits.c.created_at.asc()),
                ).mappings()
            ]

    @staticmethod
    def _product_values(values: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "name",
            "description",
            "payment_amount_fen",
            "purchased_credits",
            "promotional_credits",
            "promotional_expiry_days",
            "status",
            "display_order",
            "created_by",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"unsupported product fields: {sorted(unknown)}")
        return dict(values)

    @staticmethod
    def _decode_claim(row: dict[str, Any]) -> dict[str, Any]:
        decoded = dict(row)
        decoded["product_snapshot"] = json.loads(
            decoded.pop("product_snapshot_json"),
        )
        return decoded

    @staticmethod
    def _claim_by_submission_key(
        connection: Connection,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        row = (
            connection.execute(
                select(billing_top_up_claims).where(
                    billing_top_up_claims.c.submission_idempotency_key
                    == idempotency_key,
                ),
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    def _get_product(self, connection: Connection, public_id: str) -> dict[str, Any]:
        row = (
            connection.execute(
                select(billing_top_up_products).where(
                    billing_top_up_products.c.public_id == public_id,
                ),
            )
            .mappings()
            .first()
        )
        if row is None:
            raise KeyError(public_id)
        return dict(row)

    def _get_claim(self, connection: Connection, public_id: str) -> dict[str, Any]:
        row = (
            connection.execute(
                select(billing_top_up_claims).where(
                    billing_top_up_claims.c.public_id == public_id,
                ),
            )
            .mappings()
            .one()
        )
        return self._decode_claim(dict(row))

    def _connection(self, conn: Connection | None, *, write: bool = True):
        if conn is not None:
            return nullcontext(conn)
        return self.engine.begin() if write else self.engine.connect()
