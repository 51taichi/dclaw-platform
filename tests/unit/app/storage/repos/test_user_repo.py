# -*- coding: utf-8 -*-
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, select

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.user_repo import SqlAlchemyUserRepository, SqliteUserRepository
from qwenpaw.app.storage.schema import (
    chats,
    credit_alert_events,
    credit_alert_preferences,
    credit_alert_states,
    create_all,
    messages,
    session_states,
    token_usage_logs,
    user_connections,
    users,
)
from qwenpaw.app.storage.settings import get_storage_settings
from qwenpaw.app.user_identity import normalize_cn_mobile


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, None), ("13800138000", "+8613800138000"), (" +8613900139000 ", "+8613900139000")],
)
def test_normalize_cn_mobile_accepts_supported_forms(raw, expected):
    assert normalize_cn_mobile(raw) == expected


@pytest.mark.parametrize("raw", ["", "12800128000", "+1 555 0100", "1380013800"])
def test_normalize_cn_mobile_rejects_malformed_values(raw):
    with pytest.raises(ValueError):
        normalize_cn_mobile(raw)


@pytest.fixture
def engine(tmp_path):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")})
    engine = create_engine_from_settings(settings)
    create_all(engine)
    return engine


@pytest.fixture
def repo(engine):
    return SqlAlchemyUserRepository(engine)


def test_sqlalchemy_user_repo_creates_lists_and_updates_users(repo):
    created = repo.create_user(
        username="alice",
        password_hash="hash-a",
        password_salt="salt-a",
        role="admin",
    )

    assert created["id"] == 1
    assert created["username"] == "alice"
    assert created["role"] == "admin"
    assert created["display_name"] is None
    assert created["phone_number_e164"] is None
    assert repo.count_users() == 1
    assert repo.count_admins() == 1
    assert repo.get_user_by_username("alice")["id"] == 1
    assert repo.get_user_credentials("alice") == {
        "password_hash": "hash-a",
        "password_salt": "salt-a",
    }

    assert repo.update_user_password(1, "hash-b", "salt-b") is True
    assert repo.get_user_credentials("alice") == {
        "password_hash": "hash-b",
        "password_salt": "salt-b",
    }
    assert [user["username"] for user in repo.list_users()] == ["alice"]


def test_sqlalchemy_user_repo_round_trips_identity(repo):
    created = repo.create_user(
        username="alice",
        password_hash="hash",
        password_salt="salt",
        role="user",
        display_name="Alice Chen",
        phone_number_e164="+8613800138000",
    )

    assert created["display_name"] == "Alice Chen"
    assert created["phone_number_e164"] == "+8613800138000"
    assert repo.get_user_by_username("alice")["display_name"] == "Alice Chen"
    assert repo.list_users()[0]["phone_number_e164"] == "+8613800138000"


def test_sqlalchemy_user_repo_ensure_and_update_legacy_user(repo):
    ensured = repo.ensure_user(
        username="admin",
        password_hash="hash-a",
        password_salt="salt-a",
        role="admin",
    )
    assert ensured["username"] == "admin"

    same = repo.ensure_user(
        username="admin",
        password_hash="new-hash",
        password_salt="new-salt",
        role="user",
    )
    assert same["id"] == ensured["id"]
    assert repo.get_user_credentials("admin") == {
        "password_hash": "hash-a",
        "password_salt": "salt-a",
    }

    updated = repo.update_user_credentials(
        old_username="admin",
        username="owner",
        password_hash="hash-b",
        password_salt="salt-b",
        role="admin",
    )
    assert updated["username"] == "owner"
    assert repo.get_user_by_username("admin") is None
    assert repo.get_user_credentials("owner") == {
        "password_hash": "hash-b",
        "password_salt": "salt-b",
    }


def test_sqlalchemy_user_repo_finds_chat_access_rows(engine, repo):
    repo.create_user(
        username="alice",
        password_hash="hash",
        password_salt="salt",
        role="user",
    )
    repo.create_user(
        username="bob",
        password_hash="hash",
        password_salt="salt",
        role="user",
    )
    with engine.begin() as conn:
        conn.execute(
            insert(chats),
            [
                {
                    "id": "chat-alice",
                    "user_id": "1",
                    "agent_id": "default",
                    "session_id": "session-alice",
                    "channel": "console",
                    "name": "Alice",
                },
                {
                    "id": "chat-bob",
                    "user_id": "2",
                    "agent_id": "default",
                    "session_id": "session-bob",
                    "channel": "console",
                    "name": "Bob",
                },
            ],
        )

    rows = repo.find_chat_access_rows("session-alice")

    assert len(rows) == 1
    assert rows[0]["id"] == "chat-alice"
    assert rows[0]["user_id"] == "1"


def test_sqlalchemy_user_repo_delete_user_cascades_owned_records(engine, repo):
    repo.create_user(
        username="alice",
        password_hash="hash",
        password_salt="salt",
        role="admin",
    )
    repo.create_user(
        username="bob",
        password_hash="hash",
        password_salt="salt",
        role="admin",
    )
    now = datetime(2026, 6, 8, tzinfo=timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            insert(user_connections),
            {
                "user_id": 1,
                "connector_key": "github",
                "oauth_tokens": "{}",
                "custom_envs": "{}",
            },
        )
        conn.execute(
            insert(chats),
            {
                "id": "chat-alice",
                "user_id": "1",
                "agent_id": "default",
                "session_id": "session-alice",
                "channel": "console",
                "name": "Alice",
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.execute(
            insert(messages),
            {
                "id": "msg-1",
                "chat_id": "chat-alice",
                "role": "user",
                "name": "user",
                "content": "hello",
                "meta": "{}",
                "timestamp": now,
            },
        )
        conn.execute(
            insert(session_states),
            {
                "chat_id": "chat-alice",
                "state_json": '{"memory": {"value": "remember me"}}',
            },
        )
        conn.execute(
            insert(token_usage_logs),
            {
                "id": "usage-1",
                "user_id": 1,
                "model_name": "model",
                "prompt_tokens": 1,
                "completion_tokens": 2,
            },
        )
        conn.execute(insert(credit_alert_preferences), {"user_id": 1})
        conn.execute(insert(credit_alert_states), {"user_id": 1, "tier": "warning"})
        conn.execute(insert(credit_alert_events), {
            "id": "alert-1", "user_id": 1, "tier": "warning", "cycle_number": 1,
            "available_balance": 5000, "threshold": 5000,
            "sms_status": "skipped_unconfigured",
        })

    assert repo.delete_user_cascade(1) is True

    with engine.connect() as conn:
        assert conn.execute(select(users).where(users.c.id == 1)).first() is None
        assert conn.execute(select(chats).where(chats.c.user_id == "1")).first() is None
        assert conn.execute(select(messages)).first() is None
        assert conn.execute(select(session_states)).first() is None
        assert conn.execute(select(user_connections)).first() is None
        assert conn.execute(select(token_usage_logs)).first() is None
        assert conn.execute(select(credit_alert_preferences)).first() is None
        assert conn.execute(select(credit_alert_states)).first() is None
        assert conn.execute(select(credit_alert_events)).first() is None
        assert conn.execute(select(users).where(users.c.id == 2)).first() is not None


def test_sqlite_user_repo_delete_user_cascades_session_state(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, role TEXT, created_at TEXT);
        CREATE TABLE chats (id TEXT PRIMARY KEY, user_id TEXT NOT NULL);
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            chat_id TEXT NOT NULL REFERENCES chats(id)
        );
        CREATE TABLE session_states (
            chat_id TEXT PRIMARY KEY REFERENCES chats(id),
            state_json TEXT
        );
        CREATE TABLE user_capabilities (id TEXT PRIMARY KEY, user_id INTEGER NOT NULL);
        CREATE TABLE user_connections (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL);
        CREATE TABLE token_usage_logs (id TEXT PRIMARY KEY, user_id INTEGER);
        INSERT INTO users VALUES (1, 'alice', 'user', '2026-06-08');
        INSERT INTO users VALUES (2, 'bob', 'user', '2026-06-08');
        INSERT INTO chats VALUES ('chat-alice', '1');
        INSERT INTO chats VALUES ('chat-bob', '2');
        INSERT INTO session_states VALUES ('chat-alice', '{}');
        INSERT INTO session_states VALUES ('chat-bob', '{}');
        """,
    )
    monkeypatch.setattr("qwenpaw.app.storage.repos.user_repo.db.get_db", lambda: conn)

    assert SqliteUserRepository().delete_user_cascade(1) is True

    assert conn.execute("SELECT 1 FROM users WHERE id = 1").fetchone() is None
    assert conn.execute(
        "SELECT 1 FROM session_states WHERE chat_id = 'chat-alice'",
    ).fetchone() is None
    assert conn.execute(
        "SELECT 1 FROM session_states WHERE chat_id = 'chat-bob'",
    ).fetchone() is not None
