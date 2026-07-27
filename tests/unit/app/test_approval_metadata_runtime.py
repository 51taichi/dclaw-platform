# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio

import pytest

from qwenpaw.app.approvals.service import ApprovalService
from qwenpaw.app.runtime.approval_store import MemoryApprovalStore, RedisApprovalStore
from qwenpaw.security.tool_guard.approval import ApprovalDecision
from qwenpaw.security.tool_guard.models import (
    GuardFinding,
    GuardSeverity,
    GuardThreatCategory,
    ToolGuardResult,
)


def _guard_result() -> ToolGuardResult:
    return ToolGuardResult(
        tool_name="execute_shell_command",
        params={"command": "rm -rf /tmp/x"},
        findings=[
            GuardFinding(
                id="finding-1",
                rule_id="dangerous-rm",
                category=GuardThreatCategory.RESOURCE_ABUSE,
                severity=GuardSeverity.HIGH,
                title="Dangerous rm",
                description="Dangerous shell command",
                tool_name="execute_shell_command",
                param_name="command",
            ),
        ],
    )


async def _create_pending(svc: ApprovalService):
    return await svc.create_pending(
        session_id="session-a",
        root_session_id="root-a",
        owner_agent_id="owner-a",
        user_id="user-a",
        channel="console",
        agent_id="agent-a",
        tool_name="execute_shell_command",
        result=_guard_result(),
        timeout_seconds=300,
        extra={"tool_call": {"input": {"command": "rm -rf /tmp/x"}}},
    )


@pytest.mark.asyncio
async def test_approval_service_writes_and_deletes_metadata_records():
    store = MemoryApprovalStore(max_records=10, max_age_seconds=60)
    svc = ApprovalService(metadata_store=store)

    pending = await _create_pending(svc)

    visible = await svc.list_all_pending()
    assert [record.request_id for record in visible] == [pending.request_id]
    assert visible[0].extra["tool_call"]["input"]["command"] == "rm -rf /tmp/x"
    assert (await svc.metadata_stats())["pending_count"] == 1

    resolved = await svc.resolve_request(
        pending.request_id,
        ApprovalDecision.APPROVED,
    )

    assert resolved is pending
    assert await svc.list_all_pending() == []
    assert (await svc.metadata_stats())["pending_count"] == 0


@pytest.mark.asyncio
async def test_approval_service_can_share_metadata_through_redis_store():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    server = fakeredis.FakeServer()
    client_a = fakeredis.FakeRedis(server=server, decode_responses=True)
    client_b = fakeredis.FakeRedis(server=server, decode_responses=True)
    store_a = RedisApprovalStore(
        client_a,
        namespace="serviceapproval",
        max_records=10,
        max_age_seconds=60,
    )
    store_b = RedisApprovalStore(
        client_b,
        namespace="serviceapproval",
        max_records=10,
        max_age_seconds=60,
    )
    writer = ApprovalService(metadata_store=store_a)
    reader = ApprovalService(metadata_store=store_b)

    pending = await _create_pending(writer)

    assert [record.request_id for record in await reader.list_all_pending()] == [
        pending.request_id,
    ]

    await writer.resolve_request(pending.request_id, ApprovalDecision.DENIED)

    assert await reader.list_all_pending() == []


@pytest.mark.asyncio
async def test_approval_service_resolves_remote_redis_approval_and_wakes_waiter():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    server = fakeredis.FakeServer()
    client_a = fakeredis.FakeRedis(server=server, decode_responses=True)
    client_b = fakeredis.FakeRedis(server=server, decode_responses=True)
    store_a = RedisApprovalStore(
        client_a,
        namespace="serviceapprovalwake",
        max_records=10,
        max_age_seconds=60,
    )
    store_b = RedisApprovalStore(
        client_b,
        namespace="serviceapprovalwake",
        max_records=10,
        max_age_seconds=60,
    )
    holder = ApprovalService(metadata_store=store_a)
    web_worker = ApprovalService(metadata_store=store_b)

    pending = await _create_pending(holder)
    waiter = asyncio.create_task(
        holder.wait_for_approval(pending.request_id, timeout_seconds=1),
    )
    await asyncio.sleep(0)

    remote_pending = await web_worker.get_request(pending.request_id)
    assert remote_pending is not None
    assert remote_pending.root_session_id == "root-a"

    resolved = await web_worker.resolve_request(
        pending.request_id,
        ApprovalDecision.APPROVED,
    )

    assert resolved is not None
    assert resolved.tool_name == "execute_shell_command"
    assert await waiter == ApprovalDecision.APPROVED
    assert await web_worker.list_all_pending() == []
