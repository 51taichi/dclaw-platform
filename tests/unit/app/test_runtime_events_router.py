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
