# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app import console_push_store


@pytest.fixture(autouse=True)
def reset_push_store_cache():
    console_push_store.reset_store_for_tests()
    yield
    console_push_store.reset_store_for_tests()


@pytest.mark.asyncio
async def test_console_push_store_uses_memory_backend_by_default():
    await console_push_store.append("session-a", "hello")

    assert (await console_push_store.stats())["backend"] == "memory"
    assert [msg["text"] for msg in await console_push_store.take("session-a")] == ["hello"]


@pytest.mark.asyncio
async def test_console_push_store_can_use_redis_backend(monkeypatch):
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(
        console_push_store,
        "get_storage_settings",
        lambda: SimpleNamespace(
            runtime_backend="redis",
            redis_url="redis://example.invalid/0",
        ),
    )
    monkeypatch.setattr(
        console_push_store,
        "_make_redis_client",
        lambda _url: client,
    )

    await console_push_store.append("session-a", "hello")

    assert (await console_push_store.stats())["backend"] == "redis"
    assert [msg["text"] for msg in await console_push_store.take("session-a")] == ["hello"]
