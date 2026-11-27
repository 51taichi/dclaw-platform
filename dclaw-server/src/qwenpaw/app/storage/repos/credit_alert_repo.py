from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Connection, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..schema import (
    billing_wallets,
    credit_alert_events,
    credit_alert_preferences,
    credit_alert_states,
    users,
)


class CreditAlertRepository:
    def states_exist(self, conn: Connection, user_id: int) -> bool:
        return conn.execute(select(credit_alert_states.c.user_id).where(
            credit_alert_states.c.user_id == user_id,
        ).limit(1)).first() is not None

    def ensure_preferences(self, conn: Connection, user_id: int) -> dict[str, Any]:
        self._insert_ignore(conn, credit_alert_preferences, {"user_id": user_id}, ["user_id"])
        row = conn.execute(select(credit_alert_preferences).where(
            credit_alert_preferences.c.user_id == user_id,
        )).mappings().one()
        return dict(row)

    def ensure_states(self, conn: Connection, user_id: int) -> list[dict[str, Any]]:
        for tier in ("warning", "critical"):
            self._insert_ignore(
                conn, credit_alert_states, {"user_id": user_id, "tier": tier},
                ["user_id", "tier"],
            )
        rows = conn.execute(select(credit_alert_states).where(
            credit_alert_states.c.user_id == user_id,
        ).with_for_update()).mappings().all()
        return [dict(row) for row in rows]

    def user_for_wallet(self, conn: Connection, wallet_id: str) -> int | None:
        value = conn.execute(select(billing_wallets.c.owner_id).where(
            billing_wallets.c.id == wallet_id,
            billing_wallets.c.owner_type == "user",
        )).scalar_one_or_none()
        try:
            return int(value) if value is not None else None
        except ValueError:
            return None

    def identity(self, conn: Connection, user_id: int) -> dict[str, Any] | None:
        row = conn.execute(select(
            users.c.display_name, users.c.phone_number_e164,
        ).where(users.c.id == user_id)).mappings().first()
        return dict(row) if row else None

    def update_preferences(
        self, conn: Connection, user_id: int, warning_threshold: int, critical_threshold: int,
    ) -> None:
        conn.execute(update(credit_alert_preferences).where(
            credit_alert_preferences.c.user_id == user_id,
        ).values(
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
            updated_at=datetime.now(timezone.utc),
        ))

    def update_state(self, conn: Connection, user_id: int, tier: str, **values: Any) -> None:
        values["updated_at"] = datetime.now(timezone.utc)
        conn.execute(update(credit_alert_states).where(
            credit_alert_states.c.user_id == user_id,
            credit_alert_states.c.tier == tier,
        ).values(**values))

    def create_event(
        self, conn: Connection, *, event_id: str, user_id: int, tier: str, cycle_number: int,
        available: int, threshold: int, display_name: str | None,
        phone_number: str | None, sms_status: str,
    ) -> bool:
        values = {
            "id": event_id, "user_id": user_id, "tier": tier,
            "cycle_number": cycle_number, "available_balance": available,
            "threshold": threshold, "display_name_snapshot": display_name,
            "phone_number_snapshot": phone_number, "sms_status": sms_status,
        }
        return self._insert_ignore(
            conn, credit_alert_events, values, ["user_id", "tier", "cycle_number"],
        )

    def record_submission_result(
        self,
        conn: Connection,
        *,
        event_id: str,
        status: str,
        provider_message_id: str | None,
        provider_error: str | None,
        attempted: bool,
    ) -> None:
        now = datetime.now(timezone.utc)
        values: dict[str, Any] = {
            "sms_status": status,
            "provider_message_id": provider_message_id,
            "provider_error": provider_error,
            "updated_at": now,
        }
        if attempted:
            values["attempt_count"] = credit_alert_events.c.attempt_count + 1
        if status == "submitted":
            values["submitted_at"] = now
        conn.execute(update(credit_alert_events).where(
            credit_alert_events.c.id == event_id,
        ).values(**values))

    @staticmethod
    def _insert_ignore(
        conn: Connection, table: Any, values: dict[str, Any], conflict_columns: list[str],
    ) -> bool:
        if conn.dialect.name == "sqlite":
            statement = sqlite_insert(table).values(**values).on_conflict_do_nothing(
                index_elements=conflict_columns,
            )
        elif conn.dialect.name == "postgresql":
            statement = pg_insert(table).values(**values).on_conflict_do_nothing(
                index_elements=conflict_columns,
            )
        else:
            statement = insert(table).values(**values)
        return bool(conn.execute(statement).rowcount)
