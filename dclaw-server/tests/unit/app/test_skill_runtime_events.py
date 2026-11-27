# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.app.routers import skills
from qwenpaw.app.runtime.event_bus import MemoryRuntimeEventBus


@pytest.mark.asyncio
async def test_hub_install_status_publishes_runtime_event(monkeypatch):
    bus = MemoryRuntimeEventBus(max_events=20, max_age_seconds=60)
    monkeypatch.setattr(
        skills,
        "get_runtime_event_bus",
        lambda: bus,
        raising=False,
    )

    async with skills._hub_install_lock:
        skills._hub_install_tasks.clear()
        skills._hub_install_tasks["task-1"] = skills.HubInstallTask(
            task_id="task-1",
            bundle_url="https://example.test/skill.zip",
        )

    await skills._hub_task_set_status(
        "task-1",
        skills.HubInstallTaskStatus.COMPLETED,
        result={"name": "demo_skill", "installed": True},
    )

    events = await bus.replay(session_id=None, since_id=None)

    assert len(events) == 1
    event = events[0]
    assert event.type == "skill.install.updated"
    assert event.scope == "skill"
    assert event.job_id == "task-1"
    assert event.status == "completed"
    assert event.payload["task_id"] == "task-1"
    assert event.payload["result"]["name"] == "demo_skill"

