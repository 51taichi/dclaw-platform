# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from qwenpaw.app.routers import console as console_router
from qwenpaw.app.runtime.approval_store import ApprovalRecord


def _approval_record(request_id: str, root_session_id: str) -> ApprovalRecord:
    return ApprovalRecord(
        request_id=request_id,
        session_id=root_session_id,
        root_session_id=root_session_id,
        owner_agent_id="default",
        user_id="1",
        channel="console",
        agent_id="default",
        tool_name="execute_shell_command",
        created_at=time.time(),
        timeout_seconds=300,
        result_summary="dangerous command",
        findings_count=1,
        severity="HIGH",
        extra={"tool_call": {"input": {"command": "rm -rf /tmp/x"}}},
    )


@pytest.mark.asyncio
async def test_push_messages_uses_root_session_approval_lookup(monkeypatch):
    calls: list[tuple[str, str | None]] = []

    async def fake_take(_session_id):
        return []

    class FakeApprovalService:
        async def list_all_pending(self):
            raise AssertionError("session polling must not scan all approvals")

        async def list_pending_metadata_by_root_session(self, root_session_id):
            calls.append(("root", root_session_id))
            return [_approval_record("req-1", root_session_id)]

    monkeypatch.setattr(console_router, "ensure_chat_access", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(console_router, "is_admin_request", lambda _request: False)
    monkeypatch.setattr(
        "qwenpaw.app.console_push_store.take",
        fake_take,
    )
    monkeypatch.setattr(
        "qwenpaw.app.approvals.get_approval_service",
        lambda: FakeApprovalService(),
    )

    request = SimpleNamespace(state=SimpleNamespace(user_id=1, role="user"))
    response = await console_router.get_push_messages(request, session_id="session-1")

    assert calls == [("root", "session-1")]
    assert [item["request_id"] for item in response["pending_approvals"]] == ["req-1"]


@pytest.mark.asyncio
async def test_push_messages_without_session_hides_user_approvals(monkeypatch):
    async def fake_get_recent():
        return []

    class FakeApprovalService:
        async def list_all_pending(self):
            raise AssertionError("user global polling must not scan approvals")

    monkeypatch.setattr(console_router, "is_admin_request", lambda _request: False)
    monkeypatch.setattr(
        "qwenpaw.app.console_push_store.get_recent",
        fake_get_recent,
    )
    monkeypatch.setattr(
        "qwenpaw.app.approvals.get_approval_service",
        lambda: FakeApprovalService(),
    )

    request = SimpleNamespace(state=SimpleNamespace(user_id=1, role="user"))
    response = await console_router.get_push_messages(request, session_id=None)

    assert response == {"messages": [], "pending_approvals": []}
