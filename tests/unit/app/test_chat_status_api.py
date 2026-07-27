# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.runner.api import get_chat_manager, get_workspace, router
from qwenpaw.app.runner.manager import ChatManager
from qwenpaw.app.runner.models import ChatSpec
from qwenpaw.app.runner.repo.json_repo import JsonChatRepository


@pytest.fixture
def chat_manager(tmp_path):
    return ChatManager(repo=JsonChatRepository(tmp_path / "chats.json"))


@pytest.fixture
def api_client(chat_manager, monkeypatch):
    app = FastAPI()

    @app.middleware("http")
    async def add_test_user_context(request, call_next):
        request.state.user_id = "default"
        request.state.role = "user"
        return await call_next(request)

    class _Tracker:
        async def get_status(self, chat_id: str) -> str:
            assert chat_id == "chat-1"
            return "running"

    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_chat_manager] = lambda: chat_manager
    app.dependency_overrides[get_workspace] = lambda: SimpleNamespace(
        task_tracker=_Tracker(),
    )

    def ensure_owned_test_chat(_request, chat_id: str, *, allow_admin: bool = False):
        _ = allow_admin
        if chat_id == "chat-1":
            return {
                "id": "chat-1",
                "user_id": "default",
                "agent_id": "default",
                "session_id": "console:default",
                "channel": "console",
                "meta": "{}",
            }
        raise HTTPException(status_code=404, detail="Chat not found")

    monkeypatch.setattr(
        "qwenpaw.app.runner.api.ensure_chat_access",
        ensure_owned_test_chat,
    )
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_get_chat_status_returns_lightweight_metadata(api_client, chat_manager):
    updated_at = datetime(2026, 6, 6, tzinfo=timezone.utc)
    await chat_manager.create_chat(
        ChatSpec(
            id="chat-1",
            name="Perf Chat",
            session_id="console:default",
            user_id="default",
            channel="console",
            task_status="in_progress",
            updated_at=updated_at,
        ),
    )

    async with api_client:
        response = await api_client.get("/api/chats/chat-1/status")

    assert response.status_code == 200
    assert response.json() == {
        "id": "chat-1",
        "status": "running",
        "task_status": "in_progress",
        "updated_at": "2026-06-06T00:00:00Z",
        "message_count": 0,
    }

