from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.sealed_agents import policy
from qwenpaw.app.routers.agent_scoped import create_agent_scoped_router
from qwenpaw.app.routers import agents as agents_router


class Request:
    def __init__(
        self,
        *,
        path_agent=None,
        state_agent=None,
        header_agent=None,
        method="GET",
        url_path="/api/user/skills",
        query_params=None,
    ):
        self.path_params = {"agentId": path_agent} if path_agent else {}
        self.state = SimpleNamespace()
        if state_agent:
            self.state.agent_id = state_agent
        self.headers = {"X-Agent-Id": header_agent} if header_agent else {}
        self.method = method
        self.url = SimpleNamespace(path=url_path)
        self.query_params = query_params or {}


@pytest.mark.parametrize(
    ("req", "expected"),
    [
        (
            Request(
                path_agent="path-agent",
                state_agent="state",
                header_agent="header",
            ),
            "path-agent",
        ),
        (
            Request(state_agent="state-agent", header_agent="header"),
            "state-agent",
        ),
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
        lambda: SimpleNamespace(
            is_sealed=lambda agent_id: agent_id == "luyu",
            package_supports=lambda *_args, **_kwargs: False,
        ),
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


@pytest.mark.parametrize(
    ("url_path", "query_params"),
    [
        ("/api/user/workspace/artifacts", {"session_id": "chat-1"}),
        ("/api/user/workspace/artifacts/download", {"session_id": "chat-1"}),
        (
            "/api/user/workspace/files/download/report.pdf",
            {"chatId": "chat-1"},
        ),
    ],
)
def test_asset_guard_allows_owned_chat_artifact_delivery_for_sealed_agent(
    monkeypatch,
    url_path,
    query_params,
):
    monkeypatch.setattr(
        policy,
        "get_sealed_agent_registry",
        lambda: SimpleNamespace(
            is_sealed=lambda agent_id: agent_id == "luyu",
            package_supports=lambda *_args, **_kwargs: False,
        ),
    )

    policy.deny_sealed_asset_access(
        Request(
            header_agent="luyu",
            method="GET",
            url_path=url_path,
            query_params=query_params,
        ),
    )


@pytest.mark.parametrize(
    ("url_path", "query_params"),
    [
        ("/api/user/workspace/artifacts", {}),
        ("/api/user/workspace/files/raw/report.md", {"chatId": "chat-1"}),
        ("/api/agents/luyu/workspace/artifacts", {"session_id": "chat-1"}),
    ],
)
def test_asset_guard_keeps_other_sealed_workspace_assets_protected(
    monkeypatch,
    url_path,
    query_params,
):
    monkeypatch.setattr(
        policy,
        "get_sealed_agent_registry",
        lambda: SimpleNamespace(
            is_sealed=lambda agent_id: agent_id == "luyu",
            package_supports=lambda agent_id, feature: (
                agent_id == "luyu" and feature == "mutable_skill_overlay"
            ),
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        policy.deny_sealed_asset_access(
            Request(
                header_agent="luyu",
                method="GET",
                url_path=url_path,
                query_params=query_params,
            ),
        )

    assert exc_info.value.status_code == 403


def test_skill_asset_guard_allows_global_pool_listing_with_sealed_header(
    monkeypatch,
):
    monkeypatch.setattr(
        policy,
        "get_sealed_agent_registry",
        lambda: SimpleNamespace(
            is_sealed=lambda agent_id: agent_id == "luyu",
            package_supports=lambda agent_id, feature: (
                agent_id == "luyu" and feature == "mutable_skill_overlay"
            ),
        ),
    )

    policy.deny_sealed_skill_asset_access(
        Request(
            header_agent="luyu",
            method="GET",
            url_path="/api/user/skills/pool",
        ),
    )


def test_skill_asset_guard_still_denies_sealed_workspace_download(monkeypatch):
    monkeypatch.setattr(
        policy,
        "get_sealed_agent_registry",
        lambda: SimpleNamespace(
            is_sealed=lambda agent_id: agent_id == "luyu",
            package_supports=lambda *_args, **_kwargs: False,
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        policy.deny_sealed_skill_asset_access(
            Request(
                header_agent="luyu",
                method="POST",
                url_path="/api/user/skills/pool/download",
            ),
        )

    assert exc_info.value.status_code == 403


def test_skill_asset_guard_allows_super_expert_pool_download(monkeypatch):
    registry = SimpleNamespace(
        is_sealed=lambda agent_id: agent_id == "luyu",
        package_supports=lambda agent_id, feature: (
            agent_id == "luyu" and feature == "mutable_skill_overlay"
        ),
    )
    monkeypatch.setattr(
        policy,
        "get_sealed_agent_registry",
        lambda: registry,
    )

    policy.deny_sealed_skill_asset_access(
        Request(
            header_agent="luyu",
            method="POST",
            url_path="/api/user/skills/pool/download",
        ),
    )


def test_skill_asset_guard_allows_super_expert_overlay_management(monkeypatch):
    registry = SimpleNamespace(
        is_sealed=lambda agent_id: agent_id == "luyu",
        package_supports=lambda agent_id, feature: (
            agent_id == "luyu" and feature == "mutable_skill_overlay"
        ),
    )
    monkeypatch.setattr(
        policy,
        "get_sealed_agent_registry",
        lambda: registry,
    )

    policy.deny_sealed_skill_asset_access(
        Request(
            header_agent="luyu",
            method="GET",
            url_path="/api/user/skills",
        ),
    )


def test_agent_scoped_skill_routes_use_skill_specific_guard():
    scoped_router = create_agent_scoped_router()
    skill_routes = [
        route
        for route in scoped_router.routes
        if route.original_router.prefix == "/skills"
    ]

    assert skill_routes
    assert all(
        any(
            dependency.dependency is policy.deny_sealed_skill_asset_access
            for dependency in route.include_context.dependencies
        )
        for route in skill_routes
    )


@pytest.mark.parametrize(
    "url_path",
    [
        "/api/user/skills/poolish",
        "/api/user/skills/pool/download/preview",
    ],
)
def test_skill_asset_guard_does_not_overmatch_global_pool_paths(
    monkeypatch,
    url_path,
):
    monkeypatch.setattr(
        policy,
        "get_sealed_agent_registry",
        lambda: SimpleNamespace(
            is_sealed=lambda agent_id: agent_id == "luyu",
            package_supports=lambda *_args, **_kwargs: False,
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        policy.deny_sealed_skill_asset_access(
            Request(header_agent="luyu", url_path=url_path),
        )

    assert exc_info.value.status_code == 403


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
