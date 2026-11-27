# -*- coding: utf-8 -*-
"""Approval metadata stores for memory and Redis runtime backends.

Only serializable approval metadata lives here. The live asyncio Future that
unblocks a tool call stays in ``ApprovalService`` until a later worker/pubsub
phase can safely route decisions across processes.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass
class ApprovalRecord:
    """Serializable metadata for one pending approval request."""

    request_id: str
    session_id: str
    root_session_id: str
    owner_agent_id: str
    user_id: str
    channel: str
    agent_id: str
    tool_name: str
    created_at: float
    timeout_seconds: float
    status: str = "pending"
    resolved_at: float | None = None
    result_summary: str = ""
    findings_count: int = 0
    severity: str = "medium"
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_pending(cls, pending: Any) -> "ApprovalRecord":
        """Create a serializable record from a PendingApproval-like object."""
        return cls(
            request_id=str(pending.request_id),
            session_id=str(pending.session_id),
            root_session_id=str(pending.root_session_id),
            owner_agent_id=str(pending.owner_agent_id),
            user_id=str(pending.user_id),
            channel=str(pending.channel),
            agent_id=str(pending.agent_id),
            tool_name=str(pending.tool_name),
            created_at=float(pending.created_at),
            timeout_seconds=float(pending.timeout_seconds),
            status=str(getattr(pending, "status", "pending") or "pending"),
            resolved_at=getattr(pending, "resolved_at", None),
            result_summary=str(getattr(pending, "result_summary", "") or ""),
            findings_count=int(getattr(pending, "findings_count", 0) or 0),
            severity=str(getattr(pending, "severity", "medium") or "medium"),
            extra=dict(getattr(pending, "extra", {}) or {}),
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ApprovalRecord":
        return cls(
            request_id=str(raw["request_id"]),
            session_id=str(raw["session_id"]),
            root_session_id=str(raw["root_session_id"]),
            owner_agent_id=str(raw.get("owner_agent_id") or ""),
            user_id=str(raw.get("user_id") or ""),
            channel=str(raw.get("channel") or "console"),
            agent_id=str(raw["agent_id"]),
            tool_name=str(raw["tool_name"]),
            created_at=float(raw["created_at"]),
            timeout_seconds=float(raw.get("timeout_seconds") or 300.0),
            status=str(raw.get("status") or "pending"),
            resolved_at=raw.get("resolved_at"),
            result_summary=str(raw.get("result_summary") or ""),
            findings_count=int(raw.get("findings_count") or 0),
            severity=str(raw.get("severity") or "medium"),
            extra=dict(raw.get("extra") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ApprovalMetadataStore(Protocol):
    async def put(self, record: ApprovalRecord) -> None:
        ...

    async def get(self, request_id: str) -> ApprovalRecord | None:
        ...

    async def pop(self, request_id: str) -> ApprovalRecord | None:
        ...

    async def delete(self, request_id: str) -> None:
        ...

    async def list_all_pending(self) -> list[ApprovalRecord]:
        ...

    async def list_pending_by_session(self, session_id: str) -> list[ApprovalRecord]:
        ...

    async def list_pending_by_root_session(self, root_session_id: str) -> list[ApprovalRecord]:
        ...

    async def list_pending_by_agent(self, agent_id: str) -> list[ApprovalRecord]:
        ...

    async def stats(self) -> dict[str, Any]:
        ...

    async def publish_resolution(self, request_id: str, decision: str) -> None:
        ...

    async def wait_for_resolution(
        self,
        request_id: str,
        *,
        timeout_seconds: float,
    ) -> str | None:
        ...


class MemoryApprovalStore:
    """Bounded in-process approval metadata store."""

    backend = "memory"
    supports_resolution_pubsub = False

    def __init__(self, *, max_records: int, max_age_seconds: int) -> None:
        self.max_records = max_records
        self.max_age_seconds = max_age_seconds
        self._records: dict[str, ApprovalRecord] = {}
        self._lock = asyncio.Lock()

    async def put(self, record: ApprovalRecord) -> None:
        if not record.request_id:
            return
        async with self._lock:
            self._records[record.request_id] = record
            self._trim_locked()

    async def get(self, request_id: str) -> ApprovalRecord | None:
        if not request_id:
            return None
        async with self._lock:
            self._prune_expired_locked()
            return self._records.get(request_id)

    async def pop(self, request_id: str) -> ApprovalRecord | None:
        if not request_id:
            return None
        async with self._lock:
            self._prune_expired_locked()
            return self._records.pop(request_id, None)

    async def delete(self, request_id: str) -> None:
        await self.pop(request_id)

    async def list_all_pending(self) -> list[ApprovalRecord]:
        async with self._lock:
            self._prune_expired_locked()
            return _sort_pending(self._records.values())

    async def list_pending_by_session(self, session_id: str) -> list[ApprovalRecord]:
        return [
            r
            for r in await self.list_all_pending()
            if r.session_id == session_id
        ]

    async def list_pending_by_root_session(self, root_session_id: str) -> list[ApprovalRecord]:
        return [
            r
            for r in await self.list_all_pending()
            if r.root_session_id == root_session_id
        ]

    async def list_pending_by_agent(self, agent_id: str) -> list[ApprovalRecord]:
        return [
            r
            for r in await self.list_all_pending()
            if r.agent_id == agent_id
        ]

    async def stats(self) -> dict[str, Any]:
        records = await self.list_all_pending()
        return _stats(
            backend=self.backend,
            records=records,
            max_records=self.max_records,
            max_age_seconds=self.max_age_seconds,
        )

    async def publish_resolution(self, request_id: str, decision: str) -> None:
        _ = request_id, decision

    async def wait_for_resolution(
        self,
        request_id: str,
        *,
        timeout_seconds: float,
    ) -> str | None:
        _ = request_id, timeout_seconds
        return None

    def _trim_locked(self) -> None:
        self._prune_expired_locked()
        overflow = len(self._records) - self.max_records
        if overflow <= 0:
            return
        ordered = sorted(self._records.values(), key=lambda r: r.created_at)
        for record in ordered[:overflow]:
            self._records.pop(record.request_id, None)

    def _prune_expired_locked(self) -> None:
        cutoff = time.time() - self.max_age_seconds
        expired = [
            request_id
            for request_id, record in self._records.items()
            if record.created_at < cutoff
        ]
        for request_id in expired:
            self._records.pop(request_id, None)


class RedisApprovalStore:
    """Redis-backed approval metadata store shared across app processes."""

    backend = "redis"
    supports_resolution_pubsub = True

    def __init__(
        self,
        client,
        *,
        namespace: str = "qwenpaw:approval",
        max_records: int,
        max_age_seconds: int,
    ) -> None:
        self.client = client
        self.namespace = namespace.rstrip(":")
        self.max_records = max_records
        self.max_age_seconds = max_age_seconds

    async def put(self, record: ApprovalRecord) -> None:
        if not record.request_id:
            return
        payload = json.dumps(record.to_dict(), ensure_ascii=False, default=str)
        ttl = max(1, int(max(self.max_age_seconds, record.timeout_seconds + 300)))
        pipe = self.client.pipeline(transaction=True)
        pipe.set(self._record_key(record.request_id), payload, ex=ttl)
        for key in self._index_keys(record):
            pipe.zadd(key, {record.request_id: record.created_at})
            pipe.expire(key, ttl)
        await pipe.execute()
        await self._trim_and_prune()

    async def get(self, request_id: str) -> ApprovalRecord | None:
        if not request_id:
            return None
        value = await self.client.get(self._record_key(request_id))
        if not value:
            await self.client.zrem(self._all_key(), request_id)
            return None
        try:
            return ApprovalRecord.from_dict(json.loads(value))
        except (TypeError, json.JSONDecodeError, KeyError, ValueError):
            pipe = self.client.pipeline(transaction=True)
            pipe.delete(self._record_key(request_id))
            pipe.zrem(self._all_key(), request_id)
            await pipe.execute()
            return None

    async def pop(self, request_id: str) -> ApprovalRecord | None:
        record = await self.get(request_id)
        await self.delete(request_id)
        return record

    async def delete(self, request_id: str) -> None:
        if not request_id:
            return
        record = await self.get(request_id)
        pipe = self.client.pipeline(transaction=True)
        pipe.delete(self._record_key(request_id))
        pipe.zrem(self._all_key(), request_id)
        if record is not None:
            for key in self._secondary_index_keys(record):
                pipe.zrem(key, request_id)
        await pipe.execute()

    async def list_all_pending(self) -> list[ApprovalRecord]:
        await self._prune_expired()
        return await self._list_from_index(self._all_key())

    async def list_pending_by_session(self, session_id: str) -> list[ApprovalRecord]:
        if not session_id:
            return []
        await self._prune_expired()
        return await self._list_from_index(self._session_key(session_id))

    async def list_pending_by_root_session(self, root_session_id: str) -> list[ApprovalRecord]:
        if not root_session_id:
            return []
        await self._prune_expired()
        return await self._list_from_index(self._root_key(root_session_id))

    async def list_pending_by_agent(self, agent_id: str) -> list[ApprovalRecord]:
        if not agent_id:
            return []
        await self._prune_expired()
        return await self._list_from_index(self._agent_key(agent_id))

    async def stats(self) -> dict[str, Any]:
        records = await self.list_all_pending()
        return _stats(
            backend=self.backend,
            records=records,
            max_records=self.max_records,
            max_age_seconds=self.max_age_seconds,
        )

    async def publish_resolution(self, request_id: str, decision: str) -> None:
        if not request_id or not decision:
            return
        ttl = max(1, int(self.max_age_seconds))
        payload = str(decision)
        pipe = self.client.pipeline(transaction=True)
        pipe.set(self._resolution_key(request_id), payload, ex=ttl)
        pipe.publish(self._resolution_channel(request_id), payload)
        await pipe.execute()

    async def wait_for_resolution(
        self,
        request_id: str,
        *,
        timeout_seconds: float,
    ) -> str | None:
        if not request_id or timeout_seconds <= 0:
            return await self._get_resolution(request_id)

        existing = await self._get_resolution(request_id)
        if existing:
            return existing

        pubsub = self.client.pubsub()
        deadline = time.monotonic() + timeout_seconds
        try:
            await pubsub.subscribe(self._resolution_channel(request_id))
            existing = await self._get_resolution(request_id)
            if existing:
                return existing

            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return await self._get_resolution(request_id)
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=min(0.2, remaining),
                )
                if message:
                    data = message.get("data")
                    if data is None:
                        continue
                    return data.decode("utf-8") if isinstance(data, bytes) else str(data)
                existing = await self._get_resolution(request_id)
                if existing:
                    return existing
        finally:
            try:
                await pubsub.unsubscribe(self._resolution_channel(request_id))
            finally:
                await pubsub.aclose()

    async def _list_from_index(self, key: str) -> list[ApprovalRecord]:
        ids = [str(item) for item in await self.client.zrange(key, 0, -1)]
        records, missing_ids = await self._load_records(ids)
        if missing_ids:
            await self.client.zrem(key, *missing_ids)
        return _sort_pending(records)

    async def _get_resolution(self, request_id: str) -> str | None:
        value = await self.client.get(self._resolution_key(request_id))
        if not value:
            return None
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)

    async def _load_records(
        self,
        request_ids: list[str],
    ) -> tuple[list[ApprovalRecord], list[str]]:
        if not request_ids:
            return [], []
        values = await self.client.mget(
            [self._record_key(request_id) for request_id in request_ids],
        )
        records = []
        missing_ids = []
        for request_id, value in zip(request_ids, values):
            if not value:
                missing_ids.append(request_id)
                continue
            try:
                records.append(ApprovalRecord.from_dict(json.loads(value)))
            except (TypeError, json.JSONDecodeError, KeyError, ValueError):
                missing_ids.append(request_id)
        if missing_ids:
            await self.client.zrem(self._all_key(), *missing_ids)
        return records, missing_ids

    async def _trim_and_prune(self) -> None:
        await self._prune_expired()
        count = await self.client.zcard(self._all_key())
        overflow = int(count) - self.max_records
        if overflow <= 0:
            return
        old_ids = [
            str(item)
            for item in await self.client.zrange(self._all_key(), 0, overflow - 1)
        ]
        for request_id in old_ids:
            await self.delete(request_id)

    async def _prune_expired(self) -> None:
        cutoff = time.time() - self.max_age_seconds
        expired_ids = [
            str(item)
            for item in await self.client.zrangebyscore(self._all_key(), "-inf", cutoff)
        ]
        for request_id in expired_ids:
            await self.delete(request_id)

    def _index_keys(self, record: ApprovalRecord) -> list[str]:
        return [self._all_key(), *self._secondary_index_keys(record)]

    def _secondary_index_keys(self, record: ApprovalRecord) -> list[str]:
        return [
            self._session_key(record.session_id),
            self._root_key(record.root_session_id),
            self._agent_key(record.agent_id),
        ]

    def _all_key(self) -> str:
        return f"{self.namespace}:pending"

    def _record_key(self, request_id: str) -> str:
        return f"{self.namespace}:record:{request_id}"

    def _resolution_key(self, request_id: str) -> str:
        return f"{self.namespace}:resolved:{request_id}"

    def _resolution_channel(self, request_id: str) -> str:
        return f"{self.namespace}:resolved:{request_id}:channel"

    def _session_key(self, session_id: str) -> str:
        return f"{self.namespace}:session:{session_id}"

    def _root_key(self, root_session_id: str) -> str:
        return f"{self.namespace}:root:{root_session_id}"

    def _agent_key(self, agent_id: str) -> str:
        return f"{self.namespace}:agent:{agent_id}"


def _sort_pending(records: Any) -> list[ApprovalRecord]:
    return sorted(
        [r for r in records if r.status == "pending"],
        key=lambda r: r.created_at,
    )


def _stats(
    *,
    backend: str,
    records: list[ApprovalRecord],
    max_records: int,
    max_age_seconds: int,
) -> dict[str, Any]:
    return {
        "backend": backend,
        "pending_count": len(records),
        "session_count": len({r.session_id for r in records if r.session_id}),
        "root_session_count": len(
            {r.root_session_id for r in records if r.root_session_id},
        ),
        "agent_count": len({r.agent_id for r in records if r.agent_id}),
        "max_records": max_records,
        "max_age_seconds": max_age_seconds,
    }
