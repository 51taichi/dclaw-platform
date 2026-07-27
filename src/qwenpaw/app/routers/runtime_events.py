# -*- coding: utf-8 -*-
"""User runtime event stream APIs."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Query, Request
from starlette.responses import StreamingResponse

from ..chat_access import ensure_chat_access
from ..runtime.event_bus import RuntimeEvent, get_runtime_event_bus

router = APIRouter(prefix="/runtime/events", tags=["runtime-events"])

_HEARTBEAT_SECONDS = 20


@router.get("/stream")
async def stream_runtime_events(
    request: Request,
    session_id: str = Query(..., description="Root chat/session id to subscribe"),
    since_id: str | None = Query(None, description="Last consumed runtime event id"),
) -> StreamingResponse:
    """Stream user-visible runtime events for one accessible session."""
    ensure_chat_access(request, session_id, allow_admin=True)
    bus = get_runtime_event_bus()

    async def events() -> AsyncGenerator[str, None]:
        subscription = bus.subscribe(session_id=session_id, since_id=since_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(
                        subscription.__anext__(),
                        timeout=_HEARTBEAT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    yield "event: heartbeat\ndata: {}\n\n"
                    continue
                except StopAsyncIteration:
                    break
                yield _format_sse("runtime_event", event)
        finally:
            await subscription.aclose()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _format_sse(event_type: str, event: RuntimeEvent) -> str:
    data = json.dumps(event.to_dict(), ensure_ascii=False)
    return f"event: {event_type}\ndata: {data}\n\n"
