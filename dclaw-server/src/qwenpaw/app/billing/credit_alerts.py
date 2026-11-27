from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy.engine import Connection, Engine

from ..notifications.sms import (
    SmsAlert,
    SmsSender,
    SmsSubmissionResult,
    get_sms_sender,
)
from ..storage.repos.billing_repo import BillingRepository
from ..storage.repos.credit_alert_repo import CreditAlertRepository

MAX_THRESHOLD = 2**63 - 1
Cause = Literal[
    "balance_change", "expiry", "reconciliation", "preference_change", "recovery",
]


class AlertTierNotFound(ValueError):
    pass


class AlertConflict(ValueError):
    pass


class CreditAlertService:
    def __init__(
        self, engine: Engine, repository: CreditAlertRepository | None = None,
        sender: SmsSender | None = None,
    ) -> None:
        self.engine = engine
        self.repository = repository or CreditAlertRepository()
        self.sender = sender
        self._lock = RLock()

    def get(self, user_id: int, available: int) -> dict[str, Any]:
        with self._lock, self.engine.begin() as conn:
            self._reconcile_user(conn, user_id, available, cause="reconciliation")
            return self._resource(conn, user_id, available)

    def get_for_wallet(self, user_id: int, wallet_id: str) -> dict[str, Any]:
        with self._lock, self.engine.begin() as conn:
            available, cause = self._locked_wallet_context(
                conn, user_id, wallet_id,
            )
            self._reconcile_user(conn, user_id, available, cause=cause)
            return self._resource(conn, user_id, available)

    def update_preferences(
        self, user_id: int, warning_threshold: int, critical_threshold: int, available: int,
    ) -> dict[str, Any]:
        self._validate_thresholds(warning_threshold, critical_threshold)
        with self._lock, self.engine.begin() as conn:
            self.repository.ensure_preferences(conn, user_id)
            self.repository.ensure_states(conn, user_id)
            self.repository.update_preferences(
                conn, user_id, warning_threshold, critical_threshold,
            )
            self._reconcile_user(conn, user_id, available, cause="preference_change")
            return self._resource(conn, user_id, available)

    def update_preferences_for_wallet(
        self,
        user_id: int,
        wallet_id: str,
        warning_threshold: int,
        critical_threshold: int,
    ) -> dict[str, Any]:
        self._validate_thresholds(warning_threshold, critical_threshold)
        with self._lock, self.engine.begin() as conn:
            available, _ = self._locked_wallet_context(
                conn, user_id, wallet_id,
            )
            self.repository.ensure_preferences(conn, user_id)
            self.repository.ensure_states(conn, user_id)
            self.repository.update_preferences(
                conn, user_id, warning_threshold, critical_threshold,
            )
            self._reconcile_user(
                conn, user_id, available, cause="preference_change",
            )
            return self._resource(conn, user_id, available)

    def dismiss(self, user_id: int, tier: str, available: int) -> dict[str, Any]:
        if tier not in ("warning", "critical"):
            raise AlertTierNotFound(tier)
        with self._lock, self.engine.begin() as conn:
            self._reconcile_user(conn, user_id, available, cause="reconciliation")
            states = {row["tier"]: row for row in self.repository.ensure_states(conn, user_id)}
            visible = self._visible(states)
            if visible and visible["tier"] == tier:
                now = datetime.now(timezone.utc)
                self.repository.update_state(
                    conn, user_id, tier, status="dismissed", dismissed_at=now,
                )
            elif states[tier]["status"] != "dismissed":
                raise AlertConflict("tier is not the visible active alert")
            return self._resource(conn, user_id, available)

    def dismiss_for_wallet(
        self, user_id: int, wallet_id: str, tier: str,
    ) -> dict[str, Any]:
        if tier not in ("warning", "critical"):
            raise AlertTierNotFound(tier)
        with self._lock, self.engine.begin() as conn:
            available, cause = self._locked_wallet_context(
                conn, user_id, wallet_id,
            )
            self._reconcile_user(conn, user_id, available, cause=cause)
            states = {
                row["tier"]: row
                for row in self.repository.ensure_states(conn, user_id)
            }
            visible = self._visible(states)
            if visible and visible["tier"] == tier:
                self.repository.update_state(
                    conn, user_id, tier, status="dismissed",
                    dismissed_at=datetime.now(timezone.utc),
                )
            elif states[tier]["status"] != "dismissed":
                raise AlertConflict("tier is not the visible active alert")
            return self._resource(conn, user_id, available)

    def reconcile_in_connection(
        self, conn: Connection, wallet_id: str, available: int, *, cause: Cause,
    ) -> None:
        with self._lock:
            user_id = self.repository.user_for_wallet(conn, wallet_id)
            if user_id is not None and self.repository.identity(conn, user_id) is not None:
                effective_cause = cause
                if not self.repository.states_exist(conn, user_id):
                    effective_cause = "reconciliation"
                self._reconcile_user(
                    conn, user_id, available, cause=effective_cause,
                )

    def _reconcile_user(
        self, conn: Connection, user_id: int, available: int, *, cause: Cause,
    ) -> None:
        preferences = self.repository.ensure_preferences(conn, user_id)
        current = {row["tier"]: row for row in self.repository.ensure_states(conn, user_id)}
        thresholds = {
            "warning": int(preferences["warning_threshold"]),
            "critical": int(preferences["critical_threshold"]),
        }

        for tier, threshold in thresholds.items():
            if available > threshold and current[tier]["status"] != "armed":
                self.repository.update_state(
                    conn, user_id, tier, status="armed", activation_source=None,
                    trigger_balance=None, triggered_at=None, dismissed_at=None,
                    rearmed_at=datetime.now(timezone.utc),
                )
                current[tier]["status"] = "armed"

        eligible = [
            tier for tier in ("critical", "warning")
            if available <= thresholds[tier] and current[tier]["status"] == "armed"
        ]
        if not eligible:
            return
        selected = eligible[0]
        source = (
            "crossing"
            if cause in ("balance_change", "expiry", "recovery")
            else "reconciliation"
        )
        now = datetime.now(timezone.utc)
        cycle = int(current[selected]["cycle_number"])
        if source == "crossing":
            cycle += 1
        self.repository.update_state(
            conn, user_id, selected, status="active", cycle_number=cycle,
            activation_source=source, trigger_balance=available, triggered_at=now,
            dismissed_at=None,
        )
        if selected == "critical" and available <= thresholds["warning"]:
            self.repository.update_state(
                conn, user_id, "warning", status="superseded",
                activation_source=source, trigger_balance=available, triggered_at=now,
            )
        if source == "crossing":
            identity = self.repository.identity(conn, user_id) or {}
            phone = identity.get("phone_number_e164")
            event_id = str(uuid4())
            if not phone:
                self.repository.create_event(
                    conn, event_id=event_id, user_id=user_id, tier=selected,
                    cycle_number=cycle, available=available,
                    threshold=thresholds[selected],
                    display_name=identity.get("display_name"),
                    phone_number=None, sms_status="skipped_missing_phone",
                )
                return
            created = self.repository.create_event(
                conn, event_id=event_id, user_id=user_id, tier=selected,
                cycle_number=cycle, available=available,
                threshold=thresholds[selected],
                display_name=identity.get("display_name"), phone_number=phone,
                sms_status="pending",
            )
            if not created:
                return
            try:
                sender = self.sender or get_sms_sender()
                result = sender.send(SmsAlert(
                    event_id=event_id, phone_number=phone,
                    display_name=identity.get("display_name"), tier=selected,
                    available=available, threshold=thresholds[selected],
                ))
            except Exception as exc:  # noqa: BLE001 - alerts cannot abort billing
                result = SmsSubmissionResult(
                    status="failed",
                    provider_error=(
                        f"{type(exc).__name__}: {exc}"
                    )[:2000],
                    attempted=True,
                )
            if result.status not in {
                "skipped_unconfigured", "submitted", "failed",
            }:
                result = SmsSubmissionResult(
                    status="failed",
                    provider_error=f"invalid_sender_status:{result.status}"[:2000],
                    attempted=result.attempted,
                )
            self.repository.record_submission_result(
                conn,
                event_id=event_id,
                status=result.status,
                provider_message_id=result.provider_message_id,
                provider_error=result.provider_error,
                attempted=result.attempted,
            )

    def _locked_wallet_context(
        self, conn: Connection, user_id: int, wallet_id: str,
    ) -> tuple[int, Cause]:
        balance, expired = BillingRepository(
            self.engine,
        ).balance_for_alert_in_connection(conn, wallet_id)
        if self.repository.user_for_wallet(conn, wallet_id) != user_id:
            raise AlertConflict("wallet does not belong to user")
        states_preexisting = self.repository.states_exist(conn, user_id)
        if not states_preexisting:
            cause: Cause = "reconciliation"
        elif expired:
            cause = "expiry"
        else:
            cause = "recovery"
        return balance.available, cause

    @staticmethod
    def _validate_thresholds(
        warning_threshold: int, critical_threshold: int,
    ) -> None:
        if not 0 <= critical_threshold < warning_threshold <= MAX_THRESHOLD:
            raise ValueError(
                "thresholds must satisfy "
                "0 <= critical < warning <= 9223372036854775807",
            )

    def _resource(self, conn: Connection, user_id: int, available: int) -> dict[str, Any]:
        preferences = self.repository.ensure_preferences(conn, user_id)
        states = {row["tier"]: row for row in self.repository.ensure_states(conn, user_id)}
        visible = self._visible(states)
        alert = None
        if visible:
            tier = visible["tier"]
            alert = {
                "tier": tier,
                "threshold": int(preferences[f"{tier}_threshold"]),
                "available": available,
                "triggered_at": visible["triggered_at"],
            }
        return {
            "preferences": {
                "warning_threshold": int(preferences["warning_threshold"]),
                "critical_threshold": int(preferences["critical_threshold"]),
            },
            "available": available,
            "alert": alert,
        }

    @staticmethod
    def _visible(states: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        for tier in ("critical", "warning"):
            if states[tier]["status"] == "active":
                return states[tier]
        return None
