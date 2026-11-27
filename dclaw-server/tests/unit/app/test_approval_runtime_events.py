# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.app.approvals.service import ApprovalService
from qwenpaw.app.runtime.approval_store import MemoryApprovalStore
from qwenpaw.app.runtime.event_bus import MemoryRuntimeEventBus
from qwenpaw.security.tool_guard.approval import ApprovalDecision
from qwenpaw.security.tool_guard.models import ToolGuardResult


@pytest.mark.asyncio
async def test_approval_lifecycle_publishes_runtime_events(monkeypatch):
    from qwenpaw.app.approvals import service as approval_service_module

    bus = MemoryRuntimeEventBus(max_events=10, max_age_seconds=60)
    svc = ApprovalService(
        metadata_store=MemoryApprovalStore(max_records=10, max_age_seconds=60),
    )

    monkeypatch.setattr(
        approval_service_module,
        "get_runtime_event_bus",
        lambda: bus,
    )

    pending = await svc.create_pending(
        session_id="child-session",
        root_session_id="root-session",
        owner_agent_id="leader",
        user_id="user-1",
        channel="console",
        agent_id="agent-1",
        tool_name="execute_shell_command",
        result=ToolGuardResult(
            tool_name="execute_shell_command",
            params={"command": "rm -rf /tmp/x"},
        ),
        timeout_seconds=300,
        extra={"tool_call": {"input": {"command": "rm -rf /tmp/x"}}},
    )

    await svc.resolve_request(pending.request_id, ApprovalDecision.APPROVED)

    events = await bus.replay(session_id="root-session", since_id=None)
    assert [event.type for event in events] == [
        "approval.created",
        "approval.resolved",
    ]
    assert events[0].scope == "approval"
    assert events[0].status == "pending"
    assert events[0].payload["request_id"] == pending.request_id
    assert events[0].payload["tool_name"] == "execute_shell_command"
    assert events[1].status == "approved"
    assert events[1].payload["request_id"] == pending.request_id
