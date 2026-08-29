# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace
from io import BytesIO

import pytest
from fastapi import HTTPException, Request, UploadFile

from qwenpaw.mindspace import MindspaceScope

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


class FakeDocument:
    def __init__(self, doc_id: str, name: str | None = None) -> None:
        self.id = doc_id
        self.name = name or f"{doc_id}.txt"

    def to_api_dict(self):
        return {"id": self.id, "name": self.name}


class FakeKnowledgeService:
    def __init__(self, docs: list[FakeDocument] | None = None) -> None:
        self.docs = list(docs or [])
        self.list_scope = None
        self.deleted: list[tuple[str, MindspaceScope]] = []
        self.staged_content: bytes | None = None

    def list_documents(self, scope):
        self.list_scope = scope
        return list(self.docs)

    def stage_local_bytes(self, **kwargs):
        self.staged_content = kwargs["content"]
        doc = FakeDocument("uploaded", kwargs["name"])
        self.docs.append(doc)
        return doc

    def process_staged_document(self, doc_id, scope):
        assert doc_id == "uploaded"
        assert scope == MindspaceScope.PERSONAL
        return self.docs[-1]

    def get_document(self, doc_id, scope):
        assert scope == MindspaceScope.PERSONAL
        return next((doc for doc in self.docs if doc.id == doc_id), None)

    async def resync_document(self, doc_id, scope):
        return self.get_document(doc_id, scope)

    def delete_document(self, doc_id, scope):
        self.deleted.append((doc_id, scope))
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if doc.id != doc_id]
        return len(self.docs) != before


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


def _publication(*, bound_user_id: str = "7", status: str = "enabled"):
    return {
        "id": "pub-1",
        "public_id": "support",
        "name": "客服入口",
        "target_type": "agent",
        "target_id": "agent-1",
        "owner_user_id": "admin-1",
        "bound_user_id": bound_user_id,
        "knowledge_base_id": "openapi-pub-1",
        "status": status,
    }


def _patch_service(monkeypatch, service: FakeKnowledgeService) -> None:
    monkeypatch.setattr(
        knowledge,
        "publication_knowledge_service",
        lambda publication: service,
    )


def test_bound_user_can_list_documents_for_disabled_publication(monkeypatch):
    _patch_repo(
        monkeypatch,
        FakeOpenApiRepository(_publication(status="disabled")),
    )
    service = FakeKnowledgeService([FakeDocument("doc-1")])
    _patch_service(monkeypatch, service)

    rows = open_api_knowledge.list_documents(
        "pub-1",
        _request(user_id="7", role="user"),
    )

    assert rows == [{"id": "doc-1", "name": "doc-1.txt"}]
    assert service.list_scope == MindspaceScope.PERSONAL


@pytest.mark.asyncio
async def test_non_bound_user_cannot_upload(monkeypatch):
    _patch_repo(
        monkeypatch,
        FakeOpenApiRepository(_publication(bound_user_id="8")),
    )
    _patch_service(monkeypatch, FakeKnowledgeService())

    with pytest.raises(HTTPException) as exc_info:
        await open_api_knowledge.upload_document(
            "pub-1",
            _request(user_id="7", role="user"),
            UploadFile(filename="guide.txt", file=BytesIO(b"content")),
        )

    assert exc_info.value.status_code == 404


def test_permission_is_rechecked_before_delete(monkeypatch):
    publication = _publication()
    _patch_repo(monkeypatch, FakeOpenApiRepository(publication))
    service = FakeKnowledgeService([FakeDocument("doc-1")])
    _patch_service(monkeypatch, service)
    request = _request(user_id="7", role="user")
    assert open_api_knowledge.list_documents("pub-1", request)
    publication["bound_user_id"] = "8"

    with pytest.raises(HTTPException) as exc_info:
        open_api_knowledge.delete_document("pub-1", "doc-1", request)

    assert exc_info.value.status_code == 404
    assert service.deleted == []


@pytest.mark.asyncio
async def test_bound_user_can_upload_and_sync_document(monkeypatch):
    _patch_repo(monkeypatch, FakeOpenApiRepository(_publication()))
    service = FakeKnowledgeService()
    _patch_service(monkeypatch, service)
    request = _request(user_id="7", role="user")

    uploaded = await open_api_knowledge.upload_document(
        "pub-1",
        request,
        UploadFile(filename="guide.txt", file=BytesIO(b"content")),
    )
    synced = await open_api_knowledge.sync_document(
        "pub-1",
        "uploaded",
        request,
    )

    assert uploaded == {"id": "uploaded", "name": "guide.txt"}
    assert synced == uploaded
    assert service.staged_content == b"content"


def test_bound_user_can_delete_document(monkeypatch):
    _patch_repo(monkeypatch, FakeOpenApiRepository(_publication()))
    service = FakeKnowledgeService([FakeDocument("doc-1")])
    _patch_service(monkeypatch, service)

    result = open_api_knowledge.delete_document(
        "pub-1",
        "doc-1",
        _request(user_id="7", role="user"),
    )

    assert result == {"deleted": True, "id": "doc-1"}
    assert service.deleted == [("doc-1", MindspaceScope.PERSONAL)]
