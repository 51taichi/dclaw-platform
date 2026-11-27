# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import audit


class FakeAuditRepository:
    def __init__(self):
        self.list_calls = []
        self.identity_calls = []

    def list_chats(self, *, user_id=None, agent_id=None, limit=50, offset=0):
        self.list_calls.append((user_id, agent_id, limit, offset))
        return [
            {
                "id": "chat-1",
                "user_id": "1",
                "agent_id": "default",
                "session_id": "session-1",
                "channel": "console",
                "meta": "{\"kind\":\"task\"}",
            }
        ]

    def get_chat_identity(self, chat_id):
        self.identity_calls.append(chat_id)
        if chat_id == "chat-1":
            return {
                "agent_id": "default",
                "session_id": "session-1",
                "user_id": "1",
                "channel": "console",
            }
        return None


def _admin_request():
    return SimpleNamespace(state=SimpleNamespace(role="admin"))


@pytest.mark.asyncio
async def test_audit_chats_uses_audit_repository(monkeypatch):
    repo = FakeAuditRepository()
    monkeypatch.setattr(audit, "get_audit_repository", lambda: repo)

    rows = await audit.get_audit_chats(
        _admin_request(),
        user_id="1",
        agent_id="default",
        limit=10,
        offset=5,
    )

    assert repo.list_calls == [("1", "default", 10, 5)]
    assert rows[0]["meta"] == {"kind": "task"}


@pytest.mark.asyncio
async def test_audit_messages_uses_audit_repository_for_chat_identity(monkeypatch, tmp_path):
    repo = FakeAuditRepository()
    monkeypatch.setattr(audit, "get_audit_repository", lambda: repo)
    monkeypatch.setattr(
        audit,
        "load_config",
        lambda: SimpleNamespace(
            agents=SimpleNamespace(
                profiles={"default": SimpleNamespace(workspace_dir=str(tmp_path))},
            ),
        ),
    )

    rows = await audit.get_audit_chat_messages(_admin_request(), "chat-1")

    assert rows == []
    assert repo.identity_calls == ["chat-1"]


@pytest.mark.asyncio
async def test_audit_routes_reject_non_admin(monkeypatch):
    monkeypatch.setattr(audit, "get_audit_repository", lambda: FakeAuditRepository())
    request = SimpleNamespace(state=SimpleNamespace(role="user"))

    with pytest.raises(HTTPException) as exc:
        await audit.get_audit_chats(request)

    assert exc.value.status_code == 403
