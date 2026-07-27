# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.app.runtime.push_store import MemoryPushStore, RedisPushStore
from qwenpaw.app.runtime.event_bus import MemoryRuntimeEventBus


@pytest.mark.asyncio
async def test_memory_push_store_preserves_existing_take_and_recent_behavior():
    store = MemoryPushStore(max_messages=10, max_age_seconds=60)

    await store.append("session-a", "hello")
    await store.append("session-b", "world", sticky=True)

    recent = await store.get_recent()
    assert [msg["text"] for msg in recent] == ["hello", "world"]

    taken = await store.take("session-a")
    assert len(taken) == 1
    assert taken[0]["text"] == "hello"
    assert "ts" not in taken[0]

    assert [msg["text"] for msg in await store.get_recent()] == ["world"]
    assert await store.take("session-a") == []


@pytest.mark.asyncio
async def test_memory_push_store_stats_include_backend_and_bounds():
    store = MemoryPushStore(max_messages=10, max_age_seconds=60)
    await store.append("session-a", "hello")

    assert await store.stats() == {
        "backend": "memory",
        "pending_count": 1,
        "session_count": 1,
        "max_messages": 10,
        "max_age_seconds": 60,
    }


@pytest.mark.asyncio
async def test_redis_push_store_consumes_messages_across_instances():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    server = fakeredis.FakeServer()
    client_a = fakeredis.FakeRedis(server=server, decode_responses=True)
    client_b = fakeredis.FakeRedis(server=server, decode_responses=True)
    writer = RedisPushStore(client_a, namespace="testpush", max_messages=10, max_age_seconds=60)
    reader = RedisPushStore(client_b, namespace="testpush", max_messages=10, max_age_seconds=60)

    await writer.append("session-a", "hello")
    await writer.append("session-b", "world", sticky=True)

    assert [msg["text"] for msg in await reader.get_recent()] == ["hello", "world"]

    taken = await reader.take("session-a")
    assert [msg["text"] for msg in taken] == ["hello"]
    assert await reader.take("session-a") == []
    assert [msg["text"] for msg in await writer.get_recent()] == ["world"]


@pytest.mark.asyncio
async def test_redis_push_store_stats_include_backend_and_sessions():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    store = RedisPushStore(client, namespace="statspush", max_messages=10, max_age_seconds=60)

    await store.append("session-a", "hello")
    await store.append("session-b", "world")

    stats = await store.stats()

    assert stats["backend"] == "redis"
    assert stats["pending_count"] == 2
    assert stats["session_count"] == 2
    assert stats["max_messages"] == 10
    assert stats["max_age_seconds"] == 60


@pytest.mark.asyncio
async def test_console_push_append_publishes_runtime_event(monkeypatch):
    from qwenpaw.app import console_push_store

    bus = MemoryRuntimeEventBus(max_events=10, max_age_seconds=60)
    store = MemoryPushStore(max_messages=10, max_age_seconds=60)

    monkeypatch.setattr(console_push_store, "_store", store)
    monkeypatch.setattr(
        console_push_store,
        "get_runtime_event_bus",
        lambda: bus,
    )

    await console_push_store.append("session-a", "working...", sticky=True)

    events = await bus.replay(session_id="session-a", since_id=None)
    assert len(events) == 1
    assert events[0].type == "task.progress"
    assert events[0].scope == "console"
    assert events[0].message == "working..."
    assert events[0].payload == {"sticky": True}
