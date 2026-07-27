# -*- coding: utf-8 -*-
"""Admin routes for managing external Open API access."""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from ...config.utils import load_config
from ...constant import WORKING_DIR
from ...mindspace import MindspaceScope, MindspaceService
from ...mindspace.models import (
    normalize_knowledge_category,
    normalize_knowledge_tags,
)
from ..expert_teams import get_expert_team_template
from ..open_api.auth import generate_open_api_key, hash_open_api_key
from ..open_api.models import OpenApiScope, OpenApiStatus, OpenApiTargetType
from ..storage.repos.open_api_repo import get_open_api_repository
from ..storage.repos.user_repo import get_user_repository

router = APIRouter(prefix="/open-api", tags=["admin-open-api"])


class PublicationCreateRequest(BaseModel):
    public_id: str
    target_type: OpenApiTargetType
    target_id: str
    name: str
    description: str = ""
    bound_user_id: int | None = Field(default=None, gt=0)
    allowed_scopes: list[OpenApiScope] = Field(default_factory=list)
    status: OpenApiStatus = "enabled"


class ExternalAppCreateRequest(BaseModel):
    name: str
    ip_allowlist: list[str] = Field(default_factory=list)
    quota_policy: dict[str, Any] = Field(default_factory=dict)


class ApiKeyCreateRequest(BaseModel):
    app_id: str
    publication_id: str
    scopes: list[OpenApiScope] = Field(default_factory=list)
    expires_at: datetime | None = None


class PublicationStatusUpdateRequest(BaseModel):
    status: OpenApiStatus


def _require_admin(request: Request) -> str:
    if getattr(request.state, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=403, detail="Admin user required")
    return str(user_id)


def _assert_target_exists(target_type: str, target_id: str) -> None:
    if target_type == "agent":
        config = load_config()
        profiles = getattr(getattr(config, "agents", None), "profiles", {}) or {}
        if target_id not in profiles:
            raise HTTPException(status_code=404, detail="Agent target not found")
        return

    if target_type == "expert_team":
        template = get_expert_team_template(target_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Expert team target not found")
        if getattr(template, "enabled", True) is False:
            raise HTTPException(status_code=400, detail="Expert team target is disabled")
        return

    raise HTTPException(status_code=400, detail="Unsupported Open API target type")


@router.get("/publications")
def list_publications(request: Request) -> list[dict[str, Any]]:
    owner_user_id = _require_admin(request)
    return [
        publication
        for publication in get_open_api_repository().list_publications(enabled_only=False)
        if str(publication.get("owner_user_id")) == owner_user_id
    ]


@router.post("/publications")
def create_publication(
    payload: PublicationCreateRequest,
    request: Request,
) -> dict[str, Any]:
    owner_user_id = _require_admin(request)
    _assert_target_exists(payload.target_type, payload.target_id)
    bound_user_id = _resolve_bound_user_id(payload.bound_user_id, owner_user_id)
    if not payload.allowed_scopes:
        raise HTTPException(status_code=400, detail="Open API publication scopes are required")
    repo = get_open_api_repository()
    _assert_public_id_available(repo, payload.public_id, owner_user_id)
    publication_id = str(uuid.uuid4())
    try:
        return repo.upsert_publication(
            {
                "id": publication_id,
                "public_id": payload.public_id,
                "target_type": payload.target_type,
                "target_id": payload.target_id,
                "owner_user_id": owner_user_id,
                "bound_user_id": bound_user_id,
                "knowledge_base_id": f"openapi-{publication_id}",
                "name": payload.name,
                "description": payload.description,
                "status": payload.status,
                "allowed_scopes": list(payload.allowed_scopes),
            },
        )
    except ValueError as exc:
        if (
            "owner cannot be changed" in str(exc)
            or "public_id is already used" in str(exc)
        ):
            raise HTTPException(
                status_code=409,
                detail="Open API public_id is already used",
            ) from exc
        raise


def _resolve_bound_user_id(
    requested_user_id: int | None,
    owner_user_id: str,
) -> str:
    """Resolve the QwenPaw identity whose chats and knowledge are used at runtime."""
    if requested_user_id is None:
        return owner_user_id
    user = get_user_repository().get_user_by_id(requested_user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Open API bound user not found")
    return str(user["id"])


@router.patch("/publications/{publication_id}/status")
def update_publication_status(
    publication_id: str,
    payload: PublicationStatusUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    owner_user_id = _require_admin(request)
    repo = get_open_api_repository()
    publication = repo.get_publication(publication_id)
    if publication is None:
        raise HTTPException(status_code=404, detail="Open API publication not found")
    if str(publication.get("owner_user_id")) != owner_user_id:
        raise HTTPException(status_code=404, detail="Open API publication not found")
    updated = dict(publication)
    updated["status"] = payload.status
    return repo.upsert_publication(updated)


def _owned_publication(publication_id: str, owner_user_id: str) -> dict[str, Any]:
    publication = get_open_api_repository().get_publication(publication_id)
    if (
        publication is None
        or str(publication.get("owner_user_id")) != owner_user_id
    ):
        raise HTTPException(status_code=404, detail="Open API publication not found")
    return publication


def _publication_agent_id(publication: dict[str, Any]) -> str:
    if publication.get("target_type") == "agent":
        return str(publication["target_id"])
    if publication.get("target_type") == "expert_team":
        template = get_expert_team_template(str(publication["target_id"]))
        if template is None:
            raise HTTPException(status_code=404, detail="Expert team target not found")
        return str(template.leader_agent_id)
    raise HTTPException(status_code=400, detail="Unsupported Open API target type")


def _publication_knowledge_service(
    publication: dict[str, Any],
) -> MindspaceService:
    agent_id = _publication_agent_id(publication)
    config = load_config()
    profiles = getattr(getattr(config, "agents", None), "profiles", {}) or {}
    profile = profiles.get(agent_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Agent target not found")
    workspace_dir = Path(profile.workspace_dir).expanduser()
    return MindspaceService(
        global_root=Path(WORKING_DIR) / "mindspace",
        agent_workspace=workspace_dir,
        agent_id=agent_id,
        user_id=str(publication["knowledge_base_id"]),
        exclusive_personal=True,
    )


@router.get("/publications/{publication_id}/knowledge/docs")
def list_publication_knowledge_documents(
    publication_id: str,
    request: Request,
) -> list[dict[str, Any]]:
    owner_user_id = _require_admin(request)
    publication = _owned_publication(publication_id, owner_user_id)
    service = _publication_knowledge_service(publication)
    return [
        doc.to_api_dict()
        for doc in service.list_documents(MindspaceScope.PERSONAL)
    ]


@router.post("/publications/{publication_id}/knowledge/docs")
async def upload_publication_knowledge_document(
    publication_id: str,
    request: Request,
    file: UploadFile = File(...),
    category: str = Query("uncategorized", max_length=64),
    tags: str | None = Query(None, max_length=512),
) -> dict[str, Any]:
    owner_user_id = _require_admin(request)
    publication = _owned_publication(publication_id, owner_user_id)
    service = _publication_knowledge_service(publication)
    filename = file.filename or "knowledge.txt"
    suffix = os.path.splitext(filename)[1].lower().lstrip(".") or "txt"
    content = await file.read()
    doc = await asyncio.to_thread(
        service.stage_local_bytes,
        name=filename,
        content=content,
        scope=MindspaceScope.PERSONAL,
        source_type=suffix,
        mime_type=file.content_type,
        category=normalize_knowledge_category(category),
        tags=normalize_knowledge_tags(tags),
    )
    indexed = await asyncio.to_thread(
        service.process_staged_document,
        doc.id,
        MindspaceScope.PERSONAL,
    )
    return (indexed or doc).to_api_dict()


@router.post("/publications/{publication_id}/knowledge/docs/{doc_id}/sync")
async def sync_publication_knowledge_document(
    publication_id: str,
    doc_id: str,
    request: Request,
) -> dict[str, Any]:
    owner_user_id = _require_admin(request)
    publication = _owned_publication(publication_id, owner_user_id)
    service = _publication_knowledge_service(publication)
    doc = service.get_document(doc_id, MindspaceScope.PERSONAL)
    if doc is None:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    indexed = await service.resync_document(
        doc.id,
        MindspaceScope.PERSONAL,
    )
    return (indexed or doc).to_api_dict()


@router.delete("/publications/{publication_id}/knowledge/docs/{doc_id}")
def delete_publication_knowledge_document(
    publication_id: str,
    doc_id: str,
    request: Request,
) -> dict[str, Any]:
    owner_user_id = _require_admin(request)
    publication = _owned_publication(publication_id, owner_user_id)
    service = _publication_knowledge_service(publication)
    if not service.delete_document(doc_id, MindspaceScope.PERSONAL):
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return {"deleted": True, "id": doc_id}


@router.get("/publications/{publication_id}/knowledge/search")
def search_publication_knowledge(
    publication_id: str,
    request: Request,
    q: str = Query(..., min_length=1),
    top_k: int = Query(5, ge=1, le=20),
) -> dict[str, Any]:
    owner_user_id = _require_admin(request)
    publication = _owned_publication(publication_id, owner_user_id)
    service = _publication_knowledge_service(publication)
    hits = service.search(
        q,
        scope=MindspaceScope.PERSONAL,
        top_k=top_k,
    )
    return {"hits": [hit.to_dict() for hit in hits]}


@router.get("/apps")
def list_external_apps(request: Request) -> list[dict[str, Any]]:
    owner_user_id = _require_admin(request)
    return get_open_api_repository().list_external_apps(owner_user_id=owner_user_id)


@router.post("/apps")
def create_external_app(
    payload: ExternalAppCreateRequest,
    request: Request,
) -> dict[str, Any]:
    owner_user_id = _require_admin(request)
    return get_open_api_repository().create_external_app(
        {
            "id": str(uuid.uuid4()),
            "owner_user_id": owner_user_id,
            "name": payload.name,
            "status": "enabled",
            "ip_allowlist": list(payload.ip_allowlist),
            "quota_policy": dict(payload.quota_policy),
        },
    )


@router.post("/keys")
def create_api_key(
    payload: ApiKeyCreateRequest,
    request: Request,
) -> dict[str, Any]:
    owner_user_id = _require_admin(request)
    repo = get_open_api_repository()
    app = repo.get_external_app(payload.app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="Open API app not found")
    if str(app.get("owner_user_id")) != owner_user_id:
        raise HTTPException(status_code=404, detail="Open API app not found")
    if app.get("status") != "enabled":
        raise HTTPException(status_code=400, detail="Open API app is disabled")

    publication = repo.get_publication(payload.publication_id)
    if publication is None:
        raise HTTPException(status_code=404, detail="Open API publication not found")
    if (
        str(publication.get("owner_user_id")) != owner_user_id
        or str(publication.get("owner_user_id")) != str(app.get("owner_user_id"))
    ):
        raise HTTPException(status_code=404, detail="Open API publication not found")
    if publication.get("status") != "enabled":
        raise HTTPException(status_code=400, detail="Open API publication is disabled")

    requested_scopes = set(payload.scopes)
    if not requested_scopes:
        raise HTTPException(status_code=400, detail="Open API key scopes are required")
    allowed_scopes = set(publication.get("allowed_scopes") or [])
    if not requested_scopes.issubset(allowed_scopes):
        raise HTTPException(status_code=400, detail="Open API scopes exceed publication allowance")

    plaintext_key, display = generate_open_api_key()
    key = repo.create_api_key(
        {
            "id": str(uuid.uuid4()),
            "app_id": payload.app_id,
            "publication_id": payload.publication_id,
            "key_hash": hash_open_api_key(plaintext_key),
            "key_prefix": display["key_prefix"],
            "key_suffix": display["key_suffix"],
            "scopes": list(payload.scopes),
            "status": "active",
            "expires_at": payload.expires_at,
        },
    )
    return {"plaintext_key": plaintext_key, "key": key}


@router.get("/keys")
def list_api_keys(
    request: Request,
    app_id: str | None = None,
    publication_id: str | None = None,
) -> list[dict[str, Any]]:
    owner_user_id = _require_admin(request)
    repo = get_open_api_repository()
    keys = repo.list_api_keys(
        app_id=app_id,
        publication_id=publication_id,
    )
    visible_publication_ids = {
        str(publication["id"])
        for publication in repo.list_publications(enabled_only=False)
        if str(publication.get("owner_user_id")) == owner_user_id
    }
    return [
        key
        for key in keys
        if str(key.get("publication_id")) in visible_publication_ids
    ]


@router.post("/keys/{key_id}/revoke")
def revoke_api_key(key_id: str, request: Request) -> dict[str, Any]:
    owner_user_id = _require_admin(request)
    repo = get_open_api_repository()
    visible_key = next(
        (
            key
            for key in repo.list_api_keys()
            if str(key.get("id")) == key_id
            and _owns_publication(repo, str(key.get("publication_id")), owner_user_id)
        ),
        None,
    )
    if visible_key is None:
        raise HTTPException(status_code=404, detail="Open API key not found")
    key = repo.update_api_key_status(key_id, "revoked")
    if key is None:
        raise HTTPException(status_code=404, detail="Open API key not found")
    return key


@router.get("/invocations")
def list_invocations(
    request: Request,
    publication_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    owner_user_id = _require_admin(request)
    repo = get_open_api_repository()
    if publication_id is not None and not _owns_publication(repo, publication_id, owner_user_id):
        raise HTTPException(status_code=404, detail="Open API publication not found")
    scoped_publication_id = publication_id
    if scoped_publication_id is None:
        visible_publication_ids = {
            str(publication["id"])
            for publication in repo.list_publications(enabled_only=False)
            if str(publication.get("owner_user_id")) == owner_user_id
        }
        rows: list[dict[str, Any]] = []
        for visible_publication_id in visible_publication_ids:
            rows.extend(
                repo.list_invocations(
                    publication_id=visible_publication_id,
                    limit=limit + offset,
                    offset=0,
                ),
            )
        rows.sort(key=_invocation_sort_key, reverse=True)
        return rows[offset : offset + limit]
    return get_open_api_repository().list_invocations(
        publication_id=scoped_publication_id,
        limit=limit,
        offset=offset,
    )


def _owns_publication(repo: Any, publication_id: str, owner_user_id: str) -> bool:
    publication = repo.get_publication(publication_id)
    return publication is not None and str(publication.get("owner_user_id")) == owner_user_id


def _assert_public_id_available(
    repo: Any,
    public_id: str,
    owner_user_id: str,
) -> None:
    for publication in repo.list_publications(enabled_only=False):
        if str(publication.get("public_id")) != public_id:
            continue
        if str(publication.get("owner_user_id")) != owner_user_id:
            raise HTTPException(
                status_code=409,
                detail="Open API public_id is already used",
            )
        return


def _invocation_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("created_at") or ""), str(row.get("id") or ""))
