# -*- coding: utf-8 -*-
"""Tests for persisted agent ordering."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    Config,
)
from qwenpaw.app.routers import agents as agents_router
from qwenpaw.app.sealed_agents.models import SealedAgentRecord


@pytest.fixture(autouse=True)
def _no_open_api_publications(monkeypatch):
    class Repository:
        @staticmethod
        def list_publications(enabled_only=False):
            assert enabled_only is True
            return []

    monkeypatch.setattr(
        agents_router,
        "get_open_api_repository",
        lambda: Repository(),
    )


def _build_config(
    profile_ids: list[str],
    agent_order: list[str] | None = None,
) -> Config:
    """Build a minimal config with agent profiles in the given order."""
    config = Config()
    config.agents.profiles = {
        agent_id: AgentProfileRef(
            id=agent_id,
            workspace_dir=f"/tmp/{agent_id}",
        )
        for agent_id in profile_ids
    }
    config.agents.agent_order = agent_order or []
    return config


def _agent_config(agent_id: str) -> AgentProfileConfig:
    return AgentProfileConfig(
        id=agent_id,
        name=agent_id.upper(),
        description=f"{agent_id} description",
        workspace_dir=f"/tmp/{agent_id}",
    )


@pytest.mark.asyncio
async def test_list_agents_uses_persisted_order(monkeypatch):
    """List response should follow stored agent order."""
    config = _build_config(
        ["beta", "default", "alpha"],
        agent_order=["default", "alpha", "beta"],
    )

    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(
        agents_router,
        "load_agent_config",
        _agent_config,
    )

    response = await agents_router.list_agents()

    assert [agent.id for agent in response.agents] == [
        "default",
        "alpha",
        "beta",
    ]


@pytest.mark.asyncio
async def test_list_agents_appends_missing_ids(monkeypatch):
    """Old configs without complete order should still return all agents."""
    config = _build_config(
        ["beta", "default", "alpha"],
        agent_order=["default"],
    )

    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(
        agents_router,
        "load_agent_config",
        _agent_config,
    )

    response = await agents_router.list_agents()

    assert [agent.id for agent in response.agents] == [
        "default",
        "beta",
        "alpha",
    ]


@pytest.mark.asyncio
async def test_list_agents_marks_and_can_exclude_open_api_agents(monkeypatch):
    config = _build_config(
        ["default", "api_agent", "disabled_publication_agent"],
        agent_order=["default", "api_agent", "disabled_publication_agent"],
    )

    class Repository:
        @staticmethod
        def list_publications(enabled_only=False):
            assert enabled_only is True
            return [
                {
                    "target_type": "agent",
                    "target_id": "api_agent",
                    "status": "enabled",
                },
                {
                    "target_type": "expert_team",
                    "target_id": "team-1",
                    "status": "enabled",
                },
            ]

    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(agents_router, "load_agent_config", _agent_config)
    monkeypatch.setattr(
        agents_router,
        "get_open_api_repository",
        lambda: Repository(),
    )

    complete = await agents_router.list_agents()
    assert {
        agent.id: agent.open_api_enabled for agent in complete.agents
    } == {
        "default": False,
        "api_agent": True,
        "disabled_publication_agent": False,
    }

    client_visible = await agents_router.list_agents(exclude_open_api=True)
    assert [agent.id for agent in client_visible.agents] == [
        "default",
        "disabled_publication_agent",
    ]


@pytest.mark.asyncio
async def test_list_agents_merges_sealed_agents_without_exposing_workspace(
    monkeypatch,
):
    config = _build_config(["default"], agent_order=["default"])

    class Registry:
        def is_sealed(self, agent_id):
            return agent_id == "luyu"

        def list_agents(self):
            return [
                SealedAgentRecord(
                    agent_id="luyu",
                    name="陆羽",
                    description="茶文化专家",
                    enabled=True,
                    active_release_id=None,
                ),
            ]

    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(agents_router, "load_agent_config", _agent_config)
    monkeypatch.setattr(
        agents_router,
        "get_sealed_agent_registry",
        lambda: Registry(),
    )

    response = await agents_router.list_agents()
    sealed = response.agents[1]

    assert [agent.id for agent in response.agents] == ["default", "luyu"]
    assert sealed.agent_type == "sealed"
    assert sealed.scope == "global"
    assert sealed.workspace_dir is None
    assert sealed.capabilities.invoke is True
    assert sealed.capabilities.download is False


@pytest.mark.asyncio
async def test_client_agent_list_excludes_disabled_sealed_agents(monkeypatch):
    config = _build_config(["default"], agent_order=["default"])

    class Registry:
        @staticmethod
        def is_sealed(agent_id):
            return agent_id in {"enabled-luyu", "disabled-luyu"}

        @staticmethod
        def list_agents():
            return [
                SealedAgentRecord(
                    agent_id="enabled-luyu",
                    name="启用陆羽",
                    enabled=True,
                ),
                SealedAgentRecord(
                    agent_id="disabled-luyu",
                    name="停用陆羽",
                    enabled=False,
                ),
            ]

    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(agents_router, "load_agent_config", _agent_config)
    monkeypatch.setattr(
        agents_router,
        "get_sealed_agent_registry",
        lambda: Registry(),
    )

    response = await agents_router.list_agents(exclude_open_api=True)

    assert [agent.id for agent in response.agents] == [
        "default",
        "enabled-luyu",
    ]


@pytest.mark.asyncio
async def test_reorder_agents_rejects_incomplete_payload(monkeypatch):
    """Reorder should reject lists that omit configured agents."""
    config = _build_config(
        ["default", "alpha", "beta"],
        agent_order=["default", "alpha", "beta"],
    )

    monkeypatch.setattr(agents_router, "load_config", lambda: config)

    with pytest.raises(HTTPException) as exc_info:
        await agents_router.reorder_agents(
            agents_router.ReorderAgentsRequest(agent_ids=["alpha", "default"]),
        )

    assert exc_info.value.status_code == 400
    assert "exactly once" in exc_info.value.detail


@pytest.mark.asyncio
async def test_reorder_agents_persists_valid_order(monkeypatch):
    """Reorder API should save the new ordered IDs."""
    config = _build_config(
        ["default", "alpha", "beta"],
        agent_order=["default", "alpha", "beta"],
    )
    saved_orders: list[list[str]] = []

    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(
        agents_router,
        "save_config",
        lambda updated_config: saved_orders.append(
            list(updated_config.agents.agent_order),
        ),
    )

    response = await agents_router.reorder_agents(
        agents_router.ReorderAgentsRequest(
            agent_ids=["beta", "default", "alpha"],
        ),
    )

    assert response["success"] is True
    assert config.agents.agent_order == ["beta", "default", "alpha"]
    assert saved_orders == [["beta", "default", "alpha"]]


@pytest.mark.asyncio
async def test_create_agent_appends_new_id_to_order(monkeypatch, tmp_path):
    """New agents should be appended to the saved order."""
    config = _build_config(
        ["default", "alpha"],
        agent_order=["alpha", "default"],
    )

    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(agents_router, "save_config", lambda updated: None)
    monkeypatch.setattr(
        agents_router,
        "save_agent_config",
        lambda agent_id, agent_config: None,
    )
    monkeypatch.setattr(
        agents_router,
        "_initialize_agent_workspace",
        lambda workspace_dir, skill_names=None, md_template_id=None, language=None: None,  # noqa: E501  # pylint: disable=line-too-long
    )
    monkeypatch.setattr(
        agents_router,
        "generate_short_agent_id",
        lambda: "beta",
    )

    await agents_router.create_agent(
        agents_router.CreateAgentRequest(
            name="Beta",
            workspace_dir=str(tmp_path / "beta"),
        ),
    )

    assert config.agents.agent_order == ["alpha", "default", "beta"]


@pytest.mark.asyncio
async def test_delete_agent_removes_id_from_order(monkeypatch):
    """Deleting an agent should also remove it from the stored order."""
    config = _build_config(
        ["default", "alpha", "beta"],
        agent_order=["alpha", "default", "beta"],
    )

    class DummyManager:
        async def stop_agent(self, agent_id: str) -> None:
            assert agent_id == "beta"

    monkeypatch.setattr(agents_router, "load_config", lambda: config)
    monkeypatch.setattr(agents_router, "save_config", lambda updated: None)
    monkeypatch.setattr(
        agents_router,
        "_get_multi_agent_manager",
        lambda request: DummyManager(),
    )

    await agents_router.delete_agent(
        "beta",
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
    )

    assert config.agents.agent_order == ["alpha", "default"]


@pytest.mark.asyncio
async def test_sealed_publication_remains_client_visible_with_api_marker(monkeypatch):
    from types import SimpleNamespace

    record = SealedAgentRecord(
        agent_id="luyu", name="陆羽", avatar="data:image/png;base64,test"
    )
    monkeypatch.setattr(
        agents_router, "load_config", lambda: _build_config(["default"])
    )
    monkeypatch.setattr(agents_router, "load_agent_config", _agent_config)
    monkeypatch.setattr(
        agents_router,
        "get_sealed_agent_registry",
        lambda: SimpleNamespace(
            is_sealed=lambda agent_id: agent_id == "luyu", list_agents=lambda: [record]
        ),
    )
    monkeypatch.setattr(
        agents_router,
        "get_open_api_repository",
        lambda: SimpleNamespace(
            list_publications=lambda **kwargs: [
                {"target_type": "agent", "target_id": "luyu"}
            ]
        ),
    )
    response = await agents_router.list_agents(exclude_open_api=True)
    sealed = next(agent for agent in response.agents if agent.id == "luyu")
    assert sealed.open_api_enabled is True
    assert sealed.avatar == record.avatar
