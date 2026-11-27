# -*- coding: utf-8 -*-
"""Console push message stores for memory and Redis runtime backends."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Protocol


class PushStore(Protocol):
    async def append(self, session_id: str, text: str, *, sticky: bool = False) -> None:
        ...

    async def take(self, session_id: str) -> list[dict[str, Any]]:
        ...

    async def take_all(self) -> list[dict[str, Any]]:
        ...

    async def get_recent(self, max_age_seconds: int | None = None) -> list[dict[str, Any]]:
        ...

    async def stats(self) -> dict[str, Any]:
        ...


class MemoryPushStore:
    """Bounded in-process push message store."""

    backend = "memory"

    def __init__(self, *, max_messages: int, max_age_seconds: int) -> None:
        self.max_messages = max_messages
        self.max_age_seconds = max_age_seconds
        self._list: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def append(self, session_id: str, text: str, *, sticky: bool = False) -> None:
        if not session_id or not text:
            return
        async with self._lock:
            self._list.append(
                {
                    "id": str(uuid.uuid4()),
                    "text": text,
                    "sticky": sticky,
                    "ts": time.time(),
                    "session_id": session_id,
                },
            )
            self._trim_locked()

    async def take(self, session_id: str) -> list[dict[str, Any]]:
        if not session_id:
            return []
        async with self._lock:
            self._prune_expired_locked(self.max_age_seconds)
            out = []
            remaining = []
            for msg in self._list:
                if msg.get("session_id") == session_id:
                    out.append(msg)
                else:
                    remaining.append(msg)
            self._list[:] = remaining
            return _strip_internal_fields(out)

    async def take_all(self) -> list[dict[str, Any]]:
        async with self._lock:
            self._prune_expired_locked(self.max_age_seconds)
            out = list(self._list)
            self._list.clear()
            return _strip_internal_fields(out)

    async def get_recent(self, max_age_seconds: int | None = None) -> list[dict[str, Any]]:
        max_age = self.max_age_seconds if max_age_seconds is None else max_age_seconds
        if max_age < 0:
            raise ValueError("max_age_seconds must be non-negative")

        async with self._lock:
            self._prune_expired_locked(max_age)
            return _strip_internal_fields(self._list)

    async def stats(self) -> dict[str, Any]:
        async with self._lock:
            self._prune_expired_locked(self.max_age_seconds)
            sessions = {str(m.get("session_id") or "") for m in self._list}
            return {
                "backend": self.backend,
                "pending_count": len(self._list),
                "session_count": len([s for s in sessions if s]),
                "max_messages": self.max_messages,
                "max_age_seconds": self.max_age_seconds,
            }

    def _trim_locked(self) -> None:
        if len(self._list) <= self.max_messages:
            return
        self._list.sort(key=lambda m: m["ts"])
        del self._list[: len(self._list) - self.max_messages]

    def _prune_expired_locked(self, max_age_seconds: int) -> None:
        cutoff = time.time() - max_age_seconds
        self._list[:] = [m for m in self._list if m["ts"] >= cutoff]


class RedisPushStore:
    """Redis-backed push message store shared across app processes."""

    backend = "redis"

    def __init__(
        self,
        client,
        *,
        namespace: str = "qwenpaw:push",
        max_messages: int,
        max_age_seconds: int,
    ) -> None:
        self.client = client
        self.namespace = namespace.rstrip(":")
        self.max_messages = max_messages
        self.max_age_seconds = max_age_seconds

    async def append(self, session_id: str, text: str, *, sticky: bool = False) -> None:
        if not session_id or not text:
            return
        msg = {
            "id": str(uuid.uuid4()),
            "text": text,
            "sticky": sticky,
            "ts": time.time(),
            "session_id": session_id,
        }
        msg_key = self._message_key(msg["id"])
        pipe = self.client.pipeline(transaction=True)
        pipe.set(msg_key, json.dumps(msg, ensure_ascii=False), ex=self.max_age_seconds)
        pipe.zadd(self._all_key(), {msg["id"]: msg["ts"]})
        pipe.sadd(self._session_key(session_id), msg["id"])
        pipe.expire(self._session_key(session_id), self.max_age_seconds)
        await pipe.execute()
        await self._trim_and_prune()

    async def take(self, session_id: str) -> list[dict[str, Any]]:
        if not session_id:
            return []
        await self._prune_expired(self.max_age_seconds)
        session_key = self._session_key(session_id)
        ids = [str(item) for item in await self.client.smembers(session_key)]
        if not ids:
            return []
        msgs = await self._load_messages(ids)
        pipe = self.client.pipeline(transaction=True)
        pipe.delete(session_key)
        if ids:
            pipe.zrem(self._all_key(), *ids)
            pipe.delete(*[self._message_key(msg_id) for msg_id in ids])
        await pipe.execute()
        return _strip_internal_fields(sorted(msgs, key=lambda m: m["ts"]))

    async def take_all(self) -> list[dict[str, Any]]:
        await self._prune_expired(self.max_age_seconds)
        ids = [str(item) for item in await self.client.zrange(self._all_key(), 0, -1)]
        if not ids:
            return []
        msgs = await self._load_messages(ids)
        session_ids = {str(msg.get("session_id") or "") for msg in msgs if msg.get("session_id")}
        pipe = self.client.pipeline(transaction=True)
        pipe.delete(self._all_key())
        if ids:
            pipe.delete(*[self._message_key(msg_id) for msg_id in ids])
        for session_id in session_ids:
            pipe.delete(self._session_key(session_id))
        await pipe.execute()
        return _strip_internal_fields(sorted(msgs, key=lambda m: m["ts"]))

    async def get_recent(self, max_age_seconds: int | None = None) -> list[dict[str, Any]]:
        max_age = self.max_age_seconds if max_age_seconds is None else max_age_seconds
        if max_age < 0:
            raise ValueError("max_age_seconds must be non-negative")
        await self._prune_expired(max_age)
        ids = [str(item) for item in await self.client.zrange(self._all_key(), 0, -1)]
        msgs = await self._load_messages(ids)
        return _strip_internal_fields(sorted(msgs, key=lambda m: m["ts"]))

    async def stats(self) -> dict[str, Any]:
        await self._prune_expired(self.max_age_seconds)
        ids = [str(item) for item in await self.client.zrange(self._all_key(), 0, -1)]
        msgs = await self._load_messages(ids)
        sessions = {str(msg.get("session_id") or "") for msg in msgs}
        return {
            "backend": self.backend,
            "pending_count": len(msgs),
            "session_count": len([s for s in sessions if s]),
            "max_messages": self.max_messages,
            "max_age_seconds": self.max_age_seconds,
        }

    async def _load_messages(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        values = await self.client.mget([self._message_key(msg_id) for msg_id in ids])
        msgs = []
        missing_ids = []
        for msg_id, value in zip(ids, values):
            if not value:
                missing_ids.append(msg_id)
                continue
            try:
                msg = json.loads(value)
            except (TypeError, json.JSONDecodeError):
                missing_ids.append(msg_id)
                continue
            msgs.append(msg)
        if missing_ids:
            await self.client.zrem(self._all_key(), *missing_ids)
        return msgs

    async def _trim_and_prune(self) -> None:
        await self._prune_expired(self.max_age_seconds)
        count = await self.client.zcard(self._all_key())
        overflow = int(count) - self.max_messages
        if overflow <= 0:
            return
        old_ids = [str(item) for item in await self.client.zrange(self._all_key(), 0, overflow - 1)]
        if not old_ids:
            return
        await self._delete_ids(old_ids)

    async def _prune_expired(self, max_age_seconds: int) -> None:
        cutoff = time.time() - max_age_seconds
        expired_ids = [
            str(item)
            for item in await self.client.zrangebyscore(self._all_key(), "-inf", cutoff)
        ]
        if expired_ids:
            await self._delete_ids(expired_ids)

    async def _delete_ids(self, ids: list[str]) -> None:
        msgs = await self._load_messages(ids)
        session_ids = {str(msg.get("session_id") or "") for msg in msgs if msg.get("session_id")}
        pipe = self.client.pipeline(transaction=True)
        pipe.zrem(self._all_key(), *ids)
        pipe.delete(*[self._message_key(msg_id) for msg_id in ids])
        for session_id in session_ids:
            pipe.srem(self._session_key(session_id), *ids)
        await pipe.execute()

    def _all_key(self) -> str:
        return f"{self.namespace}:all"

    def _message_key(self, msg_id: str) -> str:
        return f"{self.namespace}:msg:{msg_id}"

    def _session_key(self, session_id: str) -> str:
        return f"{self.namespace}:session:{session_id}"


def _strip_internal_fields(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(m["id"]),
            "text": str(m["text"]),
            "sticky": bool(m.get("sticky", False)),
        }
        for m in msgs
    ]
