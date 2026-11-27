# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import insert

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.audit_repo import SqlAlchemyAuditRepository
from qwenpaw.app.storage.schema import chats, create_all
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def engine(tmp_path):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")})
    engine = create_engine_from_settings(settings)
    create_all(engine)
    return engine


@pytest.fixture
def repo(engine):
    return SqlAlchemyAuditRepository(engine)


def test_sqlalchemy_audit_repo_lists_and_filters_chats(engine, repo):
    now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            insert(chats),
            [
                {
                    "id": "chat-1",
                    "user_id": "1",
                    "agent_id": "default",
                    "session_id": "session-1",
                    "channel": "console",
                    "name": "Task",
                    "meta": "{\"kind\":\"task\"}",
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": "chat-2",
                    "user_id": "2",
                    "agent_id": "other",
                    "session_id": "session-2",
                    "channel": "console",
                    "name": "Other",
                    "meta": None,
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )

    rows = repo.list_chats(user_id="1", agent_id="default", limit=50, offset=0)

    assert [row["id"] for row in rows] == ["chat-1"]
    assert rows[0]["meta"] == "{\"kind\":\"task\"}"


def test_sqlalchemy_audit_repo_gets_chat_identity(engine, repo):
    with engine.begin() as conn:
        conn.execute(
            insert(chats),
            {
                "id": "chat-1",
                "user_id": "1",
                "agent_id": "default",
                "session_id": "session-1",
                "channel": "console",
                "name": "Task",
            },
        )

    assert repo.get_chat_identity("chat-1") == {
        "agent_id": "default",
        "session_id": "session-1",
        "user_id": "1",
        "channel": "console",
    }
    assert repo.get_chat_identity("missing") is None
