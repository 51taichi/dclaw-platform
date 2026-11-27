# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app.runner.repo.sqlite_repo import SqliteChatRepository
from qwenpaw.app.runner.repo.sqlalchemy_repo import SqlAlchemyChatRepository
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings
from qwenpaw.app.workspace import service_factories


class _FakeRunner:
    def __init__(self) -> None:
        self.chat_manager = None
        self.workspace = None

    def set_chat_manager(self, chat_manager) -> None:
        self.chat_manager = chat_manager

    def set_workspace(self, workspace) -> None:
        self.workspace = workspace

    async def stream_query(self, request):
        _ = request
        if False:
            yield None


class _FakeWorkspace:
    def __init__(self, workspace_dir=None) -> None:
        self.agent_id = "agent-a"
        self.workspace_dir = workspace_dir
        self._config = SimpleNamespace(channels=None)
        self._runner = _FakeRunner()
        self._service_manager = SimpleNamespace(
            services={"runner": self._runner},
        )


@pytest.mark.asyncio
async def test_create_chat_service_uses_sqlite_repository_by_default():
    ws = _FakeWorkspace()

    await service_factories.create_chat_service(ws, None)

    chat_manager = ws._service_manager.services["chat_manager"]
    assert isinstance(chat_manager._repo, SqliteChatRepository)
    assert ws._runner.chat_manager is chat_manager


@pytest.mark.asyncio
async def test_create_chat_service_uses_sqlalchemy_repository_for_postgres_backend(
    tmp_path,
    monkeypatch,
):
    engine = create_engine_from_settings(
        get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "qwenpaw.db")}),
    )
    create_all(engine)
    monkeypatch.setattr(
        service_factories,
        "get_storage_settings",
        lambda: SimpleNamespace(database_backend="postgres"),
        raising=False,
    )
    monkeypatch.setattr(
        service_factories,
        "get_app_engine",
        lambda: engine,
        raising=False,
    )
    ws = _FakeWorkspace()

    await service_factories.create_chat_service(ws, None)

    chat_manager = ws._service_manager.services["chat_manager"]
    assert isinstance(chat_manager._repo, SqlAlchemyChatRepository)
    assert ws._runner.chat_manager is chat_manager


@pytest.mark.asyncio
async def test_create_channel_service_defaults_to_console_when_channels_omitted(
    tmp_path,
):
    ws = _FakeWorkspace(tmp_path)

    manager = await service_factories.create_channel_service(ws, None)
    console_channel = await manager.get_channel("console")

    assert ws._service_manager.services["channel_manager"] is manager
    assert console_channel is not None
    assert console_channel.enabled is True
    assert ws._runner.workspace is ws
