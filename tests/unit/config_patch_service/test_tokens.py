from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from config_patch_service.db import ConfigPatchDatabase
from config_patch_service.settings import ConfigPatchSettings
from config_patch_service.tokens import (
    ExpiredStaffTokenError,
    InvalidStaffTokenError,
    RevokedStaffTokenError,
)


def test_schema_initialization_is_idempotent_and_uses_wal(database: ConfigPatchDatabase):
    database.initialize()
    with database.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    assert {"staff_tokens", "audit_events"}.issubset(tables)
    assert journal_mode.lower() == "wal"


def test_environment_settings_require_dedicated_storage_and_every_service_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    names = {
        "CONFIG_PATCH_DATA_DIR": str(tmp_path / "dedicated"),
        "CONFIG_PATCH_TOKEN_PEPPER": "pepper-value",
        "CONFIG_PATCH_ADMIN_SECRET": "admin-value",
        "DCLAW_CONFIG_PATCH_INTERNAL_SECRET": "dclaw-value",
        "OMNICHANNEL_CONFIG_PATCH_INTERNAL_SECRET": "omnichannel-value",
    }
    for name, value in names.items():
        monkeypatch.setenv(name, value)

    loaded = ConfigPatchSettings.from_env()
    assert loaded.data_dir == (tmp_path / "dedicated").resolve()
    assert loaded.database_path.parent == loaded.data_dir
    assert "pepper-value" not in repr(loaded)
    assert "admin-value" not in repr(loaded)

    monkeypatch.delenv("CONFIG_PATCH_TOKEN_PEPPER")
    with pytest.raises(RuntimeError, match="CONFIG_PATCH_TOKEN_PEPPER"):
        ConfigPatchSettings.from_env()


def test_create_returns_plaintext_once_but_persists_only_hmac_and_safe_metadata(
    token_service,
    database: ConfigPatchDatabase,
):
    issued = token_service.create(employee_name="张三", token_name="Codex MacBook")

    assert issued.token.startswith("dclaw_staff_")
    assert len(issued.token) >= 50
    assert issued.token not in repr(token_service.list())

    with database.connect() as connection:
        row = connection.execute("SELECT * FROM staff_tokens").fetchone()
        columns = {item[1] for item in connection.execute("PRAGMA table_info(staff_tokens)")}
        database_dump = "|".join("" if value is None else str(value) for value in row)

    assert "token" not in columns
    assert "token_hmac" in columns
    assert issued.token not in database_dump
    assert row["token_hmac"] != issued.token
    assert row["token_prefix"].startswith("dclaw_staff_")
    assert row["token_suffix"] == issued.token[-4:]


def test_authentication_updates_last_used_at_at_most_once_per_minute(
    token_service,
    database: ConfigPatchDatabase,
    clock,
):
    issued = token_service.create(employee_name="李四", token_name="Home Codex")

    first = token_service.authenticate(issued.token)
    with database.connect() as connection:
        first_used_at = connection.execute(
            "SELECT last_used_at FROM staff_tokens WHERE id = ?", (issued.token_id,)
        ).fetchone()[0]

    clock.value += timedelta(seconds=30)
    second = token_service.authenticate(issued.token)
    with database.connect() as connection:
        throttled_used_at = connection.execute(
            "SELECT last_used_at FROM staff_tokens WHERE id = ?", (issued.token_id,)
        ).fetchone()[0]

    clock.value += timedelta(seconds=31)
    token_service.authenticate(issued.token)
    with database.connect() as connection:
        refreshed_used_at = connection.execute(
            "SELECT last_used_at FROM staff_tokens WHERE id = ?", (issued.token_id,)
        ).fetchone()[0]

    assert first.token_id == issued.token_id
    assert second.employee_name == "李四"
    assert throttled_used_at == first_used_at
    assert refreshed_used_at != first_used_at


def test_expired_revoked_and_rotated_tokens_stop_working_immediately(
    token_service,
    clock,
):
    expired = token_service.create(
        employee_name="过期员工",
        token_name="Expired",
        expires_at=clock.value + timedelta(seconds=1),
    )
    clock.value += timedelta(seconds=2)
    with pytest.raises(ExpiredStaffTokenError):
        token_service.authenticate(expired.token)

    active = token_service.create(employee_name="王五", token_name="Active")
    token_service.revoke(active.token_id)
    with pytest.raises(RevokedStaffTokenError):
        token_service.authenticate(active.token)

    rotating = token_service.create(employee_name="赵六", token_name="Rotating")
    rotated = token_service.rotate(rotating.token_id)
    assert rotated.token_id == rotating.token_id
    assert rotated.token != rotating.token
    with pytest.raises(InvalidStaffTokenError):
        token_service.authenticate(rotating.token)
    assert token_service.authenticate(rotated.token).token_id == rotating.token_id


def test_unknown_token_id_operations_fail_without_creating_rows(token_service):
    with pytest.raises(KeyError):
        token_service.revoke("missing")
    with pytest.raises(KeyError):
        token_service.rotate("missing")
    assert token_service.list() == []
