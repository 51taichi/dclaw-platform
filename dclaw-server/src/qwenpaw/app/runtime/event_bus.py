# -*- coding: utf-8 -*-
"""Runtime event bus for user-visible agent progress updates."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncGenerator, Protocol

from ..storage.settings import get_storage_settings


@dataclass
class RuntimeEvent:
    """Serializable event emitted by long-running user workflows."""

    type: str
    scope: str
    id: str = ""
    session_id: str | None = None
    chat_id: str | None = None
    job_id: str | None = None
    status: str | None = None
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RuntimeEvent":
        return cls(
            id=str(raw.get("id") or ""),
            type=str(raw["type"]),
            scope=str(raw["scope"]),
            session_id=_optional_str(raw.get("session_id")),
            chat_id=_optional_str(raw.get("chat_id")),
            job_id=_optional_str(raw.get("job_id")),
            status=_optional_str(raw.get("status")),
            message=str(raw.get("message") or ""),
            payload=dict(raw.get("payload") or {}),
            created_at=float(raw.get("created_at") or 0.0),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeEventBus(Protocol):
    backend: str

    async def publish(self, event: RuntimeEvent) -> RuntimeEvent:
        ...

    async def replay(
        self,
        *,
        session_id: str | None,
        since_id: str | None,
        limit: int | None = None,
    ) -> list[RuntimeEvent]:
        ...

    async def subscribe(
        self,
        *,
        session_id: str | None,
        since_id: str | None = None,
    ) -> AsyncGenerator[RuntimeEvent, None]:
        ...

    async def stats(self) -> dict[str, Any]:
        ...


class MemoryRuntimeEventBus:
    """Bounded in-process runtime event bus."""

    backend = "memory"

    def __init__(self, *, max_events: int, max_age_seconds: int) -> None:
        self.max_events = max_events
        self.max_age_seconds = max_age_seconds
        self._events: list[RuntimeEvent] = []
        self._condition = asyncio.Condition()
        self._active_subscribers = 0
        self._published_count = 0
        self._sequence = 0
        self._dropped_count = 0
        self._replay_count = 0
        self._last_published_at = 0.0

    async def publish(self, event: RuntimeEvent) -> RuntimeEvent:
        if not event.id:
            self._sequence += 1
            event.id = f"{int(time.time() * 1000)}-{self._sequence:012d}"
        prepared = _prepare_event(event)
        async with self._condition:
            self._events.append(prepared)
            self._published_count += 1
            self._last_published_at = prepared.created_at
            self._trim_locked()
            self._condition.notify_all()
        return prepared

    async def replay(
        self,
        *,
        session_id: str | None,
        since_id: str | None,
        limit: int | None = None,
    ) -> list[RuntimeEvent]:
        async with self._condition:
            self._prune_expired_locked()
            events = [
                event
                for event in self._events
                if _matches_session(event, session_id)
                and _event_after_since_id(event, since_id)
            ]
            if limit is not None:
                events = events[-limit:]
            self._replay_count += len(events)
            return list(events)

    async def subscribe(
        self,
        *,
        session_id: str | None,
        since_id: str | None = None,
    ) -> AsyncGenerator[RuntimeEvent, None]:
        replayed = await self.replay(session_id=session_id, since_id=since_id)
        last_id = since_id or ""
        for event in replayed:
            last_id = event.id
            yield event

        async with self._condition:
            self._active_subscribers += 1
        try:
            while True:
                async with self._condition:
                    await self._condition.wait()
                    self._prune_expired_locked()
                    events = [
                        event
                        for event in self._events
                        if _matches_session(event, session_id)
                        and _event_after_since_id(event, last_id)
                    ]
                for event in events:
                    last_id = event.id
                    yield event
        finally:
            async with self._condition:
                self._active_subscribers = max(0, self._active_subscribers - 1)

    async def stats(self) -> dict[str, Any]:
        async with self._condition:
            self._prune_expired_locked()
            return {
                "backend": self.backend,
                "active_subscribers": self._active_subscribers,
                "replay_buffer_size": len(self._events),
                "max_events": self.max_events,
                "max_age_seconds": self.max_age_seconds,
                "published_count": self._published_count,
                "replayed_count": self._replay_count,
                "dropped_count": self._dropped_count,
                "last_published_at": self._last_published_at or None,
                "last_event_age_seconds": _age_seconds(self._last_published_at),
            }

    def _trim_locked(self) -> None:
        self._prune_expired_locked()
        overflow = len(self._events) - self.max_events
        if overflow <= 0:
            return
        del self._events[:overflow]
        self._dropped_count += overflow

    def _prune_expired_locked(self) -> None:
        cutoff = time.time() - self.max_age_seconds
        before = len(self._events)
        self._events[:] = [
            event for event in self._events if event.created_at >= cutoff
        ]
        self._dropped_count += before - len(self._events)


class RedisRuntimeEventBus:
    """Redis stream-backed runtime event bus shared across app processes."""

    backend = "redis"

    def __init__(
        self,
        client,
        *,
        namespace: str = "qwenpaw:runtime-events",
        max_events: int,
        max_age_seconds: int,
    ) -> None:
        self.client = client
        self.namespace = namespace.rstrip(":")
        self.max_events = max_events
        self.max_age_seconds = max_age_seconds
        self._active_subscribers = 0
        self._published_count = 0
        self._replay_count = 0
        self._last_published_at = 0.0

    async def publish(self, event: RuntimeEvent) -> RuntimeEvent:
        prepared = _prepare_event(event, keep_id=False)
        stream_id = await self.client.xadd(
            self._stream_key(),
            {"data": json.dumps(prepared.to_dict(), ensure_ascii=False)},
            maxlen=self.max_events,
            approximate=True,
        )
        prepared.id = str(stream_id)
        self._published_count += 1
        self._last_published_at = prepared.created_at
        return prepared

    async def replay(
        self,
        *,
        session_id: str | None,
        since_id: str | None,
        limit: int | None = None,
    ) -> list[RuntimeEvent]:
        raw_items = await self.client.xrevrange(
            self._stream_key(),
            max="+",
            min="-",
            count=limit or self.max_events,
        )
        events: list[RuntimeEvent] = []
        for raw_id, fields in reversed(raw_items):
            event = _event_from_redis(raw_id, fields)
            if _matches_session(event, session_id) and _event_after_since_id(
                event,
                since_id,
            ):
                events.append(event)
        if limit is not None:
            events = events[-limit:]
        self._replay_count += len(events)
        return events

    async def subscribe(
        self,
        *,
        session_id: str | None,
        since_id: str | None = None,
    ) -> AsyncGenerator[RuntimeEvent, None]:
        replayed = await self.replay(session_id=session_id, since_id=since_id)
        last_id = since_id or "$"
        for event in replayed:
            last_id = event.id
            yield event
        if last_id == "":
            last_id = "$"

        self._active_subscribers += 1
        try:
            while True:
                response = await self.client.xread(
                    streams={self._stream_key(): last_id},
                    count=10,
                    block=1000,
                )
                if not response:
                    continue
                for _stream, items in response:
                    for raw_id, fields in items:
                        event = _event_from_redis(raw_id, fields)
                        last_id = event.id
                        if _matches_session(event, session_id):
                            yield event
        finally:
            self._active_subscribers = max(0, self._active_subscribers - 1)

    async def stats(self) -> dict[str, Any]:
        try:
            size = int(await self.client.xlen(self._stream_key()))
        except Exception:  # pragma: no cover - diagnostics only
            size = 0
        last_published_at = self._last_published_at
        try:
            latest = await self.client.xrevrange(
                self._stream_key(),
                max="+",
                min="-",
                count=1,
            )
            if latest:
                event = _event_from_redis(latest[0][0], latest[0][1])
                last_published_at = max(last_published_at, event.created_at)
        except Exception:  # pragma: no cover - diagnostics only
            pass
        return {
            "backend": self.backend,
            "active_subscribers": self._active_subscribers,
            "replay_buffer_size": size,
            "max_events": self.max_events,
            "max_age_seconds": self.max_age_seconds,
            "published_count": self._published_count,
            "replayed_count": self._replay_count,
            "dropped_count": 0,
            "last_published_at": last_published_at or None,
            "last_event_age_seconds": _age_seconds(last_published_at),
        }

    def _stream_key(self) -> str:
        return f"{self.namespace}:stream"


def _prepare_event(event: RuntimeEvent, *, keep_id: bool = True) -> RuntimeEvent:
    data = RuntimeEvent.from_dict(event.to_dict())
    if not keep_id or not data.id:
        data.id = _make_memory_event_id()
    if not data.created_at:
        data.created_at = time.time()
    if data.payload is None:
        data.payload = {}
    return data


def _make_memory_event_id() -> str:
    return f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:10]}"


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _matches_session(event: RuntimeEvent, session_id: str | None) -> bool:
    if not session_id:
        return True
    return event.session_id == session_id


def _event_after_since_id(event: RuntimeEvent, since_id: str | None) -> bool:
    if not since_id:
        return True
    return _event_id_key(event.id) > _event_id_key(since_id)


def _age_seconds(timestamp: float) -> float | None:
    if not timestamp:
        return None
    return max(0.0, time.time() - timestamp)


def _event_id_key(event_id: str) -> tuple[int, str]:
    first, _, rest = str(event_id or "").partition("-")
    try:
        number = int(first)
    except ValueError:
        number = 0
    return number, rest


def _event_from_redis(raw_id: Any, fields: dict[str, Any]) -> RuntimeEvent:
    raw_data = fields.get("data")
    if isinstance(raw_data, bytes):
        raw_data = raw_data.decode("utf-8")
    data = json.loads(raw_data or "{}")
    event = RuntimeEvent.from_dict(data)
    event.id = str(raw_id)
    return event


_event_bus: RuntimeEventBus | None = None


def _make_redis_client(redis_url: str):
    from redis import asyncio as redis_asyncio

    return redis_asyncio.from_url(redis_url, decode_responses=True)


def get_runtime_event_bus() -> RuntimeEventBus:
    """Return the process-wide runtime event bus singleton."""
    global _event_bus
    if _event_bus is not None:
        return _event_bus

    settings = get_storage_settings()
    if settings.runtime_backend == "redis":
        if not settings.redis_url:
            raise RuntimeError(
                "QWENPAW_REDIS_URL is required for Redis runtime event bus",
            )
        _event_bus = RedisRuntimeEventBus(
            _make_redis_client(settings.redis_url),
            max_events=1000,
            max_age_seconds=3600,
        )
    else:
        _event_bus = MemoryRuntimeEventBus(
            max_events=1000,
            max_age_seconds=3600,
        )
    return _event_bus


def reset_runtime_event_bus_for_tests() -> None:
    """Reset cached runtime event bus. Intended for tests/reload boundaries."""
    global _event_bus
    _event_bus = None
