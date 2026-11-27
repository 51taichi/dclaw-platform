# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, select

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.chat_list_repo import SqlAlchemyChatListRepository
from qwenpaw.app.storage.schema import chats, create_all, messages
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def engine(tmp_path):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")})
    engine = create_engine_from_settings(settings)
    create_all(engine)
    return engine


@pytest.fixture
def repo(engine):
    return SqlAlchemyChatListRepository(engine)


def test_sqlalchemy_chat_list_repo_removes_empty_ghosts_and_lists_recent(engine, repo):
    now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            insert(chats),
            [
                {
                    "id": "ghost-chat",
                    "user_id": "1",
                    "agent_id": "default",
                    "session_id": "ghost-session",
                    "channel": "console",
                    "name": "New Chat",
                    "status": "idle",
                    "task_status": "pending",
                    "pinned": False,
                    "meta": "{}",
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": "running-chat",
                    "user_id": "1",
                    "agent_id": "default",
                    "session_id": "running-session",
                    "channel": "console",
                    "name": "New Chat",
                    "status": "running",
                    "task_status": "pending",
                    "pinned": False,
                    "meta": "{}",
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": "open-chat",
                    "user_id": "1",
                    "agent_id": "default",
                    "session_id": "open:app-1:public-agent:ext-user:session-1",
                    "channel": "open:app-1",
                    "name": "External Open API",
                    "status": "idle",
                    "task_status": "pending",
                    "pinned": False,
                    "meta": "{}",
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": "real-chat",
                    "user_id": "1",
                    "agent_id": "default",
                    "session_id": "real-session",
                    "channel": "console",
                    "name": "Real Task",
                    "status": "idle",
                    "task_status": "pending",
                    "pinned": True,
                    "meta": "{\"kind\":\"task\"}",
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )
        conn.execute(
            insert(messages),
            {
                "id": "message-1",
                "chat_id": "real-chat",
                "role": "user",
                "name": "user",
                "content": "hello",
                "meta": "{}",
                "timestamp": now,
            },
        )

    deleted = repo.cleanup_empty_ghost_chats(
        enabled_agent_ids=["default"],
        user_id="1",
    )
    rows = repo.list_recent_chats(
        enabled_agent_ids=["default"],
        user_id="1",
        limit=50,
    )

    assert deleted == 1
    assert {row["id"] for row in rows} == {"running-chat", "real-chat"}
    assert {row["id"]: row["message_count"] for row in rows} == {
        "running-chat": 0,
        "real-chat": 1,
    }

    with engine.connect() as conn:
        remaining = conn.execute(select(chats.c.id).order_by(chats.c.id)).all()
    assert [row[0] for row in remaining] == [
        "open-chat",
        "real-chat",
        "running-chat",
    ]


def test_sqlalchemy_chat_list_repo_filters_user_and_agents(engine, repo):
    now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            insert(chats),
            [
                {
                    "id": "alice-default",
                    "user_id": "1",
                    "agent_id": "default",
                    "session_id": "s1",
                    "channel": "console",
                    "name": "Alice",
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": "alice-hidden-agent",
                    "user_id": "1",
                    "agent_id": "hidden",
                    "session_id": "s2",
                    "channel": "console",
                    "name": "Hidden",
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": "bob-default",
                    "user_id": "2",
                    "agent_id": "default",
                    "session_id": "s3",
                    "channel": "console",
                    "name": "Bob",
                    "created_at": now,
                    "updated_at": now,
                },
            ],
        )

    rows = repo.list_recent_chats(
        enabled_agent_ids=["default"],
        user_id="1",
        limit=50,
    )

    assert [row["id"] for row in rows] == ["alice-default"]
