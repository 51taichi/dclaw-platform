"""Asset-first authorization for sealed agents."""

from __future__ import annotations

from fastapi import HTTPException, Request

from .models import SealedCapability
from .registry import get_sealed_agent_registry

_PUBLIC_CAPABILITIES = {
    SealedCapability.INVOKE,
    SealedCapability.PUBLIC_METADATA,
}


def assert_sealed_capability(
    agent_id: str,
    capability: SealedCapability,
    *,
    is_sealed: bool,
) -> None:
    del agent_id
    if not is_sealed or capability in _PUBLIC_CAPABILITIES:
        return
    raise HTTPException(
        status_code=403,
        detail="Sealed agent asset access denied",
    )


def requested_agent_id(request: Request) -> str | None:
    """Resolve the server-selected agent identity without touching its assets."""
    path_params = getattr(request, "path_params", {}) or {}
    agent_id = path_params.get("agentId") or path_params.get("agent_id")
    if agent_id:
        return str(agent_id)
    state = getattr(request, "state", None)
    agent_id = getattr(state, "agent_id", None) if state is not None else None
    if agent_id:
        return str(agent_id)
    headers = getattr(request, "headers", {}) or {}
    agent_id = headers.get("X-Agent-Id") or headers.get("x-agent-id")
    if agent_id:
        return str(agent_id)
    return None


def deny_sealed_asset_access(request: Request) -> None:
    """FastAPI dependency guarding any endpoint that exposes agent assets."""
    agent_id = requested_agent_id(request)
    if not agent_id:
        return
    assert_sealed_capability(
        agent_id,
        SealedCapability.INSPECT,
        is_sealed=get_sealed_agent_registry().is_sealed(agent_id),
    )
