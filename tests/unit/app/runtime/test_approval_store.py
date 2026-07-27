# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import time

import pytest

from qwenpaw.app.runtime.approval_store import (
    ApprovalRecord,
    MemoryApprovalStore,
    RedisApprovalStore,
)


def _record(
    request_id: str,
    *,
    session_id: str = "session-a",
    root_session_id: str = "root-a",
    agent_id: str = "agent-a",
    created_at: float | None = None,
) -> ApprovalRecord:
    return ApprovalRecord(
        request_id=request_id,
        session_id=session_id,
        root_session_id=root_session_id,
        owner_agent_id="owner-a",
        user_id="user-a",
        channel="console",
        agent_id=agent_id,
        tool_name="execute_shell_command",
        created_at=time.time() if created_at is None else created_at,
        timeout_seconds=300.0,
        result_summary="dangerous command",
        findings_count=1,
        severity="HIGH",
        extra={"tool_call": {"input": {"command": "rm -rf /tmp/x"}}},
    )


@pytest.mark.asyncio
async def test_memory_approval_store_filters_pending_records_and_stats():
    store = MemoryApprovalStore(max_records=10, max_age_seconds=60)
    base = time.time()
    await store.put(_record("req-1", created_at=base))
    await store.put(
        _record(
            "req-2",
            session_id="session-b",
            root_session_id="root-b",
            agent_id="agent-b",
            created_at=base + 1,
        ),
    )

    assert [r.request_id for r in await store.list_all_pending()] == [
        "req-1",
        "req-2",
    ]
    assert [r.request_id for r in await store.list_pending_by_session("session-a")] == [
        "req-1",
    ]
    assert [r.request_id for r in await store.list_pending_by_root_session("root-b")] == [
        "req-2",
    ]
    assert [r.request_id for r in await store.list_pending_by_agent("agent-b")] == [
        "req-2",
    ]
    assert await store.stats() == {
        "backend": "memory",
        "pending_count": 2,
        "session_count": 2,
        "root_session_count": 2,
        "agent_count": 2,
        "max_records": 10,
        "max_age_seconds": 60,
    }

    popped = await store.pop("req-1")

    assert popped is not None
    assert popped.tool_name == "execute_shell_command"
    assert await store.get("req-1") is None
    assert [r.request_id for r in await store.list_all_pending()] == ["req-2"]


@pytest.mark.asyncio
async def test_redis_approval_store_shares_records_and_cleans_indexes():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    server = fakeredis.FakeServer()
    client_a = fakeredis.FakeRedis(server=server, decode_responses=True)
    client_b = fakeredis.FakeRedis(server=server, decode_responses=True)
    writer = RedisApprovalStore(
        client_a,
        namespace="testapproval",
        max_records=10,
        max_age_seconds=60,
    )
    reader = RedisApprovalStore(
        client_b,
        namespace="testapproval",
        max_records=10,
        max_age_seconds=60,
    )

    base = time.time()
    await writer.put(_record("req-1", created_at=base))
    await writer.put(_record("req-2", session_id="session-b", created_at=base + 1))

    assert [r.request_id for r in await reader.list_all_pending()] == [
        "req-1",
        "req-2",
    ]
    assert (await reader.get("req-1")).extra["tool_call"]["input"]["command"] == (
        "rm -rf /tmp/x"
    )
    assert [r.request_id for r in await reader.list_pending_by_session("session-a")] == [
        "req-1",
    ]

    popped = await reader.pop("req-1")

    assert popped is not None
    assert popped.request_id == "req-1"
    assert await writer.get("req-1") is None
    assert await writer.list_pending_by_session("session-a") == []
    assert [r.request_id for r in await writer.list_all_pending()] == ["req-2"]

    stats = await reader.stats()
    assert stats["backend"] == "redis"
    assert stats["pending_count"] == 1
    assert stats["session_count"] == 1


@pytest.mark.asyncio
async def test_redis_approval_store_publishes_resolution_across_instances():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    server = fakeredis.FakeServer()
    client_a = fakeredis.FakeRedis(server=server, decode_responses=True)
    client_b = fakeredis.FakeRedis(server=server, decode_responses=True)
    writer = RedisApprovalStore(
        client_a,
        namespace="testapprovalresolve",
        max_records=10,
        max_age_seconds=60,
    )
    reader = RedisApprovalStore(
        client_b,
        namespace="testapprovalresolve",
        max_records=10,
        max_age_seconds=60,
    )

    waiter = asyncio.create_task(
        reader.wait_for_resolution("req-1", timeout_seconds=1),
    )
    await asyncio.sleep(0)

    await writer.publish_resolution("req-1", "approved")

    assert await waiter == "approved"
