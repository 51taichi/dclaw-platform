from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import insert, select

from qwenpaw.app.billing.credit_alerts import CreditAlertService
from qwenpaw.app.notifications.sms import DisabledSmsSender, SmsAlert
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.schema import (
    billing_wallets, create_all, credit_alert_events, credit_alert_states, users,
)
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def alert_env(tmp_path):
    engine = create_engine_from_settings(get_storage_settings({
        "QWENPAW_SQLITE_PATH": str(tmp_path / "alerts.db"),
    }))
    create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(users), {
            "id": 1, "username": "alice", "password_hash": "h", "password_salt": "s",
            "display_name": "Alice", "phone_number_e164": "+8613800138000",
        })
        conn.execute(insert(users), {
            "id": 2, "username": "legacy", "password_hash": "h", "password_salt": "s",
        })
        conn.execute(insert(billing_wallets), [
            {"id": "wallet-1", "owner_type": "user", "owner_id": "1"},
            {"id": "wallet-2", "owner_type": "user", "owner_id": "2"},
        ])
    return engine, CreditAlertService(engine)


def reconcile(engine, service, wallet_id, available, cause="balance_change"):
    with engine.begin() as conn:
        service.reconcile_in_connection(conn, wallet_id, available, cause=cause)


def events(engine):
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(select(credit_alert_events)).mappings()]


def states(engine, user_id=1):
    with engine.connect() as conn:
        return {
            row["tier"]: dict(row)
            for row in conn.execute(select(credit_alert_states).where(
                credit_alert_states.c.user_id == user_id,
            )).mappings()
        }


def test_initial_zero_reconciliation_shows_critical_without_sms(alert_env):
    engine, service = alert_env
    resource = service.get(1, 0)
    assert resource["preferences"] == {"warning_threshold": 5000, "critical_threshold": 1000}
    assert resource["alert"]["tier"] == "critical"
    assert events(engine) == []


def test_warning_then_critical_crossings_and_dismissal(alert_env):
    engine, service = alert_env
    reconcile(engine, service, "wallet-1", 5001, "reconciliation")
    reconcile(engine, service, "wallet-1", 5000)
    assert service.get(1, 5000)["alert"]["tier"] == "warning"
    assert events(engine)[0]["sms_status"] == "skipped_unconfigured"
    assert service.dismiss(1, "warning", 5000)["alert"] is None
    reconcile(engine, service, "wallet-1", 1001)
    reconcile(engine, service, "wallet-1", 1000)
    assert service.get(1, 1000)["alert"]["tier"] == "critical"
    assert [row["tier"] for row in events(engine)] == ["warning", "critical"]


def test_rearms_only_strictly_above_threshold(alert_env):
    engine, service = alert_env
    reconcile(engine, service, "wallet-1", 6000, "reconciliation")
    reconcile(engine, service, "wallet-1", 5000)
    service.dismiss(1, "warning", 5000)
    reconcile(engine, service, "wallet-1", 5000)
    assert states(engine)["warning"]["status"] == "dismissed"
    reconcile(engine, service, "wallet-1", 5001)
    assert states(engine)["warning"]["status"] == "armed"
    reconcile(engine, service, "wallet-1", 5000)
    assert len(events(engine)) == 2


def test_preference_change_activates_without_sms_and_validates(alert_env):
    engine, service = alert_env
    resource = service.update_preferences(1, 7000, 2000, 6000)
    assert resource["alert"]["tier"] == "warning"
    assert events(engine) == []
    for values in ((1000, 1000), (999, 1000), (5000, -1), (2**63, 1000)):
        with pytest.raises(ValueError):
            service.update_preferences(1, values[0], values[1], 6000)


def test_single_change_crossing_both_records_only_critical(alert_env):
    engine, service = alert_env
    reconcile(engine, service, "wallet-1", 6000, "reconciliation")
    reconcile(engine, service, "wallet-1", 500)
    assert [row["tier"] for row in events(engine)] == ["critical"]
    assert states(engine)["warning"]["status"] == "superseded"


def test_missing_phone_is_terminally_skipped(alert_env):
    engine, service = alert_env
    reconcile(engine, service, "wallet-2", 6000, "reconciliation")
    reconcile(engine, service, "wallet-2", 5000)
    assert events(engine)[0]["sms_status"] == "skipped_missing_phone"


def test_disabled_sender_is_pure_and_returns_disabled_result():
    sender = DisabledSmsSender()
    result = sender.send(SmsAlert(
        event_id="event-1", phone_number="+8613800138000", display_name="Alice",
        tier="warning", available=5000, threshold=5000,
    ))
    assert result.status == "skipped_unconfigured"
    assert result.provider_message_id is None


def test_concurrent_reconciliation_records_one_event(alert_env):
    engine, service = alert_env
    reconcile(engine, service, "wallet-1", 6000, "reconciliation")
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: reconcile(engine, service, "wallet-1", 5000), range(2)))
    assert len(events(engine)) == 1
