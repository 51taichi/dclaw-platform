# -*- coding: utf-8 -*-
"""Console channel push messages with memory/Redis runtime backends."""
from __future__ import annotations

import logging
from typing import Any

from redis import asyncio as redis_asyncio

from .runtime.event_bus import RuntimeEvent, get_runtime_event_bus
from .runtime.push_store import MemoryPushStore, RedisPushStore, PushStore
from .storage.settings import get_storage_settings

_MAX_AGE_SECONDS = 60
_MAX_MESSAGES = 500
_store: PushStore | None = None
logger = logging.getLogger(__name__)


def _make_redis_client(redis_url: str):
    return redis_asyncio.from_url(redis_url, decode_responses=True)


def _get_store() -> PushStore:
    global _store
    if _store is not None:
        return _store

    settings = get_storage_settings()
    if settings.runtime_backend == "redis":
        if not settings.redis_url:
            raise RuntimeError("QWENPAW_REDIS_URL is required for Redis push store")
        _store = RedisPushStore(
            _make_redis_client(settings.redis_url),
            max_messages=_MAX_MESSAGES,
            max_age_seconds=_MAX_AGE_SECONDS,
        )
    else:
        _store = MemoryPushStore(
            max_messages=_MAX_MESSAGES,
            max_age_seconds=_MAX_AGE_SECONDS,
        )
    return _store


def reset_store_for_tests() -> None:
    """Reset the cached store. Intended for tests and reload boundaries."""
    global _store
    _store = None


async def append(session_id: str, text: str, *, sticky: bool = False) -> None:
    """Append a message for a session."""
    await _get_store().append(session_id, text, sticky=sticky)
    await _publish_runtime_event(
        RuntimeEvent(
            type="task.progress",
            scope="console",
            session_id=session_id,
            status="sticky" if sticky else "info",
            message=text,
            payload={"sticky": sticky},
        ),
    )


async def take(session_id: str) -> list[dict[str, Any]]:
    """Return and remove all messages for the session."""
    return await _get_store().take(session_id)


async def take_all() -> list[dict[str, Any]]:
    """Return and remove all non-expired messages from the store."""
    return await _get_store().take_all()


async def get_recent(
    max_age_seconds: int = _MAX_AGE_SECONDS,
) -> list[dict[str, Any]]:
    """Return recent messages without consuming them."""
    return await _get_store().get_recent(max_age_seconds)


async def stats() -> dict[str, Any]:
    """Return bounded store counters for admin diagnostics."""
    return await _get_store().stats()


async def _publish_runtime_event(event: RuntimeEvent) -> None:
    try:
        await get_runtime_event_bus().publish(event)
    except Exception:  # pragma: no cover - defensive diagnostics
        logger.exception(
            "Failed to publish console runtime event: type=%s session=%s",
            event.type,
            event.session_id,
        )
