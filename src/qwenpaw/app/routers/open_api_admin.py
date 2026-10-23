# -*- coding: utf-8 -*-
"""Admin routes for managing external Open API access."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from ...config.utils import load_config
from ...mindspace import MindspaceScope
from ..expert_teams import get_expert_team_template
from ..open_api import knowledge as experience_knowledge
from ..open_api.auth import generate_open_api_key, hash_open_api_key
from ..open_api.models import OpenApiScope, OpenApiStatus, OpenApiTargetType
from ..sealed_agents.registry import get_sealed_agent_registry
from ..storage.repos.open_api_repo import get_open_api_repository
from ..storage.repos.user_repo import get_user_repository
from . import open_api_knowledge as experience_routes

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


class PublicationBoundUserUpdateRequest(BaseModel):
    bound_user_id: int = Field(gt=0)


def _require_admin(request: Request) -> str:
    if getattr(request.state, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=403, detail="Admin user required")
    return str(user_id)


def _assert_target_exists(target_type: str, target_id: str) -> None:
    if target_type == "agent":
        sealed_registry = get_sealed_agent_registry()
        if sealed_registry.is_sealed(target_id):
            record = sealed_registry.get_agent(target_id)
            if (
                record is None
                or not record.enabled
                or record.active_release_id is None
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Sealed agent target is unavailable",
                )
            return
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


def _target_publication_policy(
    target_type: str,
    target_id: str,
) -> dict[str, str]:
    if (
        target_type == "agent"
        and get_sealed_agent_registry().is_sealed(target_id)
    ):
        return {
            "allowed_capability": "invoke_only",
            "response_policy": "sealed",
        }
    return {
        "allowed_capability": "standard",
        "response_policy": "standard",
    }


def _with_target_policy(publication: dict[str, Any]) -> dict[str, Any]:
    policy = _target_publication_policy(
        str(publication.get("target_type", "")),
        str(publication.get("target_id", "")),
    )
    if policy["response_policy"] != "sealed":
        return publication
    return {**publication, **policy}


@router.get("/publications")
def list_publications(request: Request) -> list[dict[str, Any]]:
    owner_user_id = _require_admin(request)
    return [
        _with_target_policy(publication)
        for publication in get_open_api_repository().list_publications(enabled_only=False)
        if str(publication.get("owner_user_id")) == owner_user_id
        and publication.get("status") != "deleted"
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
        created = repo.upsert_publication(
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
        return _with_target_policy(created)
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
    publication = _owned_publication(publication_id, owner_user_id)
    updated = dict(publication)
    updated["status"] = payload.status
    return repo.upsert_publication(updated)


@router.patch("/publications/{publication_id}/bound-user")
def update_publication_bound_user(
    publication_id: str,
    payload: PublicationBoundUserUpdateRequest,
    request: Request,
) -> dict[str, Any]:
    owner_user_id = _require_admin(request)
    _owned_publication(publication_id, owner_user_id)
    bound_user_id = _resolve_bound_user_id(
        payload.bound_user_id,
        owner_user_id,
    )
    updated = get_open_api_repository().update_publication_bound_user(
        publication_id,
        owner_user_id,
        bound_user_id,
    )
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail="Open API publication not found",
        )
    return updated


@router.delete("/publications/{publication_id}")
def delete_publication(
    publication_id: str,
    request: Request,
) -> dict[str, Any]:
    owner_user_id = _require_admin(request)
    publication = _owned_publication(publication_id, owner_user_id)
    if publication.get("status") != "disabled":
        raise HTTPException(
            status_code=409,
            detail="Disable the Open API publication before deleting it",
        )
    deleted = get_open_api_repository().delete_disabled_publication(
        publication_id,
        owner_user_id,
    )
    if deleted is None:
        raise HTTPException(
            status_code=409,
            detail="Open API publication status changed; disable it before deleting",
        )
    return {"deleted": True, "id": publication_id}


def _owned_publication(publication_id: str, owner_user_id: str) -> dict[str, Any]:
    publication = get_open_api_repository().get_publication(publication_id)
    if (
        publication is None
        or str(publication.get("owner_user_id")) != owner_user_id
        or publication.get("status") == "deleted"
    ):
        raise HTTPException(status_code=404, detail="Open API publication not found")
    return publication


@router.get("/publications/{publication_id}/knowledge/docs")
def list_publication_knowledge_documents(
    publication_id: str,
    request: Request,
) -> list[dict[str, Any]]:
    _require_admin(request)
    return experience_routes.list_documents(publication_id, request)


@router.post("/publications/{publication_id}/knowledge/docs")
async def upload_publication_knowledge_document(
    publication_id: str,
    request: Request,
    file: UploadFile = File(...),
    category: str = Query("uncategorized", max_length=64),
    tags: str | None = Query(None, max_length=512),
) -> dict[str, Any]:
    _require_admin(request)
    return await experience_routes.upload_document(
        publication_id,
        request,
        file,
        category,
        tags,
    )


@router.post("/publications/{publication_id}/knowledge/docs/{doc_id}/sync")
async def sync_publication_knowledge_document(
    publication_id: str,
    doc_id: str,
    request: Request,
) -> dict[str, Any]:
    _require_admin(request)
    return await experience_routes.sync_document(
        publication_id,
        doc_id,
        request,
    )


@router.delete("/publications/{publication_id}/knowledge/docs/{doc_id}")
def delete_publication_knowledge_document(
    publication_id: str,
    doc_id: str,
    request: Request,
) -> dict[str, Any]:
    _require_admin(request)
    return experience_routes.delete_document(
        publication_id,
        doc_id,
        request,
    )


@router.get("/publications/{publication_id}/knowledge/search")
def search_publication_knowledge(
    publication_id: str,
    request: Request,
    q: str = Query(..., min_length=1),
    top_k: int = Query(5, ge=1, le=20),
) -> dict[str, Any]:
    _require_admin(request)
    publication = experience_knowledge.require_accessible_publication(
        publication_id,
        request,
    )
    service = experience_knowledge.publication_knowledge_service(publication)
    hits = service.search(
        q,
        scope=MindspaceScope.PERSONAL,
        top_k=top_k,
    )
    return {"hits": [hit.to_dict() for hit in hits]}


@router.get("/apps")
def list_external_apps(request: Request) -> list[dict[str, Any]]:
    _require_admin(request)
    return get_open_api_repository().list_external_apps()


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
    if app.get("status") != "enabled":
        raise HTTPException(status_code=400, detail="Open API app is disabled")

    publication = _owned_publication(payload.publication_id, owner_user_id)
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
        and publication.get("status") != "deleted"
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
            and publication.get("status") != "deleted"
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
    return (
        publication is not None
        and str(publication.get("owner_user_id")) == owner_user_id
        and publication.get("status") != "deleted"
    )


def _assert_public_id_available(
    repo: Any,
    public_id: str,
    owner_user_id: str,
) -> None:
    for publication in repo.list_publications(enabled_only=False):
        if str(publication.get("public_id")) != public_id:
            continue
        if (
            publication.get("status") == "deleted"
            or str(publication.get("owner_user_id")) != owner_user_id
        ):
            raise HTTPException(
                status_code=409,
                detail="Open API public_id is already used",
            )
        return


def _invocation_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("created_at") or ""), str(row.get("id") or ""))
