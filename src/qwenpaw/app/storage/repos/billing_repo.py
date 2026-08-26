# -*- coding: utf-8 -*-
"""Transactional wallet and immutable ledger repository."""
# pylint: disable=redefined-builtin
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, case, insert, or_, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from ...billing.models import (
    BillingInvariantError,
    DuplicateLedgerTransactionError,
    InsufficientCreditsError,
    LedgerTransaction,
    WalletBalance,
)
from ..schema import (
    billing_credit_lots,
    billing_ledger_allocations,
    billing_ledger_entries,
    billing_wallets,
)


_GRANT_EVENTS = {
    "purchase_grant",
    "promotion_grant",
    "package_grant",
    "admin_grant",
}
_CREDIT_TYPES = {"purchased", "promotional", "package"}
_TYPE_COLUMNS = {
    "purchased": billing_wallets.c.purchased_credits,
    "promotional": billing_wallets.c.promotional_credits,
    "package": billing_wallets.c.package_credits,
}


class BillingRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def ensure_wallet(self, owner_type: str, owner_id: str) -> dict[str, Any]:
        if not owner_type.strip() or not owner_id.strip():
            raise ValueError(
                "wallet owner_type and owner_id must be non-empty",
            )

        with self.engine.begin() as conn:
            row = (
                conn.execute(
                    select(billing_wallets).where(
                        billing_wallets.c.owner_type == owner_type,
                        billing_wallets.c.owner_id == owner_id,
                    ),
                )
                .mappings()
                .first()
            )
            if row is None:
                try:
                    with conn.begin_nested():
                        conn.execute(
                            insert(billing_wallets).values(
                                id=str(uuid4()),
                                owner_type=owner_type,
                                owner_id=owner_id,
                            ),
                        )
                except IntegrityError:
                    # A concurrent creator won the unique owner key. The
                    # savepoint keeps this transaction usable for the read.
                    pass
                row = (
                    conn.execute(
                        select(billing_wallets).where(
                            billing_wallets.c.owner_type == owner_type,
                            billing_wallets.c.owner_id == owner_id,
                        ),
                    )
                    .mappings()
                    .one()
                )
            return dict(row)

    def append_transaction(self, command: LedgerTransaction) -> WalletBalance:
        self._validate_command(command)
        try:
            with self.engine.begin() as conn:
                wallet = (
                    conn.execute(
                        select(billing_wallets)
                        .where(billing_wallets.c.id == command.wallet_id)
                        .with_for_update(),
                    )
                    .mappings()
                    .first()
                )
                if wallet is None:
                    raise BillingInvariantError(
                        f"wallet not found: {command.wallet_id}",
                    )
                if conn.execute(
                    select(billing_ledger_entries.c.id).where(
                        billing_ledger_entries.c.idempotency_key
                        == command.idempotency_key,
                    ),
                ).first():
                    raise DuplicateLedgerTransactionError(
                        command.idempotency_key,
                    )

                if command.event_type in _GRANT_EVENTS:
                    self._append_grant(conn, command)
                elif command.event_type == "usage_hold":
                    self._append_hold(
                        conn,
                        command,
                        wallet_available=int(wallet["available_credits"]),
                    )
                elif command.event_type == "usage_release":
                    self._append_release(conn, command)
                else:
                    raise ValueError(
                        f"unsupported ledger event type: {command.event_type}",
                    )

                balance = self._balance_for_update(conn, command.wallet_id)
                self._assert_projection(balance)
                return balance
        except IntegrityError as exc:
            if self._idempotency_exists(command.idempotency_key):
                raise DuplicateLedgerTransactionError(
                    command.idempotency_key,
                ) from exc
            raise

    def grant(
        self,
        wallet_id: str,
        *,
        credits: int,
        credit_type: str,
        expires_at: datetime | None,
        idempotency_key: str,
    ) -> WalletBalance:
        event_types = {
            "purchased": "purchase_grant",
            "promotional": "promotion_grant",
            "package": "package_grant",
        }
        if credit_type not in event_types:
            raise ValueError(f"unsupported credit type: {credit_type}")
        return self.append_transaction(
            LedgerTransaction(
                wallet_id=wallet_id,
                event_type=event_types[credit_type],
                credits=credits,
                business_type="grant",
                business_key=idempotency_key,
                idempotency_key=idempotency_key,
                credit_type=credit_type,
                expires_at=expires_at,
            ),
        )

    def hold(
        self,
        wallet_id: str,
        *,
        credits: int,
        business_key: str,
        idempotency_key: str,
    ) -> WalletBalance:
        return self.append_transaction(
            LedgerTransaction(
                wallet_id=wallet_id,
                event_type="usage_hold",
                credits=credits,
                business_type="usage",
                business_key=business_key,
                idempotency_key=idempotency_key,
            ),
        )

    def release(
        self,
        wallet_id: str,
        *,
        business_key: str,
        idempotency_key: str,
    ) -> WalletBalance:
        return self.append_transaction(
            LedgerTransaction(
                wallet_id=wallet_id,
                event_type="usage_release",
                credits=0,
                business_type="usage",
                business_key=business_key,
                idempotency_key=idempotency_key,
            ),
        )

    def balance(self, wallet_id: str) -> WalletBalance:
        with self.engine.connect() as conn:
            return self._balance_for_update(conn, wallet_id)

    def allocations(self, business_key: str) -> list[tuple[str, int]]:
        source_entry = billing_ledger_entries.alias("source_entry")
        expiry_is_null = case(
            (billing_credit_lots.c.expires_at.is_(None), 1),
            else_=0,
        )
        type_priority = case(
            (billing_credit_lots.c.credit_type == "promotional", 0),
            (billing_credit_lots.c.credit_type == "package", 1),
            else_=2,
        )
        entry_id = (
            select(billing_ledger_entries.c.id)
            .where(
                billing_ledger_entries.c.business_key == business_key,
                billing_ledger_entries.c.event_type == "usage_hold",
            )
            .order_by(
                billing_ledger_entries.c.created_at.desc(),
                billing_ledger_entries.c.id.desc(),
            )
            .limit(1)
            .scalar_subquery()
        )
        stmt = (
            select(
                source_entry.c.idempotency_key,
                billing_ledger_allocations.c.credits,
            )
            .select_from(
                billing_ledger_allocations.join(
                    billing_credit_lots,
                    billing_ledger_allocations.c.credit_lot_id
                    == billing_credit_lots.c.id,
                ).join(
                    source_entry,
                    billing_credit_lots.c.source_ledger_entry_id
                    == source_entry.c.id,
                ),
            )
            .where(billing_ledger_allocations.c.ledger_entry_id == entry_id)
            .order_by(
                expiry_is_null,
                billing_credit_lots.c.expires_at.asc(),
                type_priority,
                billing_credit_lots.c.created_at.asc(),
                billing_credit_lots.c.id.asc(),
            )
        )
        with self.engine.connect() as conn:
            return [
                (str(row.idempotency_key), int(row.credits))
                for row in conn.execute(stmt)
            ]

    def list_ledger(
        self,
        wallet_id: str,
        limit: int,
        cursor: str | None,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            raise ValueError("ledger limit must be positive")
        stmt = select(billing_ledger_entries).where(
            billing_ledger_entries.c.wallet_id == wallet_id,
        )
        with self.engine.connect() as conn:
            if cursor is not None:
                anchor = conn.execute(
                    select(
                        billing_ledger_entries.c.created_at,
                        billing_ledger_entries.c.id,
                    ).where(
                        billing_ledger_entries.c.wallet_id == wallet_id,
                        billing_ledger_entries.c.id == cursor,
                    ),
                ).first()
                if anchor is None:
                    raise ValueError(
                        "ledger cursor does not belong to this wallet",
                    )
                stmt = stmt.where(
                    or_(
                        billing_ledger_entries.c.created_at
                        < anchor.created_at,
                        and_(
                            billing_ledger_entries.c.created_at
                            == anchor.created_at,
                            billing_ledger_entries.c.id < anchor.id,
                        ),
                    ),
                )
            rows = (
                conn.execute(
                    stmt.order_by(
                        billing_ledger_entries.c.created_at.desc(),
                        billing_ledger_entries.c.id.desc(),
                    ).limit(min(limit, 100)),
                )
                .mappings()
                .all()
            )
        return [self._ledger_row(row) for row in rows]

    def _append_grant(self, conn, command: LedgerTransaction) -> None:
        assert command.credit_type is not None
        now = datetime.now(timezone.utc)
        ledger_id = str(uuid4())
        self._insert_ledger(
            conn,
            command,
            ledger_id=ledger_id,
            credit_delta=command.credits,
            now=now,
        )
        conn.execute(
            insert(billing_credit_lots).values(
                id=str(uuid4()),
                wallet_id=command.wallet_id,
                source_ledger_entry_id=ledger_id,
                credit_type=command.credit_type,
                status="active",
                granted_credits=command.credits,
                available_credits=command.credits,
                held_credits=0,
                expires_at=command.expires_at,
                metadata_json=self._json(command.metadata),
                created_at=now,
                updated_at=now,
            ),
        )
        type_column = _TYPE_COLUMNS[command.credit_type]
        conn.execute(
            update(billing_wallets)
            .where(billing_wallets.c.id == command.wallet_id)
            .values(
                available_credits=billing_wallets.c.available_credits
                + command.credits,
                **{type_column.name: type_column + command.credits},
                updated_at=now,
            ),
        )

    def _append_hold(
        self,
        conn,
        command: LedgerTransaction,
        *,
        wallet_available: int,
    ) -> None:
        if wallet_available < command.credits:
            raise InsufficientCreditsError(
                "wallet has "
                f"{wallet_available} available credits; "
                f"{command.credits} requested",
            )
        allocations = self._allocate_lots(
            conn,
            command.wallet_id,
            command.credits,
        )
        if sum(amount for _, amount in allocations) != command.credits:
            raise InsufficientCreditsError(
                "available unexpired credit lots are insufficient",
            )

        now = datetime.now(timezone.utc)
        ledger_id = str(uuid4())
        self._insert_ledger(
            conn,
            command,
            ledger_id=ledger_id,
            credit_delta=0,
            now=now,
        )
        for lot_id, amount in allocations:
            changed = conn.execute(
                update(billing_credit_lots)
                .where(
                    billing_credit_lots.c.id == lot_id,
                    billing_credit_lots.c.available_credits >= amount,
                )
                .values(
                    available_credits=billing_credit_lots.c.available_credits
                    - amount,
                    held_credits=billing_credit_lots.c.held_credits + amount,
                    updated_at=now,
                ),
            )
            if changed.rowcount != 1:
                raise InsufficientCreditsError(
                    "credit lot changed during allocation",
                )
            conn.execute(
                insert(billing_ledger_allocations).values(
                    id=str(uuid4()),
                    ledger_entry_id=ledger_id,
                    credit_lot_id=lot_id,
                    credits=amount,
                    created_at=now,
                ),
            )
        conn.execute(
            update(billing_wallets)
            .where(
                billing_wallets.c.id == command.wallet_id,
                billing_wallets.c.available_credits >= command.credits,
            )
            .values(
                available_credits=billing_wallets.c.available_credits
                - command.credits,
                held_credits=billing_wallets.c.held_credits + command.credits,
                updated_at=now,
            ),
        )

    def _append_release(self, conn, command: LedgerTransaction) -> None:
        prior_release = conn.execute(
            select(billing_ledger_entries.c.id).where(
                billing_ledger_entries.c.wallet_id == command.wallet_id,
                billing_ledger_entries.c.event_type == "usage_release",
                billing_ledger_entries.c.business_key == command.business_key,
            ),
        ).first()
        if prior_release is not None:
            raise BillingInvariantError(
                f"hold already released: {command.business_key}",
            )

        hold_id = conn.execute(
            select(billing_ledger_entries.c.id)
            .where(
                billing_ledger_entries.c.wallet_id == command.wallet_id,
                billing_ledger_entries.c.event_type == "usage_hold",
                billing_ledger_entries.c.business_key == command.business_key,
            )
            .order_by(
                billing_ledger_entries.c.created_at.desc(),
                billing_ledger_entries.c.id.desc(),
            )
            .limit(1),
        ).scalar_one_or_none()
        if hold_id is None:
            raise BillingInvariantError(
                f"hold not found: {command.business_key}",
            )
        allocations = conn.execute(
            select(
                billing_ledger_allocations.c.credit_lot_id,
                billing_ledger_allocations.c.credits,
            ).where(billing_ledger_allocations.c.ledger_entry_id == hold_id),
        ).all()
        released_credits = sum(int(row.credits) for row in allocations)
        if command.credits not in (0, released_credits):
            raise BillingInvariantError(
                "release must compensate the complete hold",
            )

        now = datetime.now(timezone.utc)
        ledger_id = str(uuid4())
        self._insert_ledger(
            conn,
            command,
            ledger_id=ledger_id,
            credit_delta=0,
            now=now,
        )
        for allocation in allocations:
            amount = int(allocation.credits)
            changed = conn.execute(
                update(billing_credit_lots)
                .where(
                    billing_credit_lots.c.id == allocation.credit_lot_id,
                    billing_credit_lots.c.held_credits >= amount,
                )
                .values(
                    available_credits=billing_credit_lots.c.available_credits
                    + amount,
                    held_credits=billing_credit_lots.c.held_credits - amount,
                    updated_at=now,
                ),
            )
            if changed.rowcount != 1:
                raise BillingInvariantError(
                    "held lot projection cannot satisfy release",
                )
            conn.execute(
                insert(billing_ledger_allocations).values(
                    id=str(uuid4()),
                    ledger_entry_id=ledger_id,
                    credit_lot_id=allocation.credit_lot_id,
                    credits=amount,
                    created_at=now,
                ),
            )
        changed = conn.execute(
            update(billing_wallets)
            .where(
                billing_wallets.c.id == command.wallet_id,
                billing_wallets.c.held_credits >= released_credits,
            )
            .values(
                available_credits=billing_wallets.c.available_credits
                + released_credits,
                held_credits=billing_wallets.c.held_credits - released_credits,
                updated_at=now,
            ),
        )
        if changed.rowcount != 1:
            raise BillingInvariantError(
                "wallet held projection cannot satisfy release",
            )

    def _allocate_lots(
        self,
        conn,
        wallet_id: str,
        credits: int,
    ) -> list[tuple[str, int]]:
        now = datetime.now(timezone.utc)
        expiry_is_null = case(
            (billing_credit_lots.c.expires_at.is_(None), 1),
            else_=0,
        )
        type_priority = case(
            (billing_credit_lots.c.credit_type == "promotional", 0),
            (billing_credit_lots.c.credit_type == "package", 1),
            else_=2,
        )
        rows = conn.execute(
            select(billing_credit_lots)
            .where(
                billing_credit_lots.c.wallet_id == wallet_id,
                billing_credit_lots.c.status == "active",
                billing_credit_lots.c.available_credits > 0,
                or_(
                    billing_credit_lots.c.expires_at.is_(None),
                    billing_credit_lots.c.expires_at > now,
                ),
            )
            .order_by(
                expiry_is_null,
                billing_credit_lots.c.expires_at.asc(),
                type_priority,
                billing_credit_lots.c.created_at.asc(),
                billing_credit_lots.c.id.asc(),
            )
            .with_for_update(),
        ).mappings()
        remaining = credits
        allocations: list[tuple[str, int]] = []
        for row in rows:
            amount = min(remaining, int(row["available_credits"]))
            if amount:
                allocations.append((str(row["id"]), amount))
                remaining -= amount
            if remaining == 0:
                break
        return allocations

    def _insert_ledger(
        self,
        conn,
        command: LedgerTransaction,
        *,
        ledger_id: str,
        credit_delta: int,
        now: datetime,
    ) -> None:
        conn.execute(
            insert(billing_ledger_entries).values(
                id=ledger_id,
                wallet_id=command.wallet_id,
                event_type=command.event_type,
                status="committed",
                credit_delta=credit_delta,
                cash_delta_fen=command.cash_delta_fen,
                business_type=command.business_type,
                business_key=command.business_key,
                idempotency_key=command.idempotency_key,
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                reason=command.reason,
                metadata_json=self._json(command.metadata),
                created_at=now,
            ),
        )

    @staticmethod
    def _validate_command(command: LedgerTransaction) -> None:
        if (
            not command.wallet_id
            or not command.business_type
            or not command.business_key
        ):
            raise ValueError(
                "wallet and business references must be non-empty",
            )
        if not command.idempotency_key:
            raise ValueError("ledger idempotency key must be non-empty")
        if command.event_type == "usage_release":
            if command.credits < 0:
                raise ValueError("release credits cannot be negative")
            return
        if command.credits <= 0:
            raise ValueError("transaction credits must be positive")
        if command.event_type in _GRANT_EVENTS:
            if command.credit_type not in _CREDIT_TYPES:
                raise ValueError(
                    "grant commands require a supported credit type",
                )
        elif command.credit_type is not None:
            raise ValueError("only grant commands may specify a credit type")

    @staticmethod
    def _assert_projection(balance: WalletBalance) -> None:
        values = (
            balance.available,
            balance.held,
            balance.purchased,
            balance.promotional,
            balance.package,
        )
        if any(value < 0 for value in values):
            raise BillingInvariantError(
                "wallet projections cannot be negative",
            )
        if balance.available + balance.held != (
            balance.purchased + balance.promotional + balance.package
        ):
            raise BillingInvariantError(
                "wallet total projection is inconsistent",
            )

    @staticmethod
    def _balance_for_update(conn, wallet_id: str) -> WalletBalance:
        row = conn.execute(
            select(
                billing_wallets.c.available_credits,
                billing_wallets.c.held_credits,
                billing_wallets.c.purchased_credits,
                billing_wallets.c.promotional_credits,
                billing_wallets.c.package_credits,
            ).where(billing_wallets.c.id == wallet_id),
        ).one_or_none()
        if row is None:
            raise BillingInvariantError(f"wallet not found: {wallet_id}")
        return WalletBalance(
            available=int(row.available_credits),
            held=int(row.held_credits),
            purchased=int(row.purchased_credits),
            promotional=int(row.promotional_credits),
            package=int(row.package_credits),
        )

    def _idempotency_exists(self, idempotency_key: str) -> bool:
        with self.engine.connect() as conn:
            return (
                conn.execute(
                    select(billing_ledger_entries.c.id).where(
                        billing_ledger_entries.c.idempotency_key
                        == idempotency_key,
                    ),
                ).first()
                is not None
            )

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _ledger_row(row) -> dict[str, Any]:
        result = dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
        return result
