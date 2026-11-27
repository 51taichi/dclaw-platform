"""Background startup must gate deployment readiness."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app._app import (
    _recover_local_capability_gateways,
    app,
    get_readiness,
)
from qwenpaw.config.config import MCPClientConfig, MCPConfig


def _state(monkeypatch, *, phase, agents, expected, loaded, hooks=0):
    values = {
        "startup_phase": phase,
        "agent_startup_results": agents,
        "expected_plugin_ids": list(expected),
        "expected_plugin_versions": expected,
        "loaded_plugin_versions": loaded,
        "failed_control_commands": 0,
        "failed_startup_hooks": hooks,
        "knowledge_worker_ready": True,
        "local_gateways_expected": 0,
        "local_gateways_ready": 0,
    }
    for name, value in values.items():
        monkeypatch.setattr(app.state, name, value, raising=False)


def test_loading_is_not_ready(monkeypatch):
    _state(
        monkeypatch,
        phase="loading",
        agents={},
        expected={},
        loaded={},
    )
    response = get_readiness()
    assert response.status_code == 503
    assert json.loads(response.body)["status"] == "loading"


def test_all_agents_and_exact_plugin_versions_are_ready(monkeypatch):
    _state(
        monkeypatch,
        phase="ready",
        agents={"a": True, "b": True},
        expected={"support": "1.18.58"},
        loaded={"support": "1.18.58"},
    )
    response = get_readiness()
    assert response.status_code == 200
    assert json.loads(response.body)["agents_ready"] == 2


def test_plugin_fallback_or_agent_failure_blocks_readiness(monkeypatch):
    _state(
        monkeypatch,
        phase="ready",
        agents={"a": True, "b": False},
        expected={"support": "1.18.58"},
        loaded={"support": "1.18.52"},
    )
    response = get_readiness()
    assert response.status_code == 503
    assert json.loads(response.body)["plugins_ready"] == 0


def test_missing_local_gateway_blocks_readiness(monkeypatch):
    _state(
        monkeypatch,
        phase="ready",
        agents={"a": True},
        expected={},
        loaded={},
    )
    app.state.local_gateways_expected = 1
    response = get_readiness()
    assert response.status_code == 503
    assert json.loads(response.body)["local_gateways_ready"] == 0


@pytest.mark.asyncio
async def test_local_gateway_reconnects_after_workspace_startup():
    client = SimpleNamespace(is_connected=True)
    mcp_manager = SimpleNamespace(
        get_client=AsyncMock(side_effect=[None, client]),
        replace_client=AsyncMock(),
    )
    config = MCPConfig(clients={
        "local_capability_gateway": MCPClientConfig(
            name="local-gateway",
            transport="streamable_http",
            url="http://127.0.0.1:8088/api/super-agent-support/mcp",
        ),
    })
    agent = SimpleNamespace(config=SimpleNamespace(mcp=config), mcp_manager=mcp_manager)
    manager = SimpleNamespace(agents={"sealed-agent": agent})

    assert await _recover_local_capability_gateways(manager) == (1, 1)
    mcp_manager.replace_client.assert_awaited_once_with(
        "local_capability_gateway",
        config.clients["local_capability_gateway"],
        timeout=15.0,
    )


@pytest.mark.asyncio
async def test_local_gateway_reconnect_failure_remains_unready():
    mcp_manager = SimpleNamespace(
        get_client=AsyncMock(return_value=None),
        replace_client=AsyncMock(side_effect=TimeoutError("gateway unavailable")),
    )
    config = MCPConfig(clients={
        "local_capability_gateway": MCPClientConfig(
            name="local-gateway",
            transport="streamable_http",
            url="http://127.0.0.1:8088/api/super-agent-support/mcp",
        ),
    })
    agent = SimpleNamespace(config=SimpleNamespace(mcp=config), mcp_manager=mcp_manager)

    assert await _recover_local_capability_gateways(
        SimpleNamespace(agents={"sealed-agent": agent}),
    ) == (1, 0)
