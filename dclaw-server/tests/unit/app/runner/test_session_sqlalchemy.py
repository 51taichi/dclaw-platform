# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from sqlalchemy import event, select

from qwenpaw.app.runner.session_sqlalchemy import SqlAlchemySession
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.schema import chats, create_all
from qwenpaw.app.storage.settings import get_storage_settings
from qwenpaw.exceptions import AgentStateError


class _StateModule:
    def __init__(self, state):
        self._state = state
        self.loaded = None

    def state_dict(self):
        return self._state

    def load_state_dict(self, state):
        self.loaded = state


@pytest.fixture
def engine(tmp_path):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")})
    engine = create_engine_from_settings(settings)
    create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    return SqlAlchemySession(agent_id="agent-a", engine=engine)


@pytest.mark.asyncio
async def test_sqlalchemy_session_saves_and_loads_memory_and_other_state(session):
    memory = _StateModule(
        [
            {
                "id": "msg-1",
                "role": "user",
                "name": "user",
                "content": "hello",
                "extra": {"source": "test"},
            },
            {
                "id": "msg-2",
                "role": "assistant",
                "name": "assistant",
                "content": {"text": "hi"},
            },
        ],
    )
    planner = _StateModule({"stage": "draft"})

    await session.save_session_state(
        "session-1",
        user_id="user-1",
        channel="console",
        memory=memory,
        planner=planner,
    )

    loaded_memory = _StateModule([])
    loaded_planner = _StateModule({})
    await session.load_session_state(
        "session-1",
        user_id="user-1",
        channel="console",
        memory=loaded_memory,
        planner=loaded_planner,
    )

    assert loaded_memory.loaded == [
        {
            "id": "msg-1",
            "role": "user",
            "name": "user",
            "content": "hello",
            "extra": {"source": "test"},
        },
        {
            "id": "msg-2",
            "role": "assistant",
            "name": "assistant",
            "content": '{"text": "hi"}',
        },
    ]
    assert loaded_planner.loaded == {"stage": "draft"}


@pytest.mark.asyncio
async def test_sqlalchemy_session_gets_and_updates_session_state_dict(session):
    await session.save_session_state(
        "session-1",
        user_id="user-1",
        channel="console",
        memory=_StateModule([{"id": "msg-1", "role": "user", "name": "user", "content": "hello"}]),
        planner=_StateModule({"stage": "draft"}),
    )

    await session.update_session_state(
        "session-1",
        "planner.stage",
        "final",
        user_id="user-1",
        channel="console",
    )

    state = await session.get_session_state_dict(
        "session-1",
        user_id="user-1",
        channel="console",
    )

    assert state["memory"][0]["content"] == "hello"
    assert state["planner"]["stage"] == "final"


@pytest.mark.asyncio
async def test_sqlalchemy_session_raises_when_state_missing_and_not_allowed(session):
    with pytest.raises(AgentStateError):
        await session.get_session_state_dict(
            "missing-session",
            user_id="user-1",
            channel="console",
            allow_not_exist=False,
        )


@pytest.mark.asyncio
async def test_sqlalchemy_session_creates_fallback_chat(engine, session):
    await session.save_session_state(
        "new-session",
        user_id="user-1",
        channel="console",
        memory=_StateModule([]),
    )

    with engine.connect() as conn:
        row = conn.execute(
            select(chats).where(
                chats.c.session_id == "new-session",
                chats.c.user_id == "user-1",
                chats.c.channel == "console",
                chats.c.agent_id == "agent-a",
            ),
        ).mappings().first()

    assert row is not None
    assert row["name"] == "New Chat"


@pytest.mark.asyncio
async def test_sqlalchemy_session_bulk_upserts_messages(engine, session):
    statement_count = 0

    def count_statement(*_args):
        nonlocal statement_count
        statement_count += 1

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        await session.save_session_state(
            "bulk-session",
            user_id="user-1",
            channel="console",
            memory=_StateModule(
                [
                    {
                        "id": f"msg-{index}",
                        "role": "user",
                        "name": "user",
                        "content": f"hello {index}",
                    }
                    for index in range(20)
                ],
            ),
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    assert statement_count <= 5
