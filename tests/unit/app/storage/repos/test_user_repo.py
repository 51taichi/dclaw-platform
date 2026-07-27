# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, select

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.user_repo import SqlAlchemyUserRepository
from qwenpaw.app.storage.schema import (
    chats,
    create_all,
    messages,
    token_usage_logs,
    user_connections,
    users,
)
from qwenpaw.app.storage.settings import get_storage_settings


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
            insert(token_usage_logs),
            {
                "id": "usage-1",
                "user_id": 1,
                "model_name": "model",
                "prompt_tokens": 1,
                "completion_tokens": 2,
            },
        )

    assert repo.delete_user_cascade(1) is True

    with engine.connect() as conn:
        assert conn.execute(select(users).where(users.c.id == 1)).first() is None
        assert conn.execute(select(chats).where(chats.c.user_id == "1")).first() is None
        assert conn.execute(select(messages)).first() is None
        assert conn.execute(select(user_connections)).first() is None
        assert conn.execute(select(token_usage_logs)).first() is None
        assert conn.execute(select(users).where(users.c.id == 2)).first() is not None
