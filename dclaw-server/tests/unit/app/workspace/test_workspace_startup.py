import asyncio
import threading
from types import SimpleNamespace

import pytest

from qwenpaw.app.workspace.workspace import Workspace


@pytest.mark.asyncio
async def test_skill_pool_initialization_does_not_block_event_loop(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def initialize_pool():
        started.set()
        assert release.wait(timeout=2)

    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.ensure_skill_pool_initialized",
        initialize_pool,
    )
    monkeypatch.setattr(
        "qwenpaw.app.workspace.workspace.load_agent_config",
        lambda agent_id: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "qwenpaw.app.workspace.capabilities_injector.inject_user_capabilities",
        lambda user_id, config: None,
    )

    workspace = Workspace.__new__(Workspace)
    workspace._started = False
    workspace.agent_id = "startup-test"
    workspace.workspace_dir = SimpleNamespace(name="startup-test")
    workspace._service_manager = SimpleNamespace(start_all=lambda: None)
    workspace._migrate_legacy_weixin_data = lambda: None
    workspace._migrate_or_init_workspace_mds = lambda: None

    async def start_services():
        return None

    workspace._service_manager.start_all = start_services
    task = asyncio.create_task(workspace.start())
    assert await asyncio.to_thread(started.wait, 1)

    # This callback can run only if pool initialization is off the event loop.
    await asyncio.wait_for(asyncio.sleep(0), timeout=0.1)
    release.set()
    await task
    assert workspace._started
