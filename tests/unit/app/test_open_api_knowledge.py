# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Request

from qwenpaw.app.open_api import knowledge
from qwenpaw.app.routers import open_api_knowledge


class FakeOpenApiRepository:
    def __init__(self, *publications: dict[str, object]) -> None:
        self.publications = {
            str(publication["id"]): publication
            for publication in publications
        }

    def list_publications(self, enabled_only: bool = False):
        assert enabled_only is False
        return list(self.publications.values())

    def get_publication(self, publication_id: str):
        return self.publications.get(publication_id)


def _request(*, role: str, user_id: str) -> Request:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/open-api-knowledge/publications",
            "raw_path": b"/api/open-api-knowledge/publications",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8088),
            "scheme": "http",
        },
    )
    request.state.role = role
    request.state.user_id = user_id
    return request


def _patch_repo(monkeypatch, repo: FakeOpenApiRepository) -> None:
    monkeypatch.setattr(knowledge, "get_open_api_repository", lambda: repo)


def test_user_lists_only_bound_publications(monkeypatch):
    repo = FakeOpenApiRepository(
        {
            "id": "mine",
            "public_id": "support",
            "name": "客服入口",
            "target_type": "agent",
            "target_id": "agent-1",
            "owner_user_id": "admin",
            "bound_user_id": "7",
            "knowledge_base_id": "openapi-mine",
            "status": "enabled",
        },
        {
            "id": "other",
            "public_id": "sales",
            "name": "销售入口",
            "target_type": "agent",
            "target_id": "agent-2",
            "owner_user_id": "admin",
            "bound_user_id": "8",
            "knowledge_base_id": "openapi-other",
            "status": "disabled",
        },
    )
    _patch_repo(monkeypatch, repo)
    names = {"agent-1": "客服专家", "agent-2": "销售专家"}
    monkeypatch.setattr(
        knowledge,
        "load_agent_config",
        lambda agent_id: SimpleNamespace(name=names[agent_id]),
    )

    rows = open_api_knowledge.list_experience_publications(
        _request(user_id="7", role="user"),
    )

    assert [row["id"] for row in rows] == ["mine"]
    assert rows[0]["target_name"] == "客服专家"
    assert "workspace_dir" not in rows[0]


def test_admin_lists_only_owned_publications(monkeypatch):
    repo = FakeOpenApiRepository(
        {
            "id": "mine",
            "public_id": "support",
            "name": "客服入口",
            "target_type": "agent",
            "target_id": "agent-1",
            "owner_user_id": "admin-1",
            "bound_user_id": "7",
            "knowledge_base_id": "openapi-mine",
            "status": "enabled",
        },
        {
            "id": "other",
            "public_id": "sales",
            "name": "销售入口",
            "target_type": "agent",
            "target_id": "agent-2",
            "owner_user_id": "admin-2",
            "bound_user_id": "7",
            "knowledge_base_id": "openapi-other",
            "status": "enabled",
        },
    )
    _patch_repo(monkeypatch, repo)
    monkeypatch.setattr(
        knowledge,
        "load_agent_config",
        lambda agent_id: SimpleNamespace(name=agent_id),
    )

    rows = open_api_knowledge.list_experience_publications(
        _request(user_id="admin-1", role="admin"),
    )

    assert [row["id"] for row in rows] == ["mine"]


def test_inaccessible_publication_is_reported_as_not_found(monkeypatch):
    _patch_repo(
        monkeypatch,
        FakeOpenApiRepository(
            {
                "id": "private",
                "owner_user_id": "admin",
                "bound_user_id": "8",
            },
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        knowledge.require_accessible_publication(
            "private",
            _request(user_id="7", role="user"),
        )

    assert exc_info.value.status_code == 404


def test_experience_router_is_mounted_at_neutral_authenticated_prefix():
    from fastapi import FastAPI
    from qwenpaw.app.routers import router

    effective_app = FastAPI()
    effective_app.include_router(router, prefix="/api")
    paths = set(effective_app.openapi()["paths"])

    assert "/api/open-api-knowledge/publications" in paths
