# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.runtime.event_bus import MemoryRuntimeEventBus, RuntimeEvent


@pytest.mark.asyncio
async def test_runtime_event_stream_requires_session_access(monkeypatch):
    from qwenpaw.app.routers import runtime_events

    def deny_access(*_args, **_kwargs):
        raise HTTPException(status_code=404, detail="Chat not found")

    monkeypatch.setattr(runtime_events, "ensure_chat_access", deny_access)

    with pytest.raises(HTTPException) as exc:
        await runtime_events.stream_runtime_events(
            SimpleNamespace(state=SimpleNamespace(user_id=1, role="user")),
            session_id="session-a",
            since_id=None,
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_runtime_event_stream_replays_existing_session_event(monkeypatch):
    from qwenpaw.app.routers import runtime_events

    bus = MemoryRuntimeEventBus(max_events=10, max_age_seconds=60)
    event = await bus.publish(
        RuntimeEvent(
            type="approval.created",
            scope="approval",
            session_id="session-a",
            chat_id="chat-a",
            status="pending",
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

    monkeypatch.setattr(runtime_events, "ensure_chat_access", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runtime_events, "get_runtime_event_bus", lambda: bus)

    response = await runtime_events.stream_runtime_events(
        SimpleNamespace(state=SimpleNamespace(user_id=1, role="user")),
        session_id="session-a",
        since_id=None,
    )
    chunk = await response.body_iterator.__anext__()
    text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk

    assert text.startswith("event: runtime_event\n")
    payload = json.loads(text.split("data: ", 1)[1])
    assert payload["id"] == event.id
    assert payload["session_id"] == "session-a"
    assert payload["payload"] == {"request_id": "req-1"}


@pytest.mark.asyncio
async def test_runtime_event_stream_resolves_public_chat_id_to_runtime_session(
    monkeypatch,
):
    """A browser chat UUID must receive events published to its runtime session."""
    from qwenpaw.app.routers import runtime_events

    bus = MemoryRuntimeEventBus(max_events=10, max_age_seconds=60)
    event = await bus.publish(
        RuntimeEvent(
            type="aigc.task.created",
            scope="super_expert",
            session_id="luyu-aigc-test-20260904",
            chat_id="f2294f76-4e08-4d83-8bb4-aad52344488e",
            status="WAITING_TO_START",
            payload={"material_task_id": "material-1"},
        ),
    )

    monkeypatch.setattr(
        runtime_events,
        "ensure_chat_access",
        lambda *_args, **_kwargs: {
            "id": "f2294f76-4e08-4d83-8bb4-aad52344488e",
            "session_id": "luyu-aigc-test-20260904",
            "user_id": 1,
        },
    )
    monkeypatch.setattr(runtime_events, "get_runtime_event_bus", lambda: bus)
    monkeypatch.setattr(runtime_events, "_HEARTBEAT_SECONDS", 0.01)

    response = await runtime_events.stream_runtime_events(
        SimpleNamespace(state=SimpleNamespace(user_id=1, role="user")),
        session_id="f2294f76-4e08-4d83-8bb4-aad52344488e",
        since_id=None,
    )
    chunk = await response.body_iterator.__anext__()
    text = chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk

    assert text.startswith("event: runtime_event\n")
    payload = json.loads(text.split("data: ", 1)[1])
    assert payload["id"] == event.id
    assert payload["session_id"] == "luyu-aigc-test-20260904"
