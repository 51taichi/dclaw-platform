# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from contextlib import suppress

import pytest

from qwenpaw.app.runner.task_tracker import TaskTracker
from qwenpaw.app.runtime.event_bus import MemoryRuntimeEventBus
from qwenpaw.app import task_limits
from qwenpaw.app.runner import task_tracker as task_tracker_module
from qwenpaw.app.task_limits import (
    RedisTaskConcurrencyLimiter,
    TaskConcurrencyLimiter,
    create_task_limiter_from_env,
)


@pytest.mark.asyncio
async def test_task_limiter_enforces_global_limit():
    limiter = TaskConcurrencyLimiter(max_global=1, max_per_agent=10, max_per_user=10)

    permit = await limiter.try_acquire(agent_id="a", user_id="u")
    assert permit is not None
    assert await limiter.try_acquire(agent_id="b", user_id="v") is None
    snapshot = await limiter.snapshot()
    assert snapshot["rejected_acquire_count"] == 1
    assert snapshot["expired_permit_count"] == 0

    await permit.release()
    next_permit = await limiter.try_acquire(agent_id="b", user_id="v")
    assert next_permit is not None
    await next_permit.release()


@pytest.mark.asyncio
async def test_task_limiter_enforces_agent_and_user_limits():
    limiter = TaskConcurrencyLimiter(max_global=10, max_per_agent=2, max_per_user=1)

    first = await limiter.try_acquire(agent_id="agent-a", user_id="user-a")
    assert first is not None
    assert await limiter.try_acquire(agent_id="agent-b", user_id="user-a") is None

    second = await limiter.try_acquire(agent_id="agent-a", user_id="user-b")
    assert second is not None
    assert await limiter.try_acquire(agent_id="agent-a", user_id="user-c") is None
    await first.release()
    await second.release()


@pytest.mark.asyncio
async def test_task_limiter_applies_request_specific_scope_limits():
    limiter = TaskConcurrencyLimiter(
        max_global=20,
        max_per_agent=20,
        max_per_user=20,
    )

    permits = []
    for _ in range(5):
        permit = await limiter.try_acquire(
            agent_id="publication-1",
            user_id="api-key-1",
            max_per_agent=12,
            max_per_user=5,
        )
        assert permit is not None
        permits.append(permit)

    assert (
        await limiter.try_acquire(
            agent_id="publication-1",
            user_id="api-key-1",
            max_per_agent=12,
            max_per_user=5,
        )
        is None
    )

    other_key = await limiter.try_acquire(
        agent_id="publication-1",
        user_id="api-key-2",
        max_per_agent=12,
        max_per_user=5,
    )
    assert other_key is not None

    for permit in permits:
        await permit.release()
    await other_key.release()


@pytest.mark.asyncio
async def test_task_tracker_finish_callback_releases_limit_slot():
    limiter = TaskConcurrencyLimiter(max_global=1, max_per_agent=1, max_per_user=1)
    permit = await limiter.try_acquire(agent_id="agent-a", user_id="user-a")
    assert permit is not None

    tracker = TaskTracker()

    async def stream(_payload):
        yield "data: {}\n\n"

    queue, is_new = await tracker.attach_or_start(
        "chat-1",
        {},
        stream,
        on_finish=permit.release,
    )

    assert is_new is True
    async for _event in tracker.stream_from_queue(queue, "chat-1"):
        pass

    snapshot = await limiter.snapshot()
    assert snapshot["running_global"] == 0


@pytest.mark.asyncio
async def test_task_tracker_publishes_started_and_completed_events(monkeypatch):
    bus = MemoryRuntimeEventBus(max_events=20, max_age_seconds=60)
    monkeypatch.setattr(
        task_tracker_module,
        "get_runtime_event_bus",
        lambda: bus,
        raising=False,
    )
    tracker = TaskTracker()

    async def stream(_payload):
        yield "data: {}\n\n"

    queue, is_new = await tracker.attach_or_start(
        "chat-1",
        {"session_id": "session-1", "user_id": "user-1"},
        stream,
    )

    assert is_new is True
    async for _event in tracker.stream_from_queue(queue, "chat-1"):
        pass

    events = await bus.replay(session_id="session-1", since_id=None)

    assert [event.type for event in events] == ["task.started", "task.completed"]
    assert {event.chat_id for event in events} == {"chat-1"}
    assert {event.payload["user_id"] for event in events} == {"user-1"}


@pytest.mark.asyncio
async def test_task_tracker_caps_replay_buffer_by_count_and_bytes():
    tracker = TaskTracker(max_buffer_events=3, max_buffer_bytes=24)

    async def stream(_payload):
        for index in range(6):
            yield f"data: {index:02d}-payload\n\n"

    queue, is_new = await tracker.attach_or_start("chat-buffer", {}, stream)

    assert is_new is True
    async for _event in tracker.stream_from_queue(queue, "chat-buffer"):
        pass

    stats = await tracker.get_buffer_stats()
    run_stats = stats["recent_runs"]["chat-buffer"]
    assert run_stats["buffer_event_count"] <= 3
    assert run_stats["buffer_bytes"] <= 24
    assert run_stats["dropped_buffer_events"] > 0


@pytest.mark.asyncio
async def test_redis_task_limiter_enforces_global_limit_across_instances():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    server = fakeredis.FakeServer()
    limiter_a = RedisTaskConcurrencyLimiter(
        fakeredis.FakeRedis(server=server, decode_responses=True),
        namespace="testtasks",
        max_global=1,
        max_per_agent=10,
        max_per_user=10,
        permit_ttl_seconds=30,
    )
    limiter_b = RedisTaskConcurrencyLimiter(
        fakeredis.FakeRedis(server=server, decode_responses=True),
        namespace="testtasks",
        max_global=1,
        max_per_agent=10,
        max_per_user=10,
        permit_ttl_seconds=30,
    )

    permit = await limiter_a.try_acquire(agent_id="agent-a", user_id="user-a")
    assert permit is not None
    assert await limiter_b.try_acquire(agent_id="agent-b", user_id="user-b") is None

    snapshot = await limiter_b.snapshot()
    assert snapshot["backend"] == "redis"
    assert snapshot["running_global"] == 1
    assert snapshot["rejected_acquire_count"] == 1
    assert snapshot["expired_permit_count"] == 0
    assert snapshot["running_by_agent"] == {"agent-a": 1}
    assert snapshot["running_by_user"] == {"user-a": 1}

    await permit.release()
    await permit.release()

    next_permit = await limiter_b.try_acquire(agent_id="agent-b", user_id="user-b")
    assert next_permit is not None
    await next_permit.release()


@pytest.mark.asyncio
async def test_redis_task_limiter_enforces_agent_and_user_limits():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    limiter = RedisTaskConcurrencyLimiter(
        client,
        namespace="testtasksagent",
        max_global=10,
        max_per_agent=2,
        max_per_user=1,
        permit_ttl_seconds=30,
    )

    first = await limiter.try_acquire(agent_id="agent-a", user_id="user-a")
    assert first is not None
    assert await limiter.try_acquire(agent_id="agent-b", user_id="user-a") is None

    second = await limiter.try_acquire(agent_id="agent-a", user_id="user-b")
    assert second is not None
    assert await limiter.try_acquire(agent_id="agent-a", user_id="user-c") is None
    await first.release()
    await second.release()


@pytest.mark.asyncio
async def test_redis_task_limiter_applies_request_specific_scope_limits():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    limiter = RedisTaskConcurrencyLimiter(
        fakeredis.FakeRedis(decode_responses=True),
        namespace="testtasksoverrides",
        max_global=20,
        max_per_agent=20,
        max_per_user=20,
        permit_ttl_seconds=30,
    )

    permits = []
    for _ in range(5):
        permit = await limiter.try_acquire(
            agent_id="publication-1",
            user_id="api-key-1",
            max_per_agent=12,
            max_per_user=5,
        )
        assert permit is not None
        permits.append(permit)

    assert (
        await limiter.try_acquire(
            agent_id="publication-1",
            user_id="api-key-1",
            max_per_agent=12,
            max_per_user=5,
        )
        is None
    )

    for permit in permits:
        await permit.release()


@pytest.mark.asyncio
async def test_redis_task_limiter_leaked_permits_expire():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    server = fakeredis.FakeServer()
    limiter_a = RedisTaskConcurrencyLimiter(
        fakeredis.FakeRedis(server=server, decode_responses=True),
        namespace="testtasksttl",
        max_global=1,
        max_per_agent=1,
        max_per_user=1,
        permit_ttl_seconds=1,
    )
    limiter_b = RedisTaskConcurrencyLimiter(
        fakeredis.FakeRedis(server=server, decode_responses=True),
        namespace="testtasksttl",
        max_global=1,
        max_per_agent=1,
        max_per_user=1,
        permit_ttl_seconds=1,
    )

    permit = await limiter_a.try_acquire(agent_id="agent-a", user_id="user-a")
    assert permit is not None
    assert await limiter_b.try_acquire(agent_id="agent-b", user_id="user-b") is None
    permit._refresh_task.cancel()
    with suppress(asyncio.CancelledError):
        await permit._refresh_task

    await asyncio.sleep(1.1)

    recovered = await limiter_b.try_acquire(agent_id="agent-b", user_id="user-b")
    assert recovered is not None
    await recovered.release()


def test_create_task_limiter_from_env_selects_memory_by_default(monkeypatch):
    monkeypatch.setattr(
        task_limits,
        "get_storage_settings",
        lambda: type("Settings", (), {"runtime_backend": "memory", "redis_url": None})(),
    )

    limiter = create_task_limiter_from_env()

    assert isinstance(limiter, TaskConcurrencyLimiter)
    assert limiter.max_global == 32
    assert limiter.max_per_agent == 12
    assert limiter.max_per_user == 6


def test_create_task_limiter_from_env_selects_redis(monkeypatch):
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(
        task_limits,
        "get_storage_settings",
        lambda: type(
            "Settings",
            (),
            {
                "runtime_backend": "redis",
                "redis_url": "redis://example.invalid/0",
            },
        )(),
    )
    monkeypatch.setattr(task_limits, "_make_redis_client", lambda _url: client)

    limiter = create_task_limiter_from_env()

    assert isinstance(limiter, RedisTaskConcurrencyLimiter)
