# -*- coding: utf-8 -*-
"""Tests for aggregated chat list performance behavior."""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from qwenpaw.app.routers import agents as agents_router
from qwenpaw.app.storage.repos.chat_list_repo import SqliteChatListRepository


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE chats (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            agent_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            channel TEXT DEFAULT 'default',
            name TEXT DEFAULT 'New Chat',
            status TEXT DEFAULT 'idle',
            task_status TEXT DEFAULT 'pending',
            pinned BOOLEAN DEFAULT 0,
            meta TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    conn.execute(
        """
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            name TEXT NOT NULL,
            content TEXT,
            meta TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    )
    return conn


@pytest.mark.asyncio
async def test_list_all_chats_does_not_cleanup_empty_default_name_ghosts(monkeypatch):
    conn = _make_db()
    conn.execute(
        """
        INSERT INTO chats
          (id, user_id, agent_id, session_id, channel, name, status, task_status, pinned, meta)
        VALUES
          ('ghost-chat', 1, 'default', 'ghost-session', 'console', 'New Chat', 'idle', 'pending', 0, '{}'),
          ('running-chat', 1, 'default', 'running-session', 'console', 'New Chat', 'running', 'pending', 0, '{}'),
          ('open-chat', 1, 'default', 'open:app-1:public-agent:ext-user:session-1', 'open:app-1', 'External Open API', 'idle', 'pending', 0, '{}'),
          ('real-chat', 1, 'default', 'real-session', 'console', 'Real Task', 'idle', 'pending', 0, '{}')
        """,
    )
    conn.execute(
        """
        INSERT INTO messages (id, chat_id, role, name, content, meta)
        VALUES ('message-1', 'real-chat', 'user', 'user', 'hello', '{}')
        """,
    )
    conn.commit()

    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={"default": SimpleNamespace(enabled=True)},
        ),
    )
    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(
        "qwenpaw.app.storage.repos.chat_list_repo.db.get_db",
        lambda: conn,
    )
    monkeypatch.setattr(
        agents_router,
        "get_chat_list_repository",
        lambda: SqliteChatListRepository(),
    )

    request = SimpleNamespace(state=SimpleNamespace(user_id=1, role="user"))
    chats = await agents_router.list_all_chats(request)

    assert {chat["id"] for chat in chats} == {
        "ghost-chat",
        "running-chat",
        "real-chat",
    }
    remaining = conn.execute("SELECT id FROM chats ORDER BY id").fetchall()
    assert [row["id"] for row in remaining] == [
        "ghost-chat",
        "open-chat",
        "real-chat",
        "running-chat",
    ]


@pytest.mark.asyncio
async def test_list_all_chats_uses_chat_list_repository(monkeypatch):
    class FakeChatListRepository:
        def __init__(self):
            self.cleanup_calls = []
            self.list_calls = []

        def cleanup_empty_ghost_chats(self, *, enabled_agent_ids, user_id):
            self.cleanup_calls.append((enabled_agent_ids, user_id))
            return 0

        def list_recent_chats(self, *, enabled_agent_ids, user_id, limit):
            self.list_calls.append((enabled_agent_ids, user_id, limit))
            return [
                {
                    "id": "chat-1",
                    "user_id": "1",
                    "agent_id": "default",
                    "session_id": "session-1",
                    "channel": "console",
                    "name": "Task",
                    "status": "idle",
                    "task_status": "pending",
                    "pinned": False,
                    "meta": "{}",
                    "created_at": "2026-06-08T10:00:00",
                    "updated_at": "2026-06-08T10:00:00",
                    "message_count": 2,
                }
            ]

    repo = FakeChatListRepository()
    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={
                "default": SimpleNamespace(enabled=True),
                "hidden": SimpleNamespace(enabled=False),
            },
        ),
    )
    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(agents_router, "get_chat_list_repository", lambda: repo)

    request = SimpleNamespace(state=SimpleNamespace(user_id=1, role="user"))
    chats = await agents_router.list_all_chats(request)

    assert repo.cleanup_calls == []
    assert repo.list_calls == [(["default"], "1", 50)]
    assert chats[0]["id"] == "chat-1"
    assert chats[0]["message_count"] == 2


@pytest.mark.asyncio
async def test_list_all_chats_hides_archived_chats(monkeypatch):
    class FakeChatListRepository:
        def list_recent_chats(self, *, enabled_agent_ids, user_id, limit):
            assert enabled_agent_ids == ["default"]
            assert user_id == "1"
            assert limit == 50
            return [
                {
                    "id": "archived-chat",
                    "user_id": "1",
                    "agent_id": "default",
                    "session_id": "archived-session",
                    "channel": "console",
                    "name": "Archived",
                    "status": "idle",
                    "task_status": "completed",
                    "pinned": False,
                    "meta": '{"archived_at": "2026-07-07T12:00:00+00:00"}',
                    "created_at": "2026-06-08T10:00:00",
                    "updated_at": "2026-06-08T10:00:00",
                    "message_count": 2,
                },
                {
                    "id": "visible-chat",
                    "user_id": "1",
                    "agent_id": "default",
                    "session_id": "visible-session",
                    "channel": "console",
                    "name": "Visible",
                    "status": "idle",
                    "task_status": "completed",
                    "pinned": False,
                    "meta": "{}",
                    "created_at": "2026-06-08T10:00:00",
                    "updated_at": "2026-06-08T10:00:00",
                    "message_count": 2,
                },
            ]

    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={"default": SimpleNamespace(enabled=True)},
        ),
    )
    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(
        agents_router,
        "get_chat_list_repository",
        lambda: FakeChatListRepository(),
    )

    request = SimpleNamespace(state=SimpleNamespace(user_id=1, role="user"))
    chats = await agents_router.list_all_chats(request)

    assert [chat["id"] for chat in chats] == ["visible-chat"]


@pytest.mark.asyncio
async def test_list_all_chats_does_not_start_unloaded_workspaces(monkeypatch):
    class FakeTaskTracker:
        async def list_active_tasks(self):
            return ["running-chat"]

    class FakeManager:
        agents = {
            "default": SimpleNamespace(task_tracker=FakeTaskTracker()),
        }

        async def get_agent(self, agent_id, user_id="default"):
            raise AssertionError(f"must not start workspace {agent_id} for {user_id}")

    class FakeChatListRepository:
        def cleanup_empty_ghost_chats(self, *, enabled_agent_ids, user_id):
            raise AssertionError("read path must not cleanup chats")

        def list_recent_chats(self, *, enabled_agent_ids, user_id, limit):
            return [
                {
                    "id": "running-chat",
                    "user_id": "1",
                    "agent_id": "default",
                    "session_id": "session-1",
                    "channel": "console",
                    "name": "Running",
                    "status": "idle",
                    "task_status": "pending",
                    "pinned": False,
                    "meta": "{}",
                    "created_at": "2026-06-08T10:00:00",
                    "updated_at": "2026-06-08T10:00:00",
                    "message_count": 1,
                },
                {
                    "id": "other-chat",
                    "user_id": "1",
                    "agent_id": "cold-agent",
                    "session_id": "session-2",
                    "channel": "console",
                    "name": "Cold",
                    "status": "idle",
                    "task_status": "pending",
                    "pinned": False,
                    "meta": "{}",
                    "created_at": "2026-06-08T10:00:00",
                    "updated_at": "2026-06-08T10:00:00",
                    "message_count": 1,
                },
            ]

    config = SimpleNamespace(
        agents=SimpleNamespace(
            profiles={
                "default": SimpleNamespace(enabled=True),
                "cold-agent": SimpleNamespace(enabled=True),
            },
        ),
    )
    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(
        agents_router,
        "get_chat_list_repository",
        lambda: FakeChatListRepository(),
    )

    request = SimpleNamespace(
        state=SimpleNamespace(user_id=1, role="user"),
        app=SimpleNamespace(state=SimpleNamespace(multi_agent_manager=FakeManager())),
    )

    chats = await agents_router.list_all_chats(request)

    assert [chat["status"] for chat in chats] == ["running", "idle"]
