# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from qwenpaw.app.runner.control_commands.approval_handler import (
    ApprovalCommandHandler,
)
from qwenpaw.app.runner.control_commands.base import ControlContext


def _context(*, all_sessions: bool = False) -> ControlContext:
    return ControlContext(
        workspace=SimpleNamespace(),
        payload={},
        channel=SimpleNamespace(),
        session_id="root-a",
        user_id="user-a",
        agent_id="agent-a",
        args={"action": "list", "all": all_sessions},
    )


def _record():
    return SimpleNamespace(
        request_id="request-1234567890",
        session_id="child-a",
        root_session_id="root-a",
        agent_id="agent-a",
        tool_name="execute_shell_command",
        severity="HIGH",
        findings_count=1,
        created_at=time.time(),
    )


@pytest.mark.asyncio
async def test_approval_list_command_uses_root_session_metadata(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeApprovalService:
        async def list_pending_metadata_by_root_session(self, root_session_id):
            calls.append(("root", root_session_id))
            return [_record()]

    monkeypatch.setattr(
        "qwenpaw.app.runner.control_commands.approval_handler.get_approval_service",
        lambda: FakeApprovalService(),
    )

    result = await ApprovalCommandHandler().handle(_context())

    assert calls == [("root", "root-a")]
    assert "execute_shell_command" in result
    assert "request-12345678" in result


@pytest.mark.asyncio
async def test_approval_list_all_command_uses_agent_metadata(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeApprovalService:
        async def list_pending_metadata_by_agent(self, agent_id):
            calls.append(("agent", agent_id))
            return [_record()]

    monkeypatch.setattr(
        "qwenpaw.app.runner.control_commands.approval_handler.get_approval_service",
        lambda: FakeApprovalService(),
    )

    result = await ApprovalCommandHandler().handle(_context(all_sessions=True))

    assert calls == [("agent", "agent-a")]
    assert "execute_shell_command" in result
