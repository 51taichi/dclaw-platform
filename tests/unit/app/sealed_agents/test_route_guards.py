from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.sealed_agents import policy
from qwenpaw.app.routers import agents as agents_router


class Request:
    def __init__(self, *, path_agent=None, state_agent=None, header_agent=None):
        self.path_params = {"agentId": path_agent} if path_agent else {}
        self.state = SimpleNamespace()
        if state_agent:
            self.state.agent_id = state_agent
        self.headers = {"X-Agent-Id": header_agent} if header_agent else {}


@pytest.mark.parametrize(
    ("req", "expected"),
    [
        (Request(path_agent="path-agent", state_agent="state", header_agent="header"), "path-agent"),
        (Request(state_agent="state-agent", header_agent="header"), "state-agent"),
        (Request(header_agent="header-agent"), "header-agent"),
    ],
)
def test_requested_agent_id_uses_trusted_precedence(req, expected):
    assert policy.requested_agent_id(req) == expected


def test_asset_guard_denies_sealed_agent_before_resolver_runs(monkeypatch):
    resolved = []
    monkeypatch.setattr(
        policy,
        "get_sealed_agent_registry",
        lambda: SimpleNamespace(is_sealed=lambda agent_id: agent_id == "luyu"),
    )

    with pytest.raises(HTTPException) as exc_info:
        policy.deny_sealed_asset_access(Request(header_agent="luyu"))
        resolved.append("filesystem-read")

    assert exc_info.value.status_code == 403
    assert resolved == []


def test_asset_guard_keeps_standard_agent_routes_unchanged(monkeypatch):
    monkeypatch.setattr(
        policy,
        "get_sealed_agent_registry",
        lambda: SimpleNamespace(is_sealed=lambda agent_id: False),
    )

    policy.deny_sealed_asset_access(Request(header_agent="ordinary"))


@pytest.mark.asyncio
async def test_direct_agent_detail_never_loads_sealed_profile(monkeypatch):
    registry = SimpleNamespace(is_sealed=lambda agent_id: agent_id == "luyu")
    loaded = []
    monkeypatch.setattr(
        agents_router,
        "get_sealed_agent_registry",
        lambda: registry,
    )
    monkeypatch.setattr(
        agents_router,
        "load_agent_config",
        lambda agent_id: loaded.append(agent_id),
    )

    with pytest.raises(HTTPException) as exc_info:
        await agents_router.get_agent("luyu")

    assert exc_info.value.status_code == 403
    assert loaded == []
