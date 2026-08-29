# -*- coding: utf-8 -*-
"""Transactional wallet and immutable ledger repository."""
# pylint: disable=redefined-builtin
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, case, func, insert, or_, select, update
from sqlalchemy.engine import Connection, Engine
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
    billing_rollout_settings,
    billing_wallets,
    users,
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
    def __init__(
        self,
        engine: Engine,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.engine = engine
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def ensure_wallet(self, owner_type: str, owner_id: str) -> dict[str, Any]:
        if not owner_type.strip() or not owner_id.strip():
            raise ValueError(
                "wallet owner_type and owner_id must be non-empty",
            )

        with self.engine.begin() as conn:
            return self.ensure_wallet_in_connection(conn, owner_type, owner_id)

    def ensure_wallet_in_connection(
        self,
        conn: Connection,
        owner_type: str,
        owner_id: str,
    ) -> dict[str, Any]:
        """Create or recover a wallet inside the caller's transaction."""
        if not owner_type.strip() or not owner_id.strip():
            raise ValueError(
                "wallet owner_type and owner_id must be non-empty",
            )
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
                # sqlite3 does not start its outer transaction for a SELECT.
                # Without a write first, releasing the first savepoint commits
                # the wallet even if a caller later rolls the outer scope back.
                if conn.dialect.name == "sqlite":
                    conn.exec_driver_sql(
                        "UPDATE billing_wallets SET id = id WHERE 0",
                    )
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

    def get_wallet(
        self,
        owner_type: str,
        owner_id: str,
    ) -> dict[str, Any] | None:
        """Return an existing owner wallet without creating one."""
        with self.engine.connect() as conn:
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
        return dict(row) if row is not None else None

    def get_rollout_setting(self) -> dict[str, Any] | None:
        """Return the singleton billing rollout authority, if activated."""
        with self.engine.connect() as conn:
            row = (
                conn.execute(
                    select(billing_rollout_settings).where(
                        billing_rollout_settings.c.id == "global",
                    ),
                )
                .mappings()
                .first()
            )
        return dict(row) if row is not None else None

    def backfill_user_wallets(self) -> None:
        """Idempotently create empty wallets for durable legacy users."""
        with self.engine.connect() as conn:
            user_ids = [
                str(value) for value in conn.scalars(select(users.c.id))
            ]
        for user_id in user_ids:
            self.ensure_wallet("user", user_id)

    def append_transaction(self, command: LedgerTransaction) -> WalletBalance:
        self._validate_command(command)
        try:
            with self.engine.begin() as conn:
                return self.append_transaction_in_connection(conn, command)
        except IntegrityError as exc:
            if self._idempotency_exists(command.idempotency_key):
                raise DuplicateLedgerTransactionError(
                    command.idempotency_key,
                ) from exc
            raise

    def append_transaction_in_connection(
        self,
        conn: Connection,
        command: LedgerTransaction,
    ) -> WalletBalance:
        """Append accounting effects inside a caller-owned transaction."""
        self._validate_command(command)
        wallet = (
            conn.execute(
                self._wallet_for_update_statement(command.wallet_id),
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
            raise DuplicateLedgerTransactionError(command.idempotency_key)

        self._expire_available_lots(
            conn,
            command.wallet_id,
            self._clock(),
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
        elif command.event_type == "usage_capture":
            self._append_capture(conn, command)
        else:
            raise ValueError(
                f"unsupported ledger event type: {command.event_type}",
            )

        balance = self._balance_for_update(conn, command.wallet_id)
        self._assert_projection(conn, command.wallet_id, balance)
        return balance

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
        capability: str | None = None,
        tier: str | None = None,
    ) -> WalletBalance:
        return self.append_transaction(
            LedgerTransaction(
                wallet_id=wallet_id,
                event_type="usage_hold",
                credits=credits,
                business_type="usage",
                business_key=business_key,
                idempotency_key=idempotency_key,
                metadata={"capability": capability, "tier": tier},
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

    def capture(
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
                event_type="usage_capture",
                credits=credits,
                business_type="usage",
                business_key=business_key,
                idempotency_key=idempotency_key,
            ),
        )

    def held_usage_credits_in_connection(
        self,
        conn: Connection,
        wallet_id: str,
        business_keys: list[str],
    ) -> int:
        """Sum durable hold allocations for still-active usage items.

        Callers pass only items whose state still retains a hold.  This keeps
        reporting tied to immutable allocation rows instead of caller input or
        an asynchronous token queue.
        """
        if not business_keys:
            return 0
        total = conn.scalar(
            select(
                func.coalesce(
                    func.sum(billing_ledger_allocations.c.credits),
                    0,
                ),
            )
            .select_from(
                billing_ledger_allocations.join(
                    billing_ledger_entries,
                    billing_ledger_allocations.c.ledger_entry_id
                    == billing_ledger_entries.c.id,
                ),
            )
            .where(
                billing_ledger_entries.c.wallet_id == wallet_id,
                billing_ledger_entries.c.event_type == "usage_hold",
                billing_ledger_entries.c.business_key.in_(business_keys),
            ),
        )
        return int(total or 0)

    def evaluate_hold_in_connection(
        self,
        conn: Connection,
        wallet_id: str,
        credits: int,
        *,
        capability: str,
        tier: str,
    ) -> tuple[bool, str | None]:
        """Plan the same lot allocation as a hold without accounting writes."""
        allocations, available = self._lot_allocation_plan(
            conn,
            wallet_id,
            credits,
            capability=capability,
            tier=tier,
        )
        if sum(amount for _, amount in allocations) == credits:
            return True, None
        if available < credits:
            return False, "insufficient_credits"
        return False, "ineligible_credit_lots"

    def balance(self, wallet_id: str) -> WalletBalance:
        with self.engine.begin() as conn:
            wallet = conn.execute(
                self._wallet_for_update_statement(wallet_id),
            ).first()
            if wallet is None:
                raise BillingInvariantError(f"wallet not found: {wallet_id}")
            self._expire_available_lots(conn, wallet_id, self._clock())
            balance = self._balance_for_update(conn, wallet_id)
            self._assert_projection(conn, wallet_id, balance)
            return balance

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

    def _expire_available_lots(
        self,
        conn,
        wallet_id: str,
        now: datetime,
    ) -> None:
        rows = (
            conn.execute(
                select(billing_credit_lots)
                .where(
                    billing_credit_lots.c.wallet_id == wallet_id,
                    billing_credit_lots.c.available_credits > 0,
                    billing_credit_lots.c.expires_at.is_not(None),
                    billing_credit_lots.c.expires_at <= now,
                )
                .order_by(
                    billing_credit_lots.c.expires_at.asc(),
                    billing_credit_lots.c.created_at.asc(),
                    billing_credit_lots.c.id.asc(),
                )
                .with_for_update(),
            )
            .mappings()
            .all()
        )
        for lot in rows:
            amount = int(lot["available_credits"])
            lot_id = str(lot["id"])
            ledger_id = str(uuid4())
            self._insert_ledger(
                conn,
                LedgerTransaction(
                    wallet_id=wallet_id,
                    event_type="credit_expiry",
                    credits=amount,
                    business_type="credit_lot",
                    business_key=lot_id,
                    idempotency_key=f"credit-expiry:available:{lot_id}",
                    metadata={
                        "expiry_phase": "available",
                        "source_ledger_entry_id": lot[
                            "source_ledger_entry_id"
                        ],
                    },
                ),
                ledger_id=ledger_id,
                credit_delta=-amount,
                now=now,
            )
            changed_lot = conn.execute(
                update(billing_credit_lots)
                .where(
                    billing_credit_lots.c.id == lot_id,
                    billing_credit_lots.c.available_credits == amount,
                )
                .values(
                    status="expired",
                    available_credits=0,
                    updated_at=now,
                ),
            )
            if changed_lot.rowcount != 1:
                raise BillingInvariantError(
                    "credit lot changed during expiry",
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
            type_column = _TYPE_COLUMNS[str(lot["credit_type"])]
            changed_wallet = conn.execute(
                update(billing_wallets)
                .where(
                    billing_wallets.c.id == wallet_id,
                    billing_wallets.c.available_credits >= amount,
                    type_column >= amount,
                )
                .values(
                    available_credits=billing_wallets.c.available_credits
                    - amount,
                    **{type_column.name: type_column - amount},
                    updated_at=now,
                ),
            )
            if changed_wallet.rowcount != 1:
                raise BillingInvariantError(
                    "wallet changed during credit expiry",
                )

    def _append_grant(self, conn, command: LedgerTransaction) -> None:
        assert command.credit_type is not None
        now = self._clock()
        if command.expires_at is not None and command.expires_at <= now:
            raise ValueError("grant expiry must be in the future")
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
        changed_wallet = conn.execute(
            update(billing_wallets)
            .where(billing_wallets.c.id == command.wallet_id)
            .values(
                available_credits=billing_wallets.c.available_credits
                + command.credits,
                **{type_column.name: type_column + command.credits},
                updated_at=now,
            ),
        )
        if changed_wallet.rowcount != 1:
            raise BillingInvariantError("wallet changed during grant")

    def _append_hold(
        self,
        conn,
        command: LedgerTransaction,
        *,
        wallet_available: int,
    ) -> None:
        existing_hold = conn.execute(
            select(billing_ledger_entries.c.id).where(
                billing_ledger_entries.c.wallet_id == command.wallet_id,
                billing_ledger_entries.c.event_type == "usage_hold",
                billing_ledger_entries.c.business_key == command.business_key,
            ),
        ).first()
        if existing_hold is not None:
            raise BillingInvariantError(
                f"hold already exists: {command.business_key}",
            )
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
            capability=str(command.metadata.get("capability") or ""),
            tier=str(command.metadata.get("tier") or ""),
        )
        if sum(amount for _, amount in allocations) != command.credits:
            raise InsufficientCreditsError(
                "available unexpired credit lots are insufficient",
            )

        now = self._clock()
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
        changed_wallet = conn.execute(
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
        if changed_wallet.rowcount != 1:
            raise BillingInvariantError("wallet changed during hold")

    def _append_release(self, conn, command: LedgerTransaction) -> None:
        prior_settlement = conn.execute(
            select(billing_ledger_entries.c.id).where(
                billing_ledger_entries.c.wallet_id == command.wallet_id,
                billing_ledger_entries.c.event_type.in_(
                    ("usage_release", "usage_capture"),
                ),
                billing_ledger_entries.c.business_key == command.business_key,
            ),
        ).first()
        if prior_settlement is not None:
            raise BillingInvariantError(
                f"hold already settled: {command.business_key}",
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
        now = self._clock()
        allocations = conn.execute(
            select(
                billing_ledger_allocations.c.credit_lot_id,
                billing_ledger_allocations.c.credits,
                billing_credit_lots.c.credit_type,
                (billing_credit_lots.c.expires_at <= now).label(
                    "is_expired",
                ),
            )
            .select_from(
                billing_ledger_allocations.join(
                    billing_credit_lots,
                    billing_ledger_allocations.c.credit_lot_id
                    == billing_credit_lots.c.id,
                ),
            )
            .where(billing_ledger_allocations.c.ledger_entry_id == hold_id),
        ).all()
        released_credits = sum(int(row.credits) for row in allocations)
        if command.credits not in (0, released_credits):
            raise BillingInvariantError(
                "release must compensate the complete hold",
            )
        ledger_id = str(uuid4())
        self._insert_ledger(
            conn,
            replace(
                command,
                metadata={
                    **command.metadata,
                    "source_ledger_entry_id": hold_id,
                },
            ),
            ledger_id=ledger_id,
            credit_delta=0,
            now=now,
        )
        restored_available = 0
        expired_by_type = {credit_type: 0 for credit_type in _CREDIT_TYPES}
        expired_allocations: list[tuple[str, int]] = []
        for allocation in allocations:
            amount = int(allocation.credits)
            is_expired = bool(allocation.is_expired)
            lot_values: dict[str, Any] = {
                "held_credits": billing_credit_lots.c.held_credits - amount,
                "updated_at": now,
            }
            if is_expired:
                lot_values["status"] = "expired"
                expired_by_type[str(allocation.credit_type)] += amount
                expired_allocations.append(
                    (str(allocation.credit_lot_id), amount),
                )
            else:
                lot_values["available_credits"] = (
                    billing_credit_lots.c.available_credits + amount
                )
                restored_available += amount
            changed = conn.execute(
                update(billing_credit_lots)
                .where(
                    billing_credit_lots.c.id == allocation.credit_lot_id,
                    billing_credit_lots.c.held_credits >= amount,
                )
                .values(**lot_values),
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
        expired_credits = sum(expired_by_type.values())
        if expired_credits:
            expiry_ledger_id = str(uuid4())
            self._insert_ledger(
                conn,
                LedgerTransaction(
                    wallet_id=command.wallet_id,
                    event_type="credit_expiry",
                    credits=expired_credits,
                    business_type="usage_hold",
                    business_key=hold_id,
                    idempotency_key=f"credit-expiry:held:{hold_id}",
                    metadata={
                        "expiry_phase": "held_release",
                        "source_ledger_entry_id": hold_id,
                        "release_ledger_entry_id": ledger_id,
                    },
                ),
                ledger_id=expiry_ledger_id,
                credit_delta=-expired_credits,
                now=now,
            )
            for lot_id, amount in expired_allocations:
                conn.execute(
                    insert(billing_ledger_allocations).values(
                        id=str(uuid4()),
                        ledger_entry_id=expiry_ledger_id,
                        credit_lot_id=lot_id,
                        credits=amount,
                        created_at=now,
                    ),
                )
        wallet_values: dict[str, Any] = {
            "available_credits": billing_wallets.c.available_credits
            + restored_available,
            "held_credits": billing_wallets.c.held_credits - released_credits,
            "updated_at": now,
        }
        wallet_guards = [
            billing_wallets.c.id == command.wallet_id,
            billing_wallets.c.held_credits >= released_credits,
        ]
        for credit_type, expired_amount in expired_by_type.items():
            if expired_amount:
                type_column = _TYPE_COLUMNS[credit_type]
                wallet_values[type_column.name] = type_column - expired_amount
                wallet_guards.append(type_column >= expired_amount)
        changed = conn.execute(
            update(billing_wallets)
            .where(*wallet_guards)
            .values(**wallet_values),
        )
        if changed.rowcount != 1:
            raise BillingInvariantError(
                "wallet held projection cannot satisfy release",
            )

    # pylint: disable=too-many-branches,too-many-statements
    def _append_capture(self, conn, command: LedgerTransaction) -> None:
        prior_settlement = conn.execute(
            select(billing_ledger_entries.c.id).where(
                billing_ledger_entries.c.wallet_id == command.wallet_id,
                billing_ledger_entries.c.event_type.in_(
                    ("usage_capture", "usage_release"),
                ),
                billing_ledger_entries.c.business_key == command.business_key,
            ),
        ).first()
        if prior_settlement is not None:
            raise BillingInvariantError(
                f"hold already settled: {command.business_key}",
            )

        hold_id = conn.execute(
            select(billing_ledger_entries.c.id)
            .where(
                billing_ledger_entries.c.wallet_id == command.wallet_id,
                billing_ledger_entries.c.event_type == "usage_hold",
                billing_ledger_entries.c.business_key == command.business_key,
            )
            .limit(1),
        ).scalar_one_or_none()
        if hold_id is None:
            raise BillingInvariantError(
                f"hold not found: {command.business_key}",
            )

        now = self._clock()
        expiry_is_null = case(
            (billing_credit_lots.c.expires_at.is_(None), 1),
            else_=0,
        )
        type_priority = case(
            (billing_credit_lots.c.credit_type == "promotional", 0),
            (billing_credit_lots.c.credit_type == "package", 1),
            else_=2,
        )
        allocations = conn.execute(
            select(
                billing_ledger_allocations.c.credit_lot_id,
                billing_ledger_allocations.c.credits,
                billing_credit_lots.c.credit_type,
                (billing_credit_lots.c.expires_at <= now).label(
                    "is_expired",
                ),
            )
            .select_from(
                billing_ledger_allocations.join(
                    billing_credit_lots,
                    billing_ledger_allocations.c.credit_lot_id
                    == billing_credit_lots.c.id,
                ),
            )
            .where(billing_ledger_allocations.c.ledger_entry_id == hold_id)
            .order_by(
                expiry_is_null,
                billing_credit_lots.c.expires_at.asc(),
                type_priority,
                billing_credit_lots.c.created_at.asc(),
                billing_credit_lots.c.id.asc(),
            ),
        ).all()
        held_credits = sum(int(row.credits) for row in allocations)
        if command.credits > held_credits:
            raise BillingInvariantError(
                "capture cannot exceed the complete hold",
            )

        capture_ledger_id = str(uuid4())
        self._insert_ledger(
            conn,
            replace(
                command,
                metadata={
                    **command.metadata,
                    "source_ledger_entry_id": hold_id,
                },
            ),
            ledger_id=capture_ledger_id,
            credit_delta=-command.credits,
            now=now,
        )
        released_credits = held_credits - command.credits
        release_ledger_id = str(uuid4()) if released_credits else None
        if release_ledger_id is not None:
            self._insert_ledger(
                conn,
                replace(
                    command,
                    event_type="usage_release",
                    credits=0,
                    idempotency_key=f"{command.idempotency_key}:remainder",
                    metadata={
                        **command.metadata,
                        "source_ledger_entry_id": hold_id,
                        "partial_capture_ledger_entry_id": capture_ledger_id,
                    },
                ),
                ledger_id=release_ledger_id,
                credit_delta=0,
                now=now,
            )

        captured_by_type = {credit_type: 0 for credit_type in _CREDIT_TYPES}
        expired_by_type = {credit_type: 0 for credit_type in _CREDIT_TYPES}
        expired_allocations: list[tuple[str, int]] = []
        restored_available = 0
        remaining_capture = command.credits
        for allocation in allocations:
            amount = int(allocation.credits)
            captured = min(remaining_capture, amount)
            released = amount - captured
            remaining_capture -= captured
            is_expired = bool(allocation.is_expired)
            lot_values: dict[str, Any] = {
                "held_credits": billing_credit_lots.c.held_credits - amount,
                "updated_at": now,
            }
            if released and is_expired:
                lot_values["status"] = "expired"
                expired_by_type[str(allocation.credit_type)] += released
                expired_allocations.append(
                    (str(allocation.credit_lot_id), released),
                )
            elif released:
                lot_values["available_credits"] = (
                    billing_credit_lots.c.available_credits + released
                )
                restored_available += released
            changed = conn.execute(
                update(billing_credit_lots)
                .where(
                    billing_credit_lots.c.id == allocation.credit_lot_id,
                    billing_credit_lots.c.held_credits >= amount,
                )
                .values(**lot_values),
            )
            if changed.rowcount != 1:
                raise BillingInvariantError(
                    "held lot projection cannot satisfy capture",
                )
            if captured:
                conn.execute(
                    insert(billing_ledger_allocations).values(
                        id=str(uuid4()),
                        ledger_entry_id=capture_ledger_id,
                        credit_lot_id=allocation.credit_lot_id,
                        credits=captured,
                        created_at=now,
                    ),
                )
                captured_by_type[str(allocation.credit_type)] += captured
            if released and release_ledger_id is not None:
                conn.execute(
                    insert(billing_ledger_allocations).values(
                        id=str(uuid4()),
                        ledger_entry_id=release_ledger_id,
                        credit_lot_id=allocation.credit_lot_id,
                        credits=released,
                        created_at=now,
                    ),
                )

        expired_credits = sum(expired_by_type.values())
        if expired_credits:
            expiry_ledger_id = str(uuid4())
            self._insert_ledger(
                conn,
                LedgerTransaction(
                    wallet_id=command.wallet_id,
                    event_type="credit_expiry",
                    credits=expired_credits,
                    business_type="usage_hold",
                    business_key=hold_id,
                    idempotency_key=(
                        f"credit-expiry:partial-capture:{hold_id}"
                    ),
                    metadata={
                        "expiry_phase": "partial_capture_release",
                        "source_ledger_entry_id": hold_id,
                        "capture_ledger_entry_id": capture_ledger_id,
                    },
                ),
                ledger_id=expiry_ledger_id,
                credit_delta=-expired_credits,
                now=now,
            )
            for lot_id, amount in expired_allocations:
                conn.execute(
                    insert(billing_ledger_allocations).values(
                        id=str(uuid4()),
                        ledger_entry_id=expiry_ledger_id,
                        credit_lot_id=lot_id,
                        credits=amount,
                        created_at=now,
                    ),
                )

        wallet_values: dict[str, Any] = {
            "available_credits": billing_wallets.c.available_credits
            + restored_available,
            "held_credits": billing_wallets.c.held_credits - held_credits,
            "updated_at": now,
        }
        wallet_guards = [
            billing_wallets.c.id == command.wallet_id,
            billing_wallets.c.held_credits >= held_credits,
        ]
        for credit_type in _CREDIT_TYPES:
            amount = (
                captured_by_type[credit_type] + expired_by_type[credit_type]
            )
            if amount:
                type_column = _TYPE_COLUMNS[credit_type]
                wallet_values[type_column.name] = type_column - amount
                wallet_guards.append(type_column >= amount)
        changed = conn.execute(
            update(billing_wallets)
            .where(*wallet_guards)
            .values(**wallet_values),
        )
        if changed.rowcount != 1:
            raise BillingInvariantError(
                "wallet held projection cannot satisfy capture",
            )

    def _allocate_lots(
        self,
        conn,
        wallet_id: str,
        credits: int,
        *,
        capability: str,
        tier: str,
    ) -> list[tuple[str, int]]:
        allocations, _available = self._lot_allocation_plan(
            conn,
            wallet_id,
            credits,
            capability=capability,
            tier=tier,
        )
        return allocations

    def _lot_allocation_plan(
        self,
        conn,
        wallet_id: str,
        credits: int,
        *,
        capability: str,
        tier: str,
    ) -> tuple[list[tuple[str, int]], int]:
        rows = list(
            conn.execute(
                self._available_lots_for_update_statement(
                    wallet_id,
                    credits,
                    self._clock(),
                ),
            ).mappings(),
        )
        remaining = credits
        allocations: list[tuple[str, int]] = []
        for row in rows:
            if not _lot_is_eligible(row, capability=capability, tier=tier):
                continue
            amount = min(remaining, int(row["available_credits"]))
            if amount:
                allocations.append((str(row["id"]), amount))
                remaining -= amount
            if remaining == 0:
                break
        return allocations, sum(int(row["available_credits"]) for row in rows)

    @staticmethod
    def _wallet_for_update_statement(wallet_id: str):
        return (
            select(billing_wallets)
            .where(billing_wallets.c.id == wallet_id)
            .with_for_update()
        )

    @staticmethod
    def _available_lots_for_update_statement(
        wallet_id: str,
        credits: int,
        now: datetime,
    ):
        expiry_is_null = case(
            (billing_credit_lots.c.expires_at.is_(None), 1),
            else_=0,
        )
        type_priority = case(
            (billing_credit_lots.c.credit_type == "promotional", 0),
            (billing_credit_lots.c.credit_type == "package", 1),
            else_=2,
        )
        return (
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
            .limit(credits)
            .with_for_update()
        )

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
            if (
                command.credit_type == "purchased"
                and command.expires_at is not None
            ):
                raise ValueError("purchased credits cannot expire")
        elif command.credit_type is not None:
            raise ValueError("only grant commands may specify a credit type")

    @staticmethod
    def _assert_projection(
        conn,
        wallet_id: str,
        balance: WalletBalance,
    ) -> None:
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
        lot_rows = conn.execute(
            select(
                billing_credit_lots.c.credit_type,
                billing_credit_lots.c.available_credits,
                billing_credit_lots.c.held_credits,
            ).where(billing_credit_lots.c.wallet_id == wallet_id),
        )
        lot_available = 0
        lot_held = 0
        lot_types = {credit_type: 0 for credit_type in _CREDIT_TYPES}
        for row in lot_rows:
            available = int(row.available_credits)
            held = int(row.held_credits)
            lot_available += available
            lot_held += held
            lot_types[str(row.credit_type)] += available + held
        expected = WalletBalance(
            available=lot_available,
            held=lot_held,
            purchased=lot_types["purchased"],
            promotional=lot_types["promotional"],
            package=lot_types["package"],
        )
        if balance != expected:
            raise BillingInvariantError(
                "wallet projection does not match credit lot projections",
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


def _lot_is_eligible(row, *, capability: str, tier: str) -> bool:
    metadata = json.loads(row["metadata_json"] or "{}")
    if metadata.get("grant_policy") != "signup_trial":
        return True
    normalized_capability = capability.strip().lower()
    normalized_tier = tier.strip().lower()
    if not normalized_capability or not normalized_tier:
        return False
    capability_groups = {
        "chat": "text",
        "text": "text",
        "text_generation": "text",
        "text_to_image": "image",
        "image_to_image": "image",
        "image_edit": "image",
        "image_generation": "image",
        "text_to_video": "video",
        "image_to_video": "video",
        "video_generation": "video",
        "fixed_workflow": "fixed_workflow",
    }
    capability_group = capability_groups.get(normalized_capability)
    denied = {
        str(value).lower() for value in metadata.get("denied_capabilities", [])
    }
    if (
        capability_group is None
        or capability_group in denied
        or normalized_capability in denied
    ):
        return False
    if normalized_tier == "high_cost" and "high_cost" in denied:
        return False
    allowed = {
        str(value).lower()
        for value in metadata.get("allowed_capabilities", [])
    }
    if allowed and capability_group not in allowed:
        return False
    allowed_tiers = {
        str(value).lower() for value in metadata.get("allowed_tiers", [])
    }
    return bool(allowed_tiers) and normalized_tier in allowed_tiers
