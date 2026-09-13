from __future__ import annotations

import asyncio

import pytest

from qwenpaw.app.multi_agent_manager import MultiAgentManager


@pytest.mark.asyncio
async def test_reload_agent_serializes_same_agent(monkeypatch):
    manager = MultiAgentManager()
    active = 0
    max_active = 0

    async def reload_serialized(agent_id):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        return True

    monkeypatch.setattr(manager, "_reload_agent_serialized", reload_serialized)

    results = await asyncio.gather(
        manager.reload_agent("luyu"),
        manager.reload_agent("luyu"),
    )

    assert results == [True, True]
    assert max_active == 1


@pytest.mark.asyncio
async def test_reload_agent_keeps_different_agents_independent(monkeypatch):
    manager = MultiAgentManager()
    started = set()
    both_started = asyncio.Event()

    async def reload_serialized(agent_id):
        started.add(agent_id)
        if len(started) == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=1)
        return True

    monkeypatch.setattr(manager, "_reload_agent_serialized", reload_serialized)

    assert await asyncio.gather(
        manager.reload_agent("luyu"),
        manager.reload_agent("writer"),
    ) == [True, True]
