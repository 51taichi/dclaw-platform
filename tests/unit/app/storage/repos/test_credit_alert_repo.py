from __future__ import annotations

from sqlalchemy import insert

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.credit_alert_repo import CreditAlertRepository
from qwenpaw.app.storage.schema import create_all, users
from qwenpaw.app.storage.settings import get_storage_settings


def test_repository_creates_default_preferences_and_states(tmp_path):
    engine = create_engine_from_settings(get_storage_settings({
        "QWENPAW_SQLITE_PATH": str(tmp_path / "alerts.db"),
    }))
    create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(users), {
            "id": 1, "username": "alice", "password_hash": "h", "password_salt": "s",
        })
        repo = CreditAlertRepository()
        preferences = repo.ensure_preferences(conn, 1)
        states = repo.ensure_states(conn, 1)

    assert preferences["warning_threshold"] == 5000
    assert preferences["critical_threshold"] == 1000
    assert {row["tier"]: row["status"] for row in states} == {
        "warning": "armed", "critical": "armed",
    }

