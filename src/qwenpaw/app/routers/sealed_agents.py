"""Administration endpoints for one-way sealed agent releases."""

from __future__ import annotations

import base64
import asyncio
import json
import logging
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import ValidationError

from ...constant import WORKING_DIR
from ...config.config import AgentProfileConfig, AgentProfileRef
from ...config.utils import load_config, save_config
from ..sealed_agents.models import SealedAgentRecord
from ..sealed_agents.registry import get_sealed_agent_registry
from ..sealed_agents.runtime_workspace import runtime_workspace_root
from ..sealed_agents.service import SealedAgentReleaseError, SealedAgentService
from ..sealed_agents.signing import load_trusted_signers

router = APIRouter(prefix="/sealed-agents", tags=["sealed-agents"])
logger = logging.getLogger(__name__)

_MAX_UPLOAD_BYTES = 200 * 1024 * 1024
_service: SealedAgentService | None = None
_activation_locks: dict[str, asyncio.Lock] = {}


def _require_admin(request: Request) -> None:
    if getattr(request.state, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


def get_sealed_agent_service() -> SealedAgentService:
    global _service
    if _service is None:
        root = Path(WORKING_DIR) / "sealed_agents"
        trusted_signers = load_trusted_signers(root / "trusted_signers.json")
        _service = SealedAgentService(
            root=root,
            registry=get_sealed_agent_registry(),
            trusted_signers=trusted_signers,
        )
    return _service


def _explicit_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _active_harness_status(
    record: SealedAgentRecord,
) -> dict[str, bool | None] | None:
    active = record.active_release
    if active is None:
        return None
    from ...plugins.registry import PluginRegistry

    if not PluginRegistry().sealed_package_type_supports(
        active.package_type,
        "harness_status",
    ):
        return None
    config_path = (
        runtime_workspace_root(
            Path(WORKING_DIR) / "sealed_agents",
            record.agent_id,
            active.release_id,
        )
        / "agent.json"
    )
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        AgentProfileConfig.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValidationError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    tools = payload.get("tools")
    builtin_tools = (
        tools.get("builtin_tools") if isinstance(tools, dict) else None
    )
    skill_reader = (
        builtin_tools.get("read_agent_skill")
        if isinstance(builtin_tools, dict)
        else None
    )
    orchestration = payload.get("orchestration")
    return {
        "skill_reader_enabled": _explicit_bool(
            skill_reader.get("enabled")
            if isinstance(skill_reader, dict)
            else None,
        ),
        "agent_loop_enabled": _explicit_bool(
            orchestration.get("agent_loop_enabled")
            if isinstance(orchestration, dict)
            else None,
        ),
    }


def _operational_dto(record: SealedAgentRecord) -> dict[str, Any]:
    active = record.active_release
    active_validation = active.runtime_validation if active else None
    active_available = bool(
        record.enabled
        and active is not None
        and active_validation is not None
        and active_validation.status == "valid"
        and active_validation.adapter == "standard"
        and active_validation.contract_version == "1",
    )
    payload = {
        "agent_id": record.agent_id,
        "name": record.name,
        "description": record.description,
        "icon": record.icon,
        "avatar": record.avatar,
        "banner_image": record.banner_image,
        "agent_type": "sealed",
        "scope": "global",
        "enabled": record.enabled,
        "availability": "available" if active_available else "unavailable",
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
                    "contract_version": release.runtime_contract_version
                    or "1",
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
    harness_status = _active_harness_status(record)
    if harness_status is not None:
        payload["harness_status"] = harness_status
    return payload


def _trusted_actor(request: Request) -> tuple[str, str]:
    tenant_id = str(getattr(request.state, "tenant_id", "local") or "local")
    administrator_id = str(
        getattr(request.state, "user_id", "local-admin") or "local-admin",
    )
    return tenant_id, administrator_id


@router.get("")
def list_sealed_agents(request: Request) -> list[dict[str, Any]]:
    _require_admin(request)
    return [
        _operational_dto(item)
        for item in get_sealed_agent_service().list_agents()
    ]


async def _upload_expert_image(
    agent_id: str,
    request: Request,
    file: UploadFile,
    *,
    field: str,
    max_bytes: int,
    dimensions: tuple[int, int],
    image_format: str,
) -> dict[str, Any]:
    from PIL import Image, ImageOps, UnidentifiedImageError

    _require_admin(request)
    registry = get_sealed_agent_registry()
    record = registry.get_agent(agent_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Expert not found")
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"Image must be at most {max_bytes // (1024 * 1024)} MB",
        )
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"}:
                raise ValueError("Unsupported image format")
            if source.width * source.height > 16_000_000:
                raise ValueError("Image dimensions exceed limit")
            image = ImageOps.exif_transpose(source).convert("RGBA")
            image.thumbnail(dimensions)
            output = BytesIO()
            image.save(output, format=image_format)
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as exc:
        raise HTTPException(
            status_code=400,
            detail="Upload a valid PNG, JPEG or WebP image",
        ) from exc
    value = f"data:image/{image_format.lower()};base64," + base64.b64encode(
        output.getvalue(),
    ).decode("ascii")
    updated = registry.upsert_agent(record.model_copy(update={field: value}))
    return _operational_dto(updated)


@router.post("/{agent_id}/avatar")
async def upload_sealed_agent_avatar(
    agent_id: str,
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    return await _upload_expert_image(
        agent_id,
        request,
        file,
        field="avatar",
        max_bytes=2 * 1024 * 1024,
        dimensions=(256, 256),
        image_format="PNG",
    )


@router.post("/{agent_id}/banner")
async def upload_sealed_agent_banner(
    agent_id: str,
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    return await _upload_expert_image(
        agent_id,
        request,
        file,
        field="banner_image",
        max_bytes=5 * 1024 * 1024,
        dimensions=(2400, 1200),
        image_format="WEBP",
    )


@router.post("/releases")
async def upload_sealed_agent_release(
    request: Request,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    _require_admin(request)
    data = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail="Sealed package exceeds size limit",
        )
    try:
        service = get_sealed_agent_service()
        release = service.install(data)
    except SealedAgentReleaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    owner = next(
        (
            agent
            for agent in service.list_agents()
            if any(
                item.release_id == release.release_id
                for item in agent.releases
            )
        ),
        None,
    )
    if owner is None:
        raise HTTPException(
            status_code=500,
            detail="Installed release owner is unavailable",
        )
    return {
        "agent_id": owner.agent_id,
        "release_id": release.release_id,
        "version": release.version,
        "content_digest": release.content_digest,
        "signer_id": release.signer_id,
        "state": release.state,
        "package_type": release.package_type,
        "capability_digest": release.capability_digest,
        "declared_capabilities": [
            list(item) for item in release.declared_capabilities
        ],
    }


@router.get("/{agent_id}/releases/{release_id}/grant-preview")
def preview_extension_grant(
    agent_id: str,
    release_id: str,
    request: Request,
) -> dict[str, Any]:
    _require_admin(request)
    tenant_id, _ = _trusted_actor(request)
    try:
        preview = get_sealed_agent_service().preview_grant(
            agent_id,
            release_id,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return preview.model_dump(mode="json")


@router.post("/{agent_id}/releases/{release_id}/grant")
def accept_extension_grant(
    agent_id: str,
    release_id: str,
    request: Request,
) -> dict[str, Any]:
    _require_admin(request)
    tenant_id, administrator_id = _trusted_actor(request)
    try:
        grant = get_sealed_agent_service().grant_installation(
            agent_id,
            release_id,
            tenant_id=tenant_id,
            administrator_id=administrator_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return grant.model_dump(mode="json")


@router.post("/{agent_id}/releases/{release_id}/grant-cancel")
def cancel_extension_grant(
    agent_id: str,
    release_id: str,
    request: Request,
) -> dict[str, bool]:
    _require_admin(request)
    tenant_id, _ = _trusted_actor(request)
    try:
        get_sealed_agent_service().cancel_grant_preview(
            agent_id,
            release_id,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"cancelled": True}


# Compatibility names for callers that predate generic sealed package types.
preview_super_expert_grant = preview_extension_grant
accept_super_expert_grant = accept_extension_grant
cancel_super_expert_grant = cancel_extension_grant


@router.post("/{agent_id}/releases/{release_id}/activate")
async def activate_sealed_agent_release(
    agent_id: str,
    release_id: str,
    request: Request,
) -> dict[str, Any]:
    _require_admin(request)
    activation_lock = _activation_locks.setdefault(agent_id, asyncio.Lock())
    async with activation_lock:
        return await _activate_sealed_agent_release_locked(
            agent_id,
            release_id,
            request,
        )


async def _activate_sealed_agent_release_locked(
    agent_id: str,
    release_id: str,
    request: Request,
) -> dict[str, Any]:
    """Activate one release while its Agent lifecycle lock is held."""
    service = get_sealed_agent_service()
    validation = await service.validate_release_runtime(agent_id, release_id)
    if validation.status != "valid":
        raise HTTPException(
            status_code=400,
            detail="sealed agent runtime validation failed",
        )
    try:
        runtime_root = service.prepare_runtime_workspace(agent_id, release_id)
    except OSError as exc:
        raise HTTPException(
            status_code=400,
            detail="Sealed agent runtime workspace is unavailable",
        ) from exc
    if not (runtime_root / "agent.json").is_file():
        raise HTTPException(
            status_code=400,
            detail="Sealed agent release is unavailable",
        )
    config = load_config()
    previous = config.agents.profiles.get(agent_id)
    previous_record = service.get_agent(agent_id)
    activated_record = None
    try:
        tenant_id, _ = _trusted_actor(request)
        activated_record = service.activate(
            agent_id,
            release_id,
            tenant_id=tenant_id,
        )
        config.agents.profiles[agent_id] = AgentProfileRef(
            id=agent_id,
            workspace_dir=str(runtime_root),
            enabled=True,
        )
        save_config(config)
        manager = getattr(request.app.state, "multi_agent_manager", None)
        if manager is None:
            raise SealedAgentReleaseError(
                "sealed agent runtime is unavailable",
            )
        if manager.is_agent_loaded(agent_id):
            loaded = await manager.reload_agent(agent_id)
        else:
            loaded = await manager.preload_agent(agent_id)
        if not loaded:
            raise SealedAgentReleaseError(
                "sealed agent runtime validation failed",
            )
        service.notify_release_committed(agent_id, release_id)
        return _operational_dto(service.get_agent(agent_id))
    except Exception as exc:
        if activated_record is not None and previous_record is not None:
            try:
                service.restore_agent_record(previous_record)
            except Exception:
                logger.exception(
                    "Failed to restore sealed Agent registry after activation",
                )
        if previous is None:
            config.agents.profiles.pop(agent_id, None)
        else:
            config.agents.profiles[agent_id] = previous
        save_config(config)
        manager = getattr(request.app.state, "multi_agent_manager", None)
        if manager is not None:
            try:
                if previous is None and manager.is_agent_loaded(agent_id):
                    await manager.stop_agent(agent_id)
                elif previous is not None:
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
async def disable_sealed_agent(
    agent_id: str,
    request: Request,
) -> dict[str, Any]:
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
async def enable_sealed_agent(
    agent_id: str,
    request: Request,
) -> dict[str, Any]:
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
                raise SealedAgentReleaseError(
                    "sealed agent runtime validation failed",
                )
        return _operational_dto(record)
    except SealedAgentReleaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{agent_id}")
async def delete_sealed_agent(
    agent_id: str,
    request: Request,
) -> dict[str, Any]:
    _require_admin(request)
    async with _activation_locks.setdefault(agent_id, asyncio.Lock()):
        try:
            get_sealed_agent_service().delete(
                agent_id,
                actor=str(getattr(request.state, "user_id", "admin")),
            )
        except SealedAgentReleaseError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        config = load_config()
        config.agents.profiles.pop(agent_id, None)
        save_config(config)
        manager = getattr(request.app.state, "multi_agent_manager", None)
        if manager is not None and manager.is_agent_loaded(agent_id):
            await manager.stop_agent(agent_id)
        logger.info(
            "Deleted sealed agent %s (metadata and releases retained)",
            agent_id,
        )
        return {"agent_id": agent_id, "deleted": True}
