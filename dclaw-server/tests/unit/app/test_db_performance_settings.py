# -*- coding: utf-8 -*-
from __future__ import annotations

from qwenpaw.app import db
from qwenpaw.app.storage import engine as storage_engine
from qwenpaw.app.storage.settings import get_storage_settings


def _reset_db_connection() -> None:
    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        delattr(db._local, "conn")


def test_init_db_enables_sqlite_performance_pragmas(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "qwenpaw.db")
    _reset_db_connection()

    db.init_db()
    conn = db.get_db()

    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_init_db_creates_high_frequency_indexes(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "qwenpaw.db")
    _reset_db_connection()

    db.init_db()
    rows = db.get_db().execute("PRAGMA index_list(chats)").fetchall()
    chat_indexes = {row["name"] for row in rows}

    assert "idx_chats_user_agent_updated" in chat_indexes
    assert "idx_chats_session_user_channel_agent" in chat_indexes

    message_indexes = {
        row["name"]
        for row in db.get_db().execute("PRAGMA index_list(messages)").fetchall()
    }
    assert "idx_messages_chat_timestamp" in message_indexes


def test_init_db_prepares_general_billing_execution_bridge(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "qwenpaw.db")
    _reset_db_connection()

    db.init_db()
    conn = db.get_db()

    columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(billing_executions)",
        ).fetchall()
    }
    assert {
        "id",
        "usage_order_id",
        "payer_user_id",
        "source_type",
        "source_id",
        "request_sha256",
        "state",
        "owner_token",
        "fence_generation",
        "lease_expires_at",
        "resume_state_json",
        "exemption_actor",
        "exemption_reason",
        "error_code",
    } <= columns


def test_postgres_engine_uses_saas_pool_defaults(monkeypatch):
    captured = {}

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(storage_engine, "create_engine", fake_create_engine)

    settings = get_storage_settings(
        {
            "QWENPAW_DATABASE_BACKEND": "postgres",
            "QWENPAW_DATABASE_URL": "postgresql://user:pass@example.test/qwenpaw",
        },
    )

    storage_engine.create_engine_from_settings(settings)

    assert captured["pool_size"] == 10
    assert captured["max_overflow"] == 20
    assert captured["connect_args"]["connect_timeout"] == 5


def test_postgres_engine_accepts_database_pool_env_aliases(monkeypatch):
    captured = {}

    def fake_create_engine(url, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setenv("QWENPAW_DATABASE_POOL_SIZE", "14")
    monkeypatch.setenv("QWENPAW_DATABASE_MAX_OVERFLOW", "28")
    monkeypatch.setattr(storage_engine, "create_engine", fake_create_engine)

    settings = get_storage_settings(
        {
            "QWENPAW_DATABASE_BACKEND": "postgres",
            "QWENPAW_DATABASE_URL": "postgresql://user:pass@example.test/qwenpaw",
        },
    )

    storage_engine.create_engine_from_settings(settings)

    assert captured["pool_size"] == 14
    assert captured["max_overflow"] == 28
