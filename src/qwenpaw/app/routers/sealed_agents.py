"""Administration endpoints for one-way sealed agent releases."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from ...constant import WORKING_DIR
from ...config.config import AgentProfileRef
from ...config.utils import load_config, save_config
from ..sealed_agents.models import SealedAgentRecord
from ..sealed_agents.registry import get_sealed_agent_registry
from ..sealed_agents.service import SealedAgentReleaseError, SealedAgentService
from ..sealed_agents.signing import load_trusted_signers

router = APIRouter(prefix="/sealed-agents", tags=["sealed-agents"])

_MAX_UPLOAD_BYTES = 200 * 1024 * 1024
_service: SealedAgentService | None = None


def _require_admin(request: Request) -> None:
    if getattr(request.state, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


def get_sealed_agent_service() -> SealedAgentService:
    global _service
    if _service is None:
        root = Path(WORKING_DIR) / "sealed_agents"
        _service = SealedAgentService(
            root=root,
            registry=get_sealed_agent_registry(),
            trusted_signers=load_trusted_signers(root / "trusted_signers.json"),
        )
    return _service


def _operational_dto(record: SealedAgentRecord) -> dict[str, Any]:
    active = record.active_release
    return {
        "agent_id": record.agent_id,
        "name": record.name,
        "description": record.description,
        "icon": record.icon,
        "agent_type": "sealed",
        "scope": "global",
        "enabled": record.enabled,
        "availability": (
            "available" if record.enabled and active is not None else "unavailable"
        ),
        "active_release_id": record.active_release_id,
        "version": active.version if active else None,
        "content_digest": active.content_digest if active else None,
        "signer_id": active.signer_id if active else None,
        "runtime": (
            {
                "adapter": active.runtime_adapter or "standard",
                "contract_version": active.runtime_contract_version or "1",
            }
            if active
            else None
        ),
        "runtime_validation": (
            active.runtime_validation.model_dump(mode="json")
            if active and active.runtime_validation
            else None
        ),
        "releases": [
            {
                "release_id": release.release_id,
                "version": release.version,
                "content_digest": release.content_digest,
                "signer_id": release.signer_id,
                "state": release.state,
                "installed_at": release.installed_at,
                "runtime": {
                    "adapter": release.runtime_adapter or "standard",
                    "contract_version": release.runtime_contract_version or "1",
                },
                "runtime_validation": (
                    release.runtime_validation.model_dump(mode="json")
                    if release.runtime_validation
                    else None
                ),
            }
            for release in record.releases
        ],
        "capabilities": {
            "invoke": True,
            "inspect": False,
            "edit": False,
            "clone": False,
            "export": False,
            "download": False,
            "trace": False,
        },
    }


@router.get("")
def list_sealed_agents(request: Request) -> list[dict[str, Any]]:
    _require_admin(request)
    return [_operational_dto(item) for item in get_sealed_agent_service().list_agents()]


@router.post("/releases")
async def upload_sealed_agent_release(
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    _require_admin(request)
    data = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Sealed package exceeds size limit")
    try:
        release = get_sealed_agent_service().install(data)
    except SealedAgentReleaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "release_id": release.release_id,
        "version": release.version,
        "content_digest": release.content_digest,
        "signer_id": release.signer_id,
        "state": release.state,
    }


@router.post("/{agent_id}/releases/{release_id}/activate")
async def activate_sealed_agent_release(
    agent_id: str,
    release_id: str,
    request: Request,
) -> dict[str, Any]:
    _require_admin(request)
    service = get_sealed_agent_service()
    validation = await service.validate_release_runtime(agent_id, release_id)
    if validation.status != "valid":
        raise HTTPException(
            status_code=400,
            detail="sealed agent runtime validation failed",
        )
    runtime_root = service.release_root(agent_id, release_id) / "agent"
    if not (runtime_root / "agent.json").is_file():
        raise HTTPException(
            status_code=400,
            detail="Sealed agent release is unavailable",
        )
    config = load_config()
    previous = config.agents.profiles.get(agent_id)
    config.agents.profiles[agent_id] = AgentProfileRef(
        id=agent_id,
        workspace_dir=str(runtime_root),
        enabled=True,
    )
    save_config(config)
    try:
        manager = getattr(request.app.state, "multi_agent_manager", None)
        if manager is None:
            raise SealedAgentReleaseError("sealed agent runtime is unavailable")
        if manager.is_agent_loaded(agent_id):
            loaded = await manager.reload_agent(agent_id)
        else:
            loaded = await manager.preload_agent(agent_id)
        if not loaded:
            raise SealedAgentReleaseError("sealed agent runtime validation failed")
        return _operational_dto(service.activate(agent_id, release_id))
    except Exception as exc:
        if previous is None:
            config.agents.profiles.pop(agent_id, None)
        else:
            config.agents.profiles[agent_id] = previous
        save_config(config)
        manager = getattr(request.app.state, "multi_agent_manager", None)
        if previous is not None and manager is not None:
            try:
                await manager.reload_agent(agent_id)
            except Exception:
                pass
        detail = (
            str(exc)
            if isinstance(exc, SealedAgentReleaseError)
            else "sealed agent activation failed"
        )
        raise HTTPException(status_code=400, detail=detail) from exc


@router.post("/{agent_id}/disable")
async def disable_sealed_agent(agent_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    try:
        record = get_sealed_agent_service().disable(agent_id)
        config = load_config()
        profile = config.agents.profiles.get(agent_id)
        if profile is not None:
            profile.enabled = False
            save_config(config)
        manager = getattr(request.app.state, "multi_agent_manager", None)
        if manager is not None and manager.is_agent_loaded(agent_id):
            await manager.stop_agent(agent_id)
        return _operational_dto(record)
    except SealedAgentReleaseError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{agent_id}/enable")
async def enable_sealed_agent(agent_id: str, request: Request) -> dict[str, Any]:
    _require_admin(request)
    try:
        record = get_sealed_agent_service().enable(agent_id)
        config = load_config()
        profile = config.agents.profiles.get(agent_id)
        if profile is not None:
            profile.enabled = True
            save_config(config)
        manager = getattr(request.app.state, "multi_agent_manager", None)
        if manager is not None and not manager.is_agent_loaded(agent_id):
            if not await manager.preload_agent(agent_id):
                get_sealed_agent_service().disable(agent_id)
                if profile is not None:
                    profile.enabled = False
                    save_config(config)
                raise SealedAgentReleaseError("sealed agent runtime validation failed")
        return _operational_dto(record)
    except SealedAgentReleaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
