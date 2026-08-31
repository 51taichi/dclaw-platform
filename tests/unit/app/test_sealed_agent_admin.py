from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import sealed_agents as router_module
from qwenpaw.app.sealed_agents.models import (
    RuntimeValidationRecord,
    SealedAgentRecord,
    SealedReleaseRecord,
)
from qwenpaw.config.config import Config


def _request(role="admin"):
    return SimpleNamespace(state=SimpleNamespace(role=role, user_id="1"))


def _record():
    release = SealedReleaseRecord(
        release_id="rel-1",
        version="1.0.0",
        content_digest="sha256:" + "a" * 64,
        signer_id="publisher",
        state="active",
    )
    return SealedAgentRecord(
        agent_id="luyu",
        name="陆羽",
        description="茶文化专家",
        active_release_id="rel-1",
        releases=[release],
    )


def test_admin_list_returns_operational_metadata_without_asset_paths(monkeypatch):
    class Service:
        def list_agents(self):
            return [_record()]

    monkeypatch.setattr(router_module, "get_sealed_agent_service", lambda: Service())

    response = router_module.list_sealed_agents(_request())

    assert response[0]["agent_id"] == "luyu"
    assert response[0]["version"] == "1.0.0"
    assert response[0]["runtime"] == {
        "adapter": "standard",
        "contract_version": "1",
    }
    serialized = str(response)
    assert "workspace" not in serialized
    assert "AGENTS.md" not in serialized
    assert "path" not in serialized


def test_non_admin_cannot_use_release_routes():
    with pytest.raises(HTTPException) as exc_info:
        router_module.list_sealed_agents(_request(role="user"))

    assert exc_info.value.status_code == 403


def test_router_has_no_package_or_content_download_route():
    routes = [(route.path, frozenset(route.methods or set())) for route in router_module.router.routes]

    assert any(path == "/sealed-agents/releases" and "POST" in methods for path, methods in routes)
    assert all(
        not ("GET" in methods and any(word in path for word in ("download", "content", "files", "package")))
        for path, methods in routes
    )


@pytest.mark.asyncio
async def test_activation_registers_private_runtime_only_after_preload_succeeds(
    monkeypatch,
    tmp_path,
):
    record = _record()
    release_root = tmp_path / "releases/luyu/rel-1"
    (release_root / "agent").mkdir(parents=True)
    (release_root / "agent/agent.json").write_text(
        '{"id":"luyu","name":"陆羽"}',
    )

    class Service:
        async def validate_release_runtime(self, agent_id, release_id):
            return RuntimeValidationRecord(
                status="valid",
                adapter="standard",
                contract_version="1",
            )

        def release_root(self, agent_id, release_id):
            return release_root

        def activate(self, agent_id, release_id):
            return record

    class Manager:
        async def preload_agent(self, agent_id):
            assert agent_id == "luyu"
            return True

        def is_agent_loaded(self, agent_id):
            return False

    config = Config()
    saved = []
    monkeypatch.setattr(router_module, "get_sealed_agent_service", lambda: Service())
    monkeypatch.setattr(router_module, "load_config", lambda: config)
    monkeypatch.setattr(router_module, "save_config", lambda value: saved.append(value))
    request = _request()
    request.app = SimpleNamespace(
        state=SimpleNamespace(multi_agent_manager=Manager()),
    )

    response = await router_module.activate_sealed_agent_release(
        "luyu",
        "rel-1",
        request,
    )

    assert response["agent_id"] == "luyu"
    assert config.agents.profiles["luyu"].workspace_dir == str(release_root / "agent")
    assert saved


@pytest.mark.asyncio
async def test_disable_stops_loaded_runtime_and_config(monkeypatch):
    record = _record().model_copy(update={"enabled": False})

    class Service:
        def disable(self, agent_id):
            return record

    stopped = []

    class Manager:
        def is_agent_loaded(self, agent_id):
            return True

        async def stop_agent(self, agent_id):
            stopped.append(agent_id)

    config = Config()
    from qwenpaw.config.config import AgentProfileRef

    config.agents.profiles["luyu"] = AgentProfileRef(
        id="luyu", workspace_dir="/private/release", enabled=True
    )
    monkeypatch.setattr(router_module, "get_sealed_agent_service", lambda: Service())
    monkeypatch.setattr(router_module, "load_config", lambda: config)
    monkeypatch.setattr(router_module, "save_config", lambda _value: None)
    request = _request()
    request.app = SimpleNamespace(state=SimpleNamespace(multi_agent_manager=Manager()))

    response = await router_module.disable_sealed_agent("luyu", request)

    assert response["enabled"] is False
    assert config.agents.profiles["luyu"].enabled is False
    assert stopped == ["luyu"]
