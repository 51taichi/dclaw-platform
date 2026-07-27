# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app import db
from qwenpaw.app import chat_access
from qwenpaw.app.chat_access import ensure_chat_access


@pytest.fixture
def isolated_chat_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "qwenpaw.db")

    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        delattr(db._local, "conn")

    db.init_db()
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO users (id, username, password_hash, password_salt, role)
        VALUES
            (1, 'alice', 'hash', 'salt', 'user'),
            (2, 'bob', 'hash', 'salt', 'user')
        """
    )
    cursor.execute(
        """
        INSERT INTO chats (id, user_id, agent_id, session_id, channel, name)
        VALUES
            ('chat-alice', 1, 'default', 'session-alice', 'console', 'Alice chat'),
            ('chat-bob', 2, 'default', 'session-bob', 'console', 'Bob chat')
        """
    )
    conn.commit()
    try:
        yield
    finally:
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
            delattr(db._local, "conn")


def _request_for_user(user_id: int, role: str = "user"):
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id, role=role))


def test_current_user_id_without_request_state_uses_single_user_fallback(
    monkeypatch,
):
    monkeypatch.setattr(chat_access, "is_auth_enabled", lambda: False)

    assert chat_access.current_user_id(object()) == "0"


def test_current_user_id_without_request_state_requires_auth_when_enabled(
    monkeypatch,
):
    monkeypatch.setattr(chat_access, "is_auth_enabled", lambda: True)

    with pytest.raises(HTTPException) as exc:
        chat_access.current_user_id(object())

    assert exc.value.status_code == 401


def test_chat_owner_can_access_by_chat_id(isolated_chat_db):
    row = ensure_chat_access(_request_for_user(1), "chat-alice")

    assert row["id"] == "chat-alice"
    assert row["session_id"] == "session-alice"


def test_chat_owner_can_access_by_session_id(isolated_chat_db):
    row = ensure_chat_access(_request_for_user(1), "session-alice")

    assert row["id"] == "chat-alice"


def test_other_user_chat_is_hidden(isolated_chat_db):
    with pytest.raises(HTTPException) as exc:
        ensure_chat_access(_request_for_user(1), "chat-bob")

    assert exc.value.status_code == 404


def test_other_user_session_is_hidden(isolated_chat_db):
    with pytest.raises(HTTPException) as exc:
        ensure_chat_access(_request_for_user(1), "session-bob")

    assert exc.value.status_code == 404


def test_chat_access_uses_user_repository(monkeypatch):
    class FakeUserRepository:
        def __init__(self):
            self.lookups = []

        def find_chat_access_rows(self, chat_id_or_session_id):
            self.lookups.append(chat_id_or_session_id)
            return [
                {
                    "id": "chat-repo",
                    "user_id": "3",
                    "agent_id": "default",
                    "session_id": "session-repo",
                    "channel": "console",
                    "meta": "{}",
                }
            ]

    repo = FakeUserRepository()
    monkeypatch.setattr(chat_access, "get_user_repository", lambda: repo)

    row = chat_access.ensure_chat_access(_request_for_user(3), "session-repo")

    assert repo.lookups == ["session-repo"]
    assert row["id"] == "chat-repo"
