# -*- coding: utf-8 -*-
"""Shared authorization and metadata for Open API experience libraries."""
from __future__ import annotations

from typing import Any
from pathlib import Path

from fastapi import HTTPException, Request

from ...config.config import load_agent_config
from ...config.utils import load_config
from ...constant import WORKING_DIR
from ...mindspace import MindspaceService
from ..expert_teams import get_expert_team_template
from ..sealed_agents.registry import get_sealed_agent_registry
from ..storage.repos.open_api_repo import get_open_api_repository


_PUBLICATION_FIELDS = (
    "id",
    "public_id",
    "name",
    "target_type",
    "target_id",
    "status",
    "knowledge_base_id",
)


def can_manage_publication(
    publication: dict[str, Any],
    request: Request,
) -> bool:
    """Return whether the authenticated caller may manage its knowledge."""
    user_id = str(getattr(request.state, "user_id", "") or "")
    if not user_id:
        return False
    if getattr(request.state, "role", None) == "admin":
        return str(publication.get("owner_user_id") or "") == user_id
    return str(publication.get("bound_user_id") or "") == user_id


def require_accessible_publication(
    publication_id: str,
    request: Request,
) -> dict[str, Any]:
    """Resolve an authorized publication without leaking its existence."""
    publication = get_open_api_repository().get_publication(publication_id)
    if publication is None or not can_manage_publication(publication, request):
        raise HTTPException(
            status_code=404,
            detail="Open API publication not found",
        )
    return publication


def publication_target_name(publication: dict[str, Any]) -> str:
    """Resolve a display-only target name without exposing target assets."""
    target_id = str(publication.get("target_id") or "")
    target_type = str(publication.get("target_type") or "")
    if target_type == "agent":
        sealed = get_sealed_agent_registry().get_agent(target_id)
        if sealed is not None:
            return sealed.name or str(publication.get("name") or target_id)
        try:
            return load_agent_config(target_id).name
        except Exception:
            pass
    elif target_type == "expert_team":
        team = get_expert_team_template(target_id)
        if team is not None:
            return team.name
    return str(publication.get("name") or target_id)


def publication_summary(publication: dict[str, Any]) -> dict[str, Any]:
    """Return only the operational metadata required by the shared UI."""
    return {
        field: publication.get(field)
        for field in _PUBLICATION_FIELDS
    } | {"target_name": publication_target_name(publication)}


def list_accessible_publications(request: Request) -> list[dict[str, Any]]:
    """List all enabled or disabled publications the caller can maintain."""
    return [
        publication_summary(publication)
        for publication in get_open_api_repository().list_publications(
            enabled_only=False,
        )
        if can_manage_publication(publication, request)
    ]


def publication_agent_id(publication: dict[str, Any]) -> str:
    """Resolve the concrete Agent workspace used by a publication."""
    target_type = str(publication.get("target_type") or "")
    target_id = str(publication.get("target_id") or "")
    if target_type == "agent":
        return target_id
    if target_type == "expert_team":
        team = get_expert_team_template(target_id)
        if team is None:
            raise HTTPException(status_code=404, detail="Expert team target not found")
        return str(team.leader_agent_id)
    raise HTTPException(status_code=400, detail="Unsupported Open API target type")


def publication_knowledge_service(
    publication: dict[str, Any],
) -> MindspaceService:
    """Create the isolated Mindspace service for one publication."""
    agent_id = publication_agent_id(publication)
    config = load_config()
    profiles = getattr(getattr(config, "agents", None), "profiles", {}) or {}
    profile = profiles.get(agent_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Agent target not found")
    return MindspaceService(
        global_root=Path(WORKING_DIR) / "mindspace",
        agent_workspace=Path(profile.workspace_dir).expanduser(),
        agent_id=agent_id,
        user_id=str(publication["knowledge_base_id"]),
        exclusive_personal=True,
    )
