# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert, select

from qwenpaw.app.runner.models import ChatSpec
from qwenpaw.app.runner.repo.sqlalchemy_repo import SqlAlchemyChatRepository
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.schema import create_all, messages, session_states, users
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def engine(tmp_path):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")})
    engine = create_engine_from_settings(settings)
    create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            insert(users),
            [
                {
                    "id": 1,
                    "username": "alice",
                    "password_hash": "hash",
                    "password_salt": "salt",
                    "role": "user",
                },
                {
                    "id": 2,
                    "username": "bob",
                    "password_hash": "hash",
                    "password_salt": "salt",
                    "role": "user",
                },
            ],
        )
    return engine


@pytest.fixture
def repo(engine):
    return SqlAlchemyChatRepository(agent_id="agent-a", engine=engine)


def _chat(
    chat_id: str,
    *,
    user_id: str = "1",
    session_id: str = "session-1",
    agent_label: str = "agent-a",
    seconds: int = 0,
) -> ChatSpec:
    now = datetime(2026, 6, 8, tzinfo=timezone.utc) + timedelta(seconds=seconds)
    return ChatSpec(
        id=chat_id,
        name=f"Chat {chat_id}",
        session_id=session_id,
        user_id=user_id,
        channel="console",
        status="idle",
        task_status="pending",
        pinned=False,
        meta={"agent_id": agent_label, "source": "test"},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_sqlalchemy_chat_repo_upserts_gets_and_filters_in_update_order(repo):
    old_chat = _chat("chat-old", seconds=1)
    new_chat = _chat("chat-new", seconds=2)

    await repo.upsert_chat(old_chat)
    await repo.upsert_chat(new_chat)

    found = await repo.get_chat("chat-old")
    assert found is not None
    assert found.id == "chat-old"
    assert found.user_id == "1"
    assert found.meta["agent_id"] == "agent-a"
    assert found.meta["source"] == "test"

    filtered = await repo.filter_chats(user_id="1", channel="console")
    assert [chat.id for chat in filtered] == ["chat-new", "chat-old"]


@pytest.mark.asyncio
async def test_sqlalchemy_chat_repo_isolates_agent_and_user(engine, repo):
    await repo.upsert_chat(_chat("agent-a-user-1", user_id="1", session_id="shared"))
    other_agent_repo = SqlAlchemyChatRepository(agent_id="agent-b", engine=engine)
    await other_agent_repo.upsert_chat(
        _chat("agent-b-user-1", user_id="1", session_id="shared", agent_label="agent-b"),
    )
    await repo.upsert_chat(_chat("agent-a-user-2", user_id="2", session_id="shared"))

    assert await repo.get_chat("agent-b-user-1") is None
    assert await repo.get_chat_by_id("shared", user_id="1", channel="console")
    assert (await repo.get_chat_by_id("shared", user_id="2", channel="console")).id == "agent-a-user-2"
    assert [chat.id for chat in await repo.filter_chats(user_id="1")] == ["agent-a-user-1"]


@pytest.mark.asyncio
async def test_sqlalchemy_chat_repo_counts_messages(engine, repo):
    await repo.upsert_chat(_chat("chat-with-messages"))
    with engine.begin() as conn:
        conn.execute(
            insert(messages),
            [
                {
                    "id": "msg-1",
                    "chat_id": "chat-with-messages",
                    "role": "user",
                    "name": "user",
                    "content": "hello",
                    "meta": "{}",
                    "timestamp": datetime(2026, 6, 8, tzinfo=timezone.utc),
                },
                {
                    "id": "msg-2",
                    "chat_id": "chat-with-messages",
                    "role": "assistant",
                    "name": "assistant",
                    "content": "hi",
                    "meta": "{}",
                    "timestamp": datetime(2026, 6, 8, tzinfo=timezone.utc),
                },
            ],
        )

    assert await repo.count_messages("chat-with-messages") == 2


@pytest.mark.asyncio
async def test_sqlalchemy_chat_repo_get_chat_id_by_session_returns_most_recent(repo):
    await repo.upsert_chat(_chat("older", session_id="same-session", seconds=1))
    await repo.upsert_chat(_chat("newer", session_id="same-session", seconds=2))
    await repo.upsert_chat(_chat("other-user", user_id="2", session_id="same-session", seconds=3))

    assert (
        await repo.get_chat_id_by_session("same-session", channel="console", user_id="1")
        == "newer"
    )


@pytest.mark.asyncio
async def test_sqlalchemy_chat_repo_delete_chats_is_scoped_to_agent(engine, repo):
    await repo.upsert_chat(_chat("delete-me"))
    other_agent_repo = SqlAlchemyChatRepository(agent_id="agent-b", engine=engine)
    await other_agent_repo.upsert_chat(_chat("keep-me", agent_label="agent-b"))

    assert await repo.delete_chats(["delete-me", "keep-me"]) is True
    assert await repo.get_chat("delete-me") is None
    assert (await other_agent_repo.get_chat("keep-me")).id == "keep-me"


@pytest.mark.asyncio
async def test_sqlalchemy_chat_repo_delete_chats_removes_session_children(engine, repo):
    await repo.upsert_chat(_chat("delete-with-state"))
    other_agent_repo = SqlAlchemyChatRepository(agent_id="agent-b", engine=engine)
    await other_agent_repo.upsert_chat(
        _chat("keep-with-state", agent_label="agent-b"),
    )
    with engine.begin() as conn:
        conn.execute(
            insert(messages),
            [
                {
                    "id": "msg-delete",
                    "chat_id": "delete-with-state",
                    "role": "user",
                    "name": "user",
                    "content": "hello",
                    "meta": "{}",
                    "timestamp": datetime(2026, 6, 8, tzinfo=timezone.utc),
                },
                {
                    "id": "msg-keep",
                    "chat_id": "keep-with-state",
                    "role": "user",
                    "name": "user",
                    "content": "hello",
                    "meta": "{}",
                    "timestamp": datetime(2026, 6, 8, tzinfo=timezone.utc),
                },
            ],
        )
        conn.execute(
            insert(session_states),
            [
                {"chat_id": "delete-with-state", "state_json": "{}"},
                {"chat_id": "keep-with-state", "state_json": "{}"},
            ],
        )

    assert await repo.delete_chats(["delete-with-state", "keep-with-state"]) is True
    assert await repo.get_chat("delete-with-state") is None
    assert (await other_agent_repo.get_chat("keep-with-state")).id == "keep-with-state"
    with engine.connect() as conn:
        assert conn.execute(
            select(messages.c.id).where(messages.c.chat_id == "delete-with-state"),
        ).first() is None
        assert conn.execute(
            select(session_states.c.chat_id).where(
                session_states.c.chat_id == "delete-with-state",
            ),
        ).first() is None
        assert conn.execute(
            select(messages.c.id).where(messages.c.chat_id == "keep-with-state"),
        ).scalar_one() == "msg-keep"
        assert conn.execute(
            select(session_states.c.chat_id).where(
                session_states.c.chat_id == "keep-with-state",
            ),
        ).scalar_one() == "keep-with-state"
