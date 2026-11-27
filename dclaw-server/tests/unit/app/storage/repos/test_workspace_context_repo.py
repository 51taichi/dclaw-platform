# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from sqlalchemy import insert

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.workspace_context_repo import (
    SqlAlchemyWorkspaceContextRepository,
)
from qwenpaw.app.storage.schema import chats, create_all, session_states
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def engine(tmp_path):
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")})
    engine = create_engine_from_settings(settings)
    create_all(engine)
    return engine


@pytest.fixture
def repo(engine):
    return SqlAlchemyWorkspaceContextRepository(engine)


def test_sqlalchemy_workspace_context_repo_resolves_session_and_state(engine, repo):
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
        conn.execute(
            insert(session_states),
            {
                "chat_id": "chat-1",
                "state_json": "saved as `report.md`",
            },
        )

    assert repo.get_session_id_for_chat_id("chat-1") == "session-1"
    assert repo.list_chat_identity_rows("session-1") == [
        {"id": "chat-1", "session_id": "session-1"}
    ]
    assert repo.get_session_state_texts(["chat-1", "session-1"]) == ["saved as `report.md`"]
