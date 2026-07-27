# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.app.runtime.event_bus import (
    MemoryRuntimeEventBus,
    RedisRuntimeEventBus,
    RuntimeEvent,
)


@pytest.mark.asyncio
async def test_memory_event_bus_replays_session_scoped_events_only():
    bus = MemoryRuntimeEventBus(max_events=10, max_age_seconds=60)

    first = await bus.publish(
        RuntimeEvent(
            type="approval.created",
            scope="approval",
            session_id="session-a",
            chat_id="chat-a",
            status="pending",
            message="approval needed",
            payload={"request_id": "req-1"},
        ),
    )
    await bus.publish(
        RuntimeEvent(
            type="approval.created",
            scope="approval",
            session_id="session-b",
            payload={"request_id": "req-2"},
        ),
    )
    second = await bus.publish(
        RuntimeEvent(
            type="approval.resolved",
            scope="approval",
            session_id="session-a",
            chat_id="chat-a",
            status="approved",
            payload={"request_id": "req-1"},
        ),
    )

    replay = await bus.replay(session_id="session-a", since_id=None)
    stats = await bus.stats()

    assert [event.id for event in replay] == [first.id, second.id]
    assert stats["last_published_at"] == pytest.approx(second.created_at)
    assert stats["last_event_age_seconds"] is not None
    assert replay[0].to_dict() == {
        "id": first.id,
        "type": "approval.created",
        "scope": "approval",
        "session_id": "session-a",
        "chat_id": "chat-a",
        "job_id": None,
        "status": "pending",
        "message": "approval needed",
        "payload": {"request_id": "req-1"},
        "created_at": first.created_at,
    }


@pytest.mark.asyncio
async def test_memory_event_bus_replay_since_id_is_exclusive():
    bus = MemoryRuntimeEventBus(max_events=10, max_age_seconds=60)

    first = await bus.publish(
        RuntimeEvent(type="task.progress", scope="task", session_id="session-a"),
    )
    second = await bus.publish(
        RuntimeEvent(type="task.completed", scope="task", session_id="session-a"),
    )

    replay = await bus.replay(session_id="session-a", since_id=first.id)

    assert [event.id for event in replay] == [second.id]


@pytest.mark.asyncio
async def test_redis_event_bus_replays_across_instances():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    server = fakeredis.FakeServer()
    client_a = fakeredis.FakeRedis(server=server, decode_responses=True)
    client_b = fakeredis.FakeRedis(server=server, decode_responses=True)
    writer = RedisRuntimeEventBus(
        client_a,
        namespace="testevents",
        max_events=10,
        max_age_seconds=60,
    )
    reader = RedisRuntimeEventBus(
        client_b,
        namespace="testevents",
        max_events=10,
        max_age_seconds=60,
    )

    event = await writer.publish(
        RuntimeEvent(
            type="aigc.job.updated",
            scope="aigc",
            session_id="session-a",
            job_id="job-1",
            status="queued",
        ),
    )

    replay = await reader.replay(session_id="session-a", since_id=None)
    stats = await reader.stats()

    assert [item.id for item in replay] == [event.id]
    assert replay[0].job_id == "job-1"
    assert replay[0].status == "queued"
    assert stats["last_published_at"] == pytest.approx(event.created_at)
    assert stats["last_event_age_seconds"] is not None
