# -*- coding: utf-8 -*-
"""In-process task concurrency limits for single-container SaaS stability."""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Optional

from .storage.settings import get_storage_settings


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return max(value, 1)


@dataclass
class TaskPermit:
    """A held task slot."""

    limiter: Any
    agent_id: str
    user_id: str
    released: bool = False

    async def release(self) -> None:
        if self.released:
            return
        self.released = True
        await self.limiter.release(self.agent_id, self.user_id)


class TaskConcurrencyLimiter:
    """Simple in-memory limiter for one Python process."""

    def __init__(
        self,
        *,
        max_global: int,
        max_per_agent: int,
        max_per_user: int,
    ) -> None:
        self.max_global = max_global
        self.max_per_agent = max_per_agent
        self.max_per_user = max_per_user
        self._lock = asyncio.Lock()
        self._global = 0
        self._by_agent: dict[str, int] = {}
        self._by_user: dict[str, int] = {}
        self._rejected_acquire_count = 0

    @classmethod
    def from_env(cls) -> "TaskConcurrencyLimiter":
        return cls(
            max_global=_int_env("QWENPAW_MAX_RUNNING_TASKS", 32),
            max_per_agent=_int_env("QWENPAW_MAX_RUNNING_TASKS_PER_AGENT", 12),
            max_per_user=_int_env("QWENPAW_MAX_RUNNING_TASKS_PER_USER", 6),
        )

    async def try_acquire(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Optional[TaskPermit]:
        agent_key = agent_id or "default"
        user_key = user_id or "default"
        async with self._lock:
            if self._global >= self.max_global:
                self._rejected_acquire_count += 1
                return None
            if self._by_agent.get(agent_key, 0) >= self.max_per_agent:
                self._rejected_acquire_count += 1
                return None
            if self._by_user.get(user_key, 0) >= self.max_per_user:
                self._rejected_acquire_count += 1
                return None

            self._global += 1
            self._by_agent[agent_key] = self._by_agent.get(agent_key, 0) + 1
            self._by_user[user_key] = self._by_user.get(user_key, 0) + 1
            return TaskPermit(self, agent_key, user_key)

    async def release(self, agent_id: str, user_id: str) -> None:
        agent_key = agent_id or "default"
        user_key = user_id or "default"
        async with self._lock:
            self._global = max(0, self._global - 1)
            self._decrement(self._by_agent, agent_key)
            self._decrement(self._by_user, user_key)

    @staticmethod
    def _decrement(bucket: dict[str, int], key: str) -> None:
        next_value = bucket.get(key, 0) - 1
        if next_value > 0:
            bucket[key] = next_value
        else:
            bucket.pop(key, None)

    async def snapshot(self) -> dict:
        async with self._lock:
            return {
                "running_global": self._global,
                "running_by_agent": dict(self._by_agent),
                "running_by_user": dict(self._by_user),
                "max_global": self.max_global,
                "max_per_agent": self.max_per_agent,
                "max_per_user": self.max_per_user,
                "rejected_acquire_count": self._rejected_acquire_count,
                "expired_permit_count": 0,
            }


class RedisTaskPermit:
    """A Redis-backed held task slot with periodic TTL refresh."""

    def __init__(
        self,
        limiter: "RedisTaskConcurrencyLimiter",
        *,
        permit_id: str,
        agent_id: str,
        user_id: str,
    ) -> None:
        self.limiter = limiter
        self.permit_id = permit_id
        self.agent_id = agent_id
        self.user_id = user_id
        self.released = False
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def release(self) -> None:
        if self.released:
            return
        self.released = True
        self._refresh_task.cancel()
        with suppress(asyncio.CancelledError):
            await self._refresh_task
        await self.limiter.release(
            self.agent_id,
            self.user_id,
            permit_id=self.permit_id,
        )

    async def _refresh_loop(self) -> None:
        interval = max(0.5, self.limiter.permit_ttl_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            await self.limiter.refresh(
                self.agent_id,
                self.user_id,
                permit_id=self.permit_id,
            )


class RedisTaskConcurrencyLimiter:
    """Redis-backed task limiter shared across app processes."""

    backend = "redis"

    def __init__(
        self,
        client,
        *,
        namespace: str = "qwenpaw:task_limit",
        max_global: int,
        max_per_agent: int,
        max_per_user: int,
        permit_ttl_seconds: int,
    ) -> None:
        self.client = client
        self.namespace = namespace.rstrip(":")
        self.max_global = max_global
        self.max_per_agent = max_per_agent
        self.max_per_user = max_per_user
        self.permit_ttl_seconds = max(int(permit_ttl_seconds), 1)

    @classmethod
    def from_env(cls, client) -> "RedisTaskConcurrencyLimiter":
        return cls(
            client,
            max_global=_int_env("QWENPAW_MAX_RUNNING_TASKS", 32),
            max_per_agent=_int_env("QWENPAW_MAX_RUNNING_TASKS_PER_AGENT", 12),
            max_per_user=_int_env("QWENPAW_MAX_RUNNING_TASKS_PER_USER", 6),
            permit_ttl_seconds=_int_env("QWENPAW_TASK_PERMIT_TTL_SECONDS", 14400),
        )

    async def try_acquire(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Optional[RedisTaskPermit]:
        agent_key = agent_id or "default"
        user_key = user_id or "default"
        permit_id = str(uuid.uuid4())

        for _ in range(10):
            await self._prune_sets(agent_key, user_key)
            async with self.client.pipeline() as pipe:
                try:
                    await pipe.watch(
                        self._global_key(),
                        self._agent_key(agent_key),
                        self._user_key(user_key),
                    )
                    global_count = int(await pipe.scard(self._global_key()))
                    agent_count = int(await pipe.scard(self._agent_key(agent_key)))
                    user_count = int(await pipe.scard(self._user_key(user_key)))
                    if global_count >= self.max_global:
                        await pipe.unwatch()
                        await self._increment_rejected()
                        return None
                    if agent_count >= self.max_per_agent:
                        await pipe.unwatch()
                        await self._increment_rejected()
                        return None
                    if user_count >= self.max_per_user:
                        await pipe.unwatch()
                        await self._increment_rejected()
                        return None

                    payload = json.dumps(
                        {"agent_id": agent_key, "user_id": user_key},
                        ensure_ascii=False,
                    )
                    pipe.multi()
                    pipe.set(
                        self._permit_key(permit_id),
                        payload,
                        ex=self.permit_ttl_seconds,
                        nx=True,
                    )
                    pipe.sadd(self._global_key(), permit_id)
                    pipe.sadd(self._agent_key(agent_key), permit_id)
                    pipe.sadd(self._user_key(user_key), permit_id)
                    pipe.sadd(self._agents_key(), agent_key)
                    pipe.sadd(self._users_key(), user_key)
                    for key in (
                        self._global_key(),
                        self._agent_key(agent_key),
                        self._user_key(user_key),
                        self._agents_key(),
                        self._users_key(),
                    ):
                        pipe.expire(key, self.permit_ttl_seconds * 2)
                    result = await pipe.execute()
                    if result and result[0]:
                        return RedisTaskPermit(
                            self,
                            permit_id=permit_id,
                            agent_id=agent_key,
                            user_id=user_key,
                        )
                except _watch_error_type():
                    continue
        return None

    async def release(
        self,
        agent_id: str,
        user_id: str,
        *,
        permit_id: str,
    ) -> None:
        if not permit_id:
            return
        agent_key = agent_id or "default"
        user_key = user_id or "default"
        pipe = self.client.pipeline(transaction=True)
        pipe.delete(self._permit_key(permit_id))
        pipe.srem(self._global_key(), permit_id)
        pipe.srem(self._agent_key(agent_key), permit_id)
        pipe.srem(self._user_key(user_key), permit_id)
        await pipe.execute()

    async def refresh(
        self,
        agent_id: str,
        user_id: str,
        *,
        permit_id: str,
    ) -> None:
        if not permit_id:
            return
        if not await self.client.exists(self._permit_key(permit_id)):
            return
        agent_key = agent_id or "default"
        user_key = user_id or "default"
        pipe = self.client.pipeline(transaction=True)
        pipe.expire(self._permit_key(permit_id), self.permit_ttl_seconds)
        for key in (
            self._global_key(),
            self._agent_key(agent_key),
            self._user_key(user_key),
            self._agents_key(),
            self._users_key(),
        ):
            pipe.expire(key, self.permit_ttl_seconds * 2)
        await pipe.execute()

    async def snapshot(self) -> dict[str, Any]:
        await self._prune_indexed_sets()
        by_agent: dict[str, int] = {}
        for agent_id in await self._members(self._agents_key()):
            count = await self._prune_set(self._agent_key(agent_id))
            if count:
                by_agent[agent_id] = count
            else:
                await self.client.srem(self._agents_key(), agent_id)

        by_user: dict[str, int] = {}
        for user_id in await self._members(self._users_key()):
            count = await self._prune_set(self._user_key(user_id))
            if count:
                by_user[user_id] = count
            else:
                await self.client.srem(self._users_key(), user_id)

        running_global = await self._prune_set(self._global_key())
        return {
            "backend": self.backend,
            "running_global": running_global,
            "running_by_agent": by_agent,
            "running_by_user": by_user,
            "max_global": self.max_global,
            "max_per_agent": self.max_per_agent,
            "max_per_user": self.max_per_user,
            "permit_ttl_seconds": self.permit_ttl_seconds,
            "rejected_acquire_count": await self._counter_value(
                self._rejected_key(),
            ),
            "expired_permit_count": await self._counter_value(
                self._expired_key(),
            ),
        }

    async def _prune_sets(self, agent_id: str, user_id: str) -> None:
        await self._prune_set(self._global_key())
        await self._prune_set(self._agent_key(agent_id))
        await self._prune_set(self._user_key(user_id))

    async def _prune_indexed_sets(self) -> None:
        await self._prune_set(self._global_key())

    async def _prune_set(self, key: str) -> int:
        permit_ids = await self._members(key)
        if not permit_ids:
            return 0
        missing = []
        for permit_id in permit_ids:
            if not await self.client.exists(self._permit_key(permit_id)):
                missing.append(permit_id)
        if missing:
            await self.client.srem(key, *missing)
            if key == self._global_key():
                await self.client.incrby(self._expired_key(), len(missing))
        return int(await self.client.scard(key))

    async def _increment_rejected(self) -> None:
        await self.client.incr(self._rejected_key())

    async def _counter_value(self, key: str) -> int:
        value = await self.client.get(key)
        if value is None:
            return 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    async def _members(self, key: str) -> list[str]:
        return [
            item.decode("utf-8") if isinstance(item, bytes) else str(item)
            for item in await self.client.smembers(key)
        ]

    def _global_key(self) -> str:
        return f"{self.namespace}:global"

    def _agent_key(self, agent_id: str) -> str:
        return f"{self.namespace}:agent:{agent_id}"

    def _user_key(self, user_id: str) -> str:
        return f"{self.namespace}:user:{user_id}"

    def _permit_key(self, permit_id: str) -> str:
        return f"{self.namespace}:permit:{permit_id}"

    def _agents_key(self) -> str:
        return f"{self.namespace}:agents"

    def _users_key(self) -> str:
        return f"{self.namespace}:users"

    def _rejected_key(self) -> str:
        return f"{self.namespace}:metrics:rejected"

    def _expired_key(self) -> str:
        return f"{self.namespace}:metrics:expired"


def _make_redis_client(redis_url: str):
    from redis import asyncio as redis_asyncio

    return redis_asyncio.from_url(redis_url, decode_responses=True)


def _watch_error_type():
    from redis.exceptions import WatchError

    return WatchError


def create_task_limiter_from_env():
    settings = get_storage_settings()
    if settings.runtime_backend == "redis":
        if not settings.redis_url:
            raise RuntimeError(
                "QWENPAW_REDIS_URL is required for Redis task limiter",
            )
        return RedisTaskConcurrencyLimiter.from_env(
            _make_redis_client(settings.redis_url),
        )
    return TaskConcurrencyLimiter.from_env()


def get_task_limiter(app):
    limiter = getattr(app.state, "task_limiter", None)
    if limiter is None:
        limiter = create_task_limiter_from_env()
        app.state.task_limiter = limiter
    return limiter
