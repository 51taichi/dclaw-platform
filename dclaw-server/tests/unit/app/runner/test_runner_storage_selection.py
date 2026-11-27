# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app.runner import runner as runner_module
from qwenpaw.app.runner.runner import AgentRunner
from qwenpaw.app.runner.session_sqlalchemy import SqlAlchemySession
from qwenpaw.app.runner.session_sqlite import SqliteSession
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.mark.asyncio
async def test_agent_runner_uses_sqlite_session_by_default():
    runner = AgentRunner(agent_id="agent-a")

    await runner.init_handler()

    assert isinstance(runner.session, SqliteSession)


@pytest.mark.asyncio
async def test_agent_runner_uses_sqlalchemy_session_for_postgres_backend(
    tmp_path,
    monkeypatch,
):
    engine = create_engine_from_settings(
        get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")}),
    )
    create_all(engine)
    monkeypatch.setattr(
        runner_module,
        "get_storage_settings",
        lambda: SimpleNamespace(database_backend="postgres"),
        raising=False,
    )
    monkeypatch.setattr(
        runner_module,
        "get_app_engine",
        lambda: engine,
        raising=False,
    )
    runner = AgentRunner(agent_id="agent-a")

    await runner.init_handler()

    assert isinstance(runner.session, SqlAlchemySession)
