# -*- coding: utf-8 -*-
"""Workspace and skill-pool APIs."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import shutil
import tempfile
import threading
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from agentscope_runtime.engine.schemas.exception import (
    AppBaseException,
)

from ...agents.skill_system.hub import (
    SkillImportCancelled,
    search_hub_skills,
    import_pool_skill_from_hub,
    install_skill_from_hub,
)
from ...agents.skill_system import (
    SkillConflictError,
    SkillPoolService,
    SkillService,
)
from ...agents.skill_system.models import SkillInfo
from ...agents.skill_system.registry import (
    BUILTIN_SKILL_LANGUAGES,
    get_pool_builtin_sync_status,
    get_pool_builtin_update_notice,
    import_builtin_skills,
    list_builtin_import_candidates,
    list_workspaces,
    reconcile_pool_manifest,
    reconcile_workspace_manifest,
    update_single_builtin,
)
from ...agents.skill_system.store import (
    default_pool_manifest,
    default_workspace_manifest,
    get_pool_skill_manifest_path,
    get_skill_mtime,
    get_skill_pool_dir,
    get_workspace_skill_manifest_path,
    get_workspace_skills_dir,
    mutate_json,
    normalize_skill_manifest_entry,
    read_skill_from_dir,
    read_skill_manifest,
    read_skill_pool_manifest,
    suggest_conflict_name,
)
from ...security.skill_scanner import SkillScanError
from ..chat_access import current_user_id, is_admin_request
from ..runtime.event_bus import RuntimeEvent, get_runtime_event_bus
from ..sealed_agents.registry import get_sealed_agent_registry
from ..utils import schedule_agent_reload
from ..task_limits import get_task_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skills", tags=["skills"])

MAX_TAGS = 8
MAX_TAG_LENGTH = 16
PRIVATE_VISIBILITY = "private"
PUBLIC_VISIBILITY = "public"


def _skill_visibility(entry: dict[str, Any]) -> str:
    return str(entry.get("visibility", "") or "").strip().lower()


def _skill_owner_user_id(entry: dict[str, Any]) -> str:
    return str(entry.get("owner_user_id", "") or "").strip()


def _skill_client_visible(entry: dict[str, Any]) -> bool:
    return entry.get("client_visible", True) is not False


def _merged_client_visible(
    entry: dict[str, Any],
    pool_entry: dict[str, Any] | None = None,
) -> bool:
    return _skill_client_visible(entry) and _skill_client_visible(
        pool_entry or {},
    )


def _is_private_skill_entry(entry: dict[str, Any]) -> bool:
    return _skill_visibility(entry) == PRIVATE_VISIBILITY


def _can_access_skill_entry(
    request: Request | None,
    entry: dict[str, Any],
) -> bool:
    if not _is_private_skill_entry(entry):
        return True
    if request is None:
        return True
    if is_admin_request(request):
        return True
    owner_user_id = _skill_owner_user_id(entry)
    return bool(owner_user_id) and owner_user_id == current_user_id(request)


def _can_show_skill_entry(
    request: Request | None,
    entry: dict[str, Any],
    *,
    include_hidden: bool = False,
) -> bool:
    if not _can_access_skill_entry(request, entry):
        return False
    can_include_hidden = (
        include_hidden and request is not None and is_admin_request(request)
    )
    return can_include_hidden or _skill_client_visible(entry)


def _normalize_pool_visibility(
    visibility: str | None,
    *,
    fallback: str = PUBLIC_VISIBILITY,
) -> str:
    normalized = str(visibility or "").strip().lower()
    if normalized in {PUBLIC_VISIBILITY, PRIVATE_VISIBILITY}:
        return normalized
    return fallback


def _normalize_manifest_entry(raw_entry: Any) -> dict[str, Any]:
    if not isinstance(raw_entry, dict):
        return {}
    return normalize_skill_manifest_entry(raw_entry)


def _pool_manifest_entry(skill_name: str) -> dict[str, Any] | None:
    manifest = read_skill_pool_manifest()
    raw_entry = manifest.get("skills", {}).get(skill_name)
    if raw_entry is None:
        return None
    return _normalize_manifest_entry(raw_entry)


def _ensure_pool_skill_can_be_private(
    skill_name: str,
    requested_visibility: str | None,
) -> None:
    if requested_visibility is None:
        return
    entry = _pool_manifest_entry(skill_name)
    if entry is None:
        return
    current_visibility = _normalize_pool_visibility(
        str(entry.get("visibility", "") or PUBLIC_VISIBILITY),
    )
    next_visibility = _normalize_pool_visibility(
        requested_visibility,
        fallback=current_visibility,
    )
    if (
        next_visibility == PRIVATE_VISIBILITY
        and current_visibility != PRIVATE_VISIBILITY
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Private promotion is irreversible; public or default skills "
                "cannot be changed back to private."
            ),
        )


def _require_pool_skill_access(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    entry = _pool_manifest_entry(skill_name)
    if (
        entry is None
        or not _can_access_skill_entry(request, entry)
        or (not _skill_client_visible(entry) and not is_admin_request(request))
    ):
        raise HTTPException(status_code=404, detail="Pool skill not found")
    return entry


def _workspace_skill_entry_for_access(
    workspace_dir: Path,
    skill_name: str,
) -> dict[str, Any] | None:
    manifest = read_skill_manifest(workspace_dir)
    raw_entry = manifest.get("skills", {}).get(skill_name)
    if raw_entry is None:
        return None
    entry = _normalize_manifest_entry(raw_entry)
    pool_entry = _pool_manifest_entry(skill_name) or {}
    visibility = str(
        entry.get("visibility") or pool_entry.get("visibility") or "",
    ).strip()
    owner_user_id = str(
        entry.get("owner_user_id")
        or pool_entry.get("owner_user_id")
        or "",
    ).strip()
    if visibility:
        entry["visibility"] = visibility
    if owner_user_id:
        entry["owner_user_id"] = owner_user_id
    return entry


def _require_workspace_skill_access(
    request: Request,
    workspace_dir: Path,
    skill_name: str,
) -> dict[str, Any]:
    entry = _workspace_skill_entry_for_access(workspace_dir, skill_name)
    pool_entry = _pool_manifest_entry(skill_name) or {}
    if (
        entry is None
        or not _can_access_skill_entry(request, entry)
        or (
            not _merged_client_visible(entry, pool_entry)
            and not is_admin_request(request)
        )
    ):
        raise HTTPException(status_code=404, detail="Skill not found")
    return entry


def _scan_error_payload(exc: SkillScanError) -> dict[str, Any]:
    """Normalize scanner exceptions into a stable API payload.

    Example response body:
        {
            "type": "security_scan_failed",
            "skill_name": "blocked_skill",
            "max_severity": "high",
            "findings": [...]
        }
    """
    result = exc.result
    return {
        "type": "security_scan_failed",
        "detail": str(exc),
        "skill_name": result.skill_name,
        "max_severity": result.max_severity.value,
        "findings": [
            {
                "severity": f.severity.value,
                "title": f.title,
                "description": f.description,
                "file_path": f.file_path,
                "line_number": f.line_number,
                "rule_id": f.rule_id,
            }
            for f in result.findings
        ],
    }


def _scan_error_response(exc: SkillScanError) -> JSONResponse:
    """Build a 422 JSON response for skill scan failures.

    Returns a JSONResponse so callers receive structured scan
    details rather than a bare HTTP error.
    """
    return JSONResponse(
        status_code=422,
        content=_scan_error_payload(exc),
    )


def _apply_pool_skill_governance(
    skill_name: str,
    *,
    visibility: str | None = None,
    client_visible: bool | None = None,
    owner_user_id: str = "",
) -> bool:
    """Persist pool-level publishing flags without touching skill content."""

    def _update(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if entry is None:
            return False

        if visibility is not None:
            current_visibility = _normalize_pool_visibility(
                str(entry.get("visibility", "") or PUBLIC_VISIBILITY),
            )
            fallback = _normalize_pool_visibility(
                str(entry.get("visibility", "") or PUBLIC_VISIBILITY),
            )
            next_visibility = _normalize_pool_visibility(
                visibility,
                fallback=fallback,
            )
            config = entry.get("config") or {}
            if (
                next_visibility == PRIVATE_VISIBILITY
                and current_visibility != PRIVATE_VISIBILITY
                and not (
                    isinstance(config, dict)
                    and config.get("is_default") is True
                )
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Private promotion is irreversible; public or default "
                        "skills cannot be changed back to private."
                    ),
                )
            entry["visibility"] = next_visibility
            if next_visibility == PRIVATE_VISIBILITY:
                existing_owner = _skill_owner_user_id(entry)
                if owner_user_id or existing_owner:
                    entry["owner_user_id"] = existing_owner or owner_user_id
            else:
                entry.pop("owner_user_id", None)

        if client_visible is not None:
            entry["client_visible"] = bool(client_visible)

        config = entry.get("config") or {}
        if isinstance(config, dict) and config.get("is_default") is True:
            entry["visibility"] = PUBLIC_VISIBILITY
            entry.pop("owner_user_id", None)
        return True

    return mutate_json(
        get_pool_skill_manifest_path(),
        default_pool_manifest(),
        _update,
    )


def _sync_default_skill_to_all_workspaces(skill_name: str) -> None:
    service = SkillPoolService()
    for workspace in list_workspaces():
        workspace_dir_text = str(workspace.get("workspace_dir") or "").strip()
        if not workspace_dir_text:
            continue
        workspace_dir = Path(workspace_dir_text)
        try:
            service.download_to_workspace(
                skill_name=skill_name,
                workspace_dir=workspace_dir,
                overwrite=True,
            )
        except Exception:
            logger.warning(
                "Failed to install default skill '%s' into %s",
                skill_name,
                workspace_dir,
                exc_info=True,
            )


class SkillSpec(SkillInfo):
    enabled: bool = False
    channels: list[str] = Field(default_factory=lambda: ["all"])
    tags: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    last_updated: str = ""
    visibility: str = ""
    owner_user_id: str = ""
    client_visible: bool = True


class PoolSkillSpec(SkillInfo):
    protected: bool = False
    commit_text: str = ""
    sync_status: str = ""
    latest_version_text: str = ""
    builtin_language: str = ""
    available_builtin_languages: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    last_updated: str = ""
    visibility: str = ""
    owner_user_id: str = ""
    client_visible: bool = True


class WorkspaceSkillSummary(BaseModel):
    agent_id: str
    agent_name: str = ""
    workspace_dir: str
    skills: list[SkillSpec] = Field(default_factory=list)


class HubSkillSpec(BaseModel):
    slug: str
    name: str
    description: str = ""
    version: str = ""
    source_url: str = ""


class BuiltinImportSpec(BaseModel):
    name: str
    description: str = ""
    version_text: str = ""
    current_version_text: str = ""
    current_source: str = ""
    current_language: str = ""
    available_languages: list[str] = Field(default_factory=list)
    languages: dict[str, dict[str, Any]] = Field(default_factory=dict)
    status: str = ""


class BuiltinRemovedSpec(BaseModel):
    name: str
    description: str = ""
    current_version_text: str = ""
    current_source: str = ""


class BuiltinUpdateNotice(BaseModel):
    fingerprint: str = ""
    has_updates: bool = False
    total_changes: int = 0
    actionable_skill_names: list[str] = Field(default_factory=list)
    added: list[BuiltinImportSpec] = Field(default_factory=list)
    missing: list[BuiltinImportSpec] = Field(default_factory=list)
    updated: list[BuiltinImportSpec] = Field(default_factory=list)
    removed: list[BuiltinRemovedSpec] = Field(default_factory=list)


class BuiltinImportSelection(BaseModel):
    skill_name: str
    language: str = ""


class ImportBuiltinRequest(BaseModel):
    skill_names: list[str] = Field(
        default_factory=list,
    )  # Deprecated: use imports
    imports: list[BuiltinImportSelection] = Field(default_factory=list)
    overwrite_conflicts: bool = False


class UpdateBuiltinRequest(BaseModel):
    language: str = ""


class CreateSkillRequest(BaseModel):
    name: str
    content: str
    references: dict[str, Any] | None = None
    scripts: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    enable: bool = True
    visibility: str = ""
    client_visible: bool = True


class UploadToPoolRequest(BaseModel):
    workspace_id: str
    skill_name: str
    overwrite: bool = False
    preview_only: bool = False


class PoolDownloadTarget(BaseModel):
    workspace_id: str


class DownloadFromPoolRequest(BaseModel):
    skill_name: str
    targets: list[PoolDownloadTarget] = Field(default_factory=list)
    all_workspaces: bool = False
    overwrite: bool = False
    preview_only: bool = False


class SkillConfigRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class PoolSkillGovernanceRequest(BaseModel):
    visibility: str | None = None
    client_visible: bool | None = None


class SavePoolSkillRequest(BaseModel):
    name: str
    content: str
    source_name: str | None = None
    config: dict[str, Any] | None = None
    visibility: str | None = None
    client_visible: bool | None = None
    overwrite: bool = False


class SaveSkillRequest(BaseModel):
    name: str
    content: str
    source_name: str | None = None
    config: dict[str, Any] | None = None
    overwrite: bool = False


class HubInstallRequest(BaseModel):
    bundle_url: str = Field(..., description="Skill URL")
    version: str = Field(default="", description="Optional version tag")
    enable: bool = Field(default=True, description="Enable after import")
    target_name: str = Field(default="", description="Optional renamed skill")


class HubInstallTaskStatus(str, Enum):
    PENDING = "pending"
    IMPORTING = "importing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HubInstallTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    bundle_url: str
    version: str = ""
    enable: bool = True
    status: HubInstallTaskStatus = HubInstallTaskStatus.PENDING
    error: str | None = None
    result: dict[str, Any] | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


_hub_install_tasks: dict[str, HubInstallTask] = {}
_hub_install_runtime_tasks: dict[str, asyncio.Task] = {}
_hub_install_cancel_events: dict[str, threading.Event] = {}
_hub_install_lock = asyncio.Lock()

_ALLOWED_ZIP_TYPES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
}
_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB


async def _workspace_dir_for_agent(agent_id: str, request: Request) -> Path:
    manager = request.app.state.multi_agent_manager
    user_id = getattr(request.state, "user_id", "default")
    try:
        workspace = await manager.get_agent(agent_id, user_id=user_id)
        return Path(workspace.workspace_dir)
    except Exception as exc:
        raise ValueError(f"Workspace for agent '{agent_id}' not found: {exc}")


def _snapshot_workspace_skill(
    workspace_dir: Path,
    skill_name: str,
) -> dict[str, Any]:
    manifest = read_skill_manifest(workspace_dir)
    entry = manifest.get("skills", {}).get(skill_name)
    skill_dir = workspace_dir / "skills" / skill_name
    backup_dir: Path | None = None
    if skill_dir.exists():
        backup_root = Path(
            tempfile.mkdtemp(prefix=f"qwenpaw_skill_rollback_{skill_name}_"),
        )
        backup_dir = backup_root / skill_name
        shutil.copytree(skill_dir, backup_dir)
    return {
        "workspace_dir": workspace_dir,
        "skill_name": skill_name,
        "entry": copy.deepcopy(entry) if entry is not None else None,
        "backup_dir": backup_dir,
    }


def _restore_workspace_skill(snapshot: dict[str, Any]) -> None:
    workspace_dir = Path(snapshot["workspace_dir"])
    skill_name = str(snapshot["skill_name"])
    skill_dir = workspace_dir / "skills" / skill_name
    backup_dir = snapshot.get("backup_dir")
    entry = snapshot.get("entry")

    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    if backup_dir is not None and Path(backup_dir).exists():
        shutil.copytree(Path(backup_dir), skill_dir)

    def _restore(payload: dict[str, Any]) -> None:
        payload.setdefault("skills", {})
        if entry is None:
            payload["skills"].pop(skill_name, None)
            return
        payload["skills"][skill_name] = copy.deepcopy(entry)

    mutate_json(
        get_workspace_skill_manifest_path(workspace_dir),
        default_workspace_manifest(),
        _restore,
    )
    reconcile_workspace_manifest(workspace_dir)
    if backup_dir is not None:
        shutil.rmtree(Path(backup_dir).parent, ignore_errors=True)


async def _request_workspace_dir(request: Request) -> Path:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    return Path(workspace.workspace_dir)


async def _hub_task_set_status(
    task_id: str,
    status: HubInstallTaskStatus,
    *,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    event_task: HubInstallTask | None = None
    async with _hub_install_lock:
        task = _hub_install_tasks.get(task_id)
        if task is None:
            return
        task.status = status
        task.updated_at = time.time()
        if error is not None:
            task.error = error
        if result is not None:
            task.result = result
        event_task = task.model_copy(deep=True)
    await _publish_hub_install_event(event_task)


async def _publish_hub_install_event(task: HubInstallTask) -> None:
    status = task.status.value if isinstance(task.status, HubInstallTaskStatus) else str(task.status)
    try:
        await get_runtime_event_bus().publish(
            RuntimeEvent(
                type="skill.install.updated",
                scope="skill",
                job_id=task.task_id,
                status=status,
                message=f"Skill install {status}",
                payload=task.model_dump(mode="json"),
            ),
        )
    except Exception as exc:  # pragma: no cover - diagnostics only
        logger.debug("Failed to publish skill install runtime event: %s", exc)


async def _hub_task_get(task_id: str) -> HubInstallTask | None:
    async with _hub_install_lock:
        return _hub_install_tasks.get(task_id)


async def _hub_task_register_runtime(task_id: str, task: asyncio.Task) -> None:
    async with _hub_install_lock:
        _hub_install_runtime_tasks[task_id] = task


async def _hub_task_pop_runtime(task_id: str) -> asyncio.Task | None:
    async with _hub_install_lock:
        return _hub_install_runtime_tasks.pop(task_id, None)


async def _read_validated_zip_upload(file: UploadFile) -> bytes:
    if file.content_type and file.content_type not in _ALLOWED_ZIP_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Expected a zip file, "
                f"got content-type: {file.content_type}"
            ),
        )

    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File too large ({len(data) // (1024 * 1024)} MB). "
                f"Maximum is {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            ),
        )
    return data


def _cleanup_imported_skill(workspace_dir: Path, skill_name: str) -> None:
    if not skill_name:
        return
    try:
        skill_service = SkillService(workspace_dir)
        skill_service.disable_skill(skill_name)
        skill_service.delete_skill(skill_name)
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Cleanup after cancelled import failed for '%s': %s",
            skill_name,
            exc,
        )


async def _run_hub_install_task(
    *,
    task_id: str,
    workspace_dir: Path,
    body: HubInstallRequest,
    cancel_event: threading.Event,
    permit: Any | None = None,
) -> None:
    await _hub_task_set_status(task_id, HubInstallTaskStatus.IMPORTING)
    imported_skill_name: str | None = None
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: install_skill_from_hub(
                workspace_dir=workspace_dir,
                bundle_url=body.bundle_url,
                version=body.version,
                enable=body.enable,
                target_name=body.target_name,
                cancel_checker=cancel_event.is_set,
            ),
        )
        imported_skill_name = result.name
        if cancel_event.is_set():
            _cleanup_imported_skill(workspace_dir, result.name)
            await _hub_task_set_status(
                task_id,
                HubInstallTaskStatus.CANCELLED,
                result={
                    "installed": False,
                    "name": result.name,
                    "enabled": False,
                    "source_url": result.source_url,
                },
            )
            return
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.COMPLETED,
            result={
                "installed": True,
                "name": result.name,
                "enabled": result.enabled,
                "source_url": result.source_url,
            },
        )
    except SkillImportCancelled:
        if imported_skill_name:
            _cleanup_imported_skill(workspace_dir, imported_skill_name)
        await _hub_task_set_status(task_id, HubInstallTaskStatus.CANCELLED)
    except SkillScanError as exc:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(exc),
            result=_scan_error_payload(exc),
        )
    except (ValueError, AppBaseException) as exc:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(exc),
        )
    except SkillConflictError as exc:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(exc),
            result=exc.detail,
        )
    except RuntimeError as exc:
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=str(exc),
        )
    except Exception as exc:  # pragma: no cover
        await _hub_task_set_status(
            task_id,
            HubInstallTaskStatus.FAILED,
            error=f"Skill hub import failed: {exc}",
        )
    finally:
        if permit is not None:
            await permit.release()
        await _hub_task_pop_runtime(task_id)


def _build_workspace_skill_specs(
    workspace_dir: Path,
    request: Request | None = None,
) -> list[SkillSpec]:
    manifest = read_skill_manifest(workspace_dir)
    entries = manifest.get("skills", {})
    pool_entries = read_skill_pool_manifest().get("skills", {})
    skill_root = get_workspace_skills_dir(workspace_dir)
    specs: list[SkillSpec] = []
    for skill_name, raw_entry in sorted(entries.items()):
        entry = normalize_skill_manifest_entry(raw_entry)
        if raw_entry not in (None, entry):
            logger.warning(
                "Skipping malformed workspace skill entry '%s' in manifest",
                skill_name,
            )
        try:
            pool_entry = _normalize_manifest_entry(pool_entries.get(skill_name))
            visibility = str(
                entry.get("visibility")
                or pool_entry.get("visibility")
                or "",
            ).strip()
            owner_user_id = str(
                entry.get("owner_user_id")
                or pool_entry.get("owner_user_id")
                or "",
            ).strip()
            client_visible = _merged_client_visible(entry, pool_entry)
            access_entry = dict(entry)
            if visibility:
                access_entry["visibility"] = visibility
            if owner_user_id:
                access_entry["owner_user_id"] = owner_user_id
            access_entry["client_visible"] = client_visible
            if not _can_show_skill_entry(request, access_entry):
                continue
            source = entry.get("source", "customized")
            skill_dir = skill_root / skill_name
            skill = read_skill_from_dir(skill_dir, source)
            if skill is None:
                continue
            dump = skill.model_dump()
            dump["tags"] = entry.get("tags") or []
            specs.append(
                SkillSpec(
                    **dump,
                    enabled=entry.get("enabled", False),
                    channels=entry.get("channels") or ["all"],
                    config=entry.get("config") or {},
                    last_updated=get_skill_mtime(skill_dir),
                    visibility=visibility,
                    owner_user_id=owner_user_id,
                    client_visible=client_visible,
                ),
            )
        except Exception:
            logger.warning(
                "Skipping workspace skill '%s': failed to build spec",
                skill_name,
                exc_info=True,
            )
    return specs


def _build_pool_skill_specs(
    request: Request | None = None,
    *,
    include_hidden: bool = False,
) -> list[PoolSkillSpec]:
    manifest = read_skill_pool_manifest()
    entries = manifest.get("skills", {})
    pool_dir = get_skill_pool_dir()
    sync_info = get_pool_builtin_sync_status(pool_skills=entries)
    specs: list[PoolSkillSpec] = []
    for skill_name, raw_entry in sorted(entries.items()):
        entry = normalize_skill_manifest_entry(raw_entry)
        if raw_entry not in (None, entry):
            logger.warning(
                "Skipping malformed pool skill entry '%s' in manifest",
                skill_name,
            )
        try:
            if not _can_show_skill_entry(
                request,
                entry,
                include_hidden=include_hidden,
            ):
                continue
            source = entry.get("source", "customized")
            skill_dir = pool_dir / skill_name
            skill = read_skill_from_dir(skill_dir, source)
            if skill is None:
                continue
            info = sync_info.get(skill_name, {})
            dump = skill.model_dump(exclude={"version_text"})
            dump["tags"] = entry.get("tags") or []
            specs.append(
                PoolSkillSpec(
                    **dump,
                    protected=bool(entry.get("protected", False)),
                    version_text=str(entry.get("version_text", "") or ""),
                    commit_text=str(entry.get("commit_text", "") or ""),
                    sync_status=str(info.get("sync_status", "") or ""),
                    latest_version_text=str(
                        info.get("latest_version_text", "") or "",
                    ),
                    builtin_language=str(
                        entry.get("builtin_language", "") or "",
                    ),
                    available_builtin_languages=[
                        str(language)
                        for language in (
                            info.get("available_languages")
                            or entry.get("available_builtin_languages")
                            or []
                        )
                        if str(language)
                    ],
                    config=entry.get("config") or {},
                    last_updated=get_skill_mtime(skill_dir),
                    visibility=str(
                        entry.get("visibility", "") or "",
                    ),
                    owner_user_id=str(
                        entry.get("owner_user_id", "") or "",
                    ),
                    client_visible=_skill_client_visible(entry),
                ),
            )
        except Exception:
            logger.warning(
                "Skipping pool skill '%s': failed to build spec",
                skill_name,
                exc_info=True,
            )
    return specs


@router.get("")
async def list_skills(request: Request) -> list[SkillSpec]:
    workspace_dir = await _request_workspace_dir(request)
    return _build_workspace_skill_specs(workspace_dir, request)


@router.post("/refresh")
async def refresh_skills(request: Request) -> list[SkillSpec]:
    """Force reconcile and return updated workspace skill list."""
    workspace_dir = await _request_workspace_dir(request)
    reconcile_workspace_manifest(workspace_dir)
    return _build_workspace_skill_specs(workspace_dir, request)


@router.get("/hub/search")
async def search_hub(
    q: str = "",
    limit: int = 20,
) -> list[HubSkillSpec]:
    results = search_hub_skills(q, limit=limit)
    return [
        HubSkillSpec(
            slug=item.slug,
            name=item.name,
            description=item.description,
            version=item.version,
            source_url=item.source_url,
        )
        for item in results
    ]


@router.get("/workspaces")
async def list_workspace_skill_sources(
    request: Request,
) -> list[WorkspaceSkillSummary]:
    summaries: list[WorkspaceSkillSummary] = []
    workspaces = list_workspaces()
    sealed_registry = get_sealed_agent_registry()
    for workspace in workspaces:
        if sealed_registry.is_sealed(workspace["agent_id"]):
            continue
        workspace_dir = Path(workspace["workspace_dir"])
        summaries.append(
            WorkspaceSkillSummary(
                agent_id=workspace["agent_id"],
                agent_name=workspace.get("agent_name", ""),
                workspace_dir=str(workspace_dir),
                skills=_build_workspace_skill_specs(workspace_dir, request),
            ),
        )
    return summaries


@router.post("/hub/install/start", response_model=HubInstallTask)
async def start_install_from_hub(
    request_body: HubInstallRequest,
    request: Request,
) -> HubInstallTask:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    user_id = str(getattr(request.state, "user_id", None) or "default")
    permit = await get_task_limiter(request.app).try_acquire(
        agent_id=str(getattr(workspace, "agent_id", "") or "default"),
        user_id=user_id,
    )
    if permit is None:
        raise HTTPException(
            status_code=429,
            detail=(
                "Too many running tasks. Please wait for an existing task "
                "to finish and try again."
            ),
        )
    task = HubInstallTask(
        bundle_url=request_body.bundle_url,
        version=request_body.version,
        enable=request_body.enable,
    )
    cancel_event = threading.Event()
    async with _hub_install_lock:
        _hub_install_tasks[task.task_id] = task
        _hub_install_cancel_events[task.task_id] = cancel_event

    runtime_task = asyncio.create_task(
        _run_hub_install_task(
            task_id=task.task_id,
            workspace_dir=workspace_dir,
            body=request_body,
            cancel_event=cancel_event,
            permit=permit,
        ),
        name=f"skill-hub-install-{task.task_id}",
    )
    await _hub_task_register_runtime(task.task_id, runtime_task)
    return task


@router.get("/hub/install/status/{task_id}", response_model=HubInstallTask)
async def get_hub_install_status(task_id: str) -> HubInstallTask:
    task = await _hub_task_get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="install task not found")
    return task


@router.post("/hub/install/cancel/{task_id}")
async def cancel_hub_install(task_id: str) -> dict[str, Any]:
    async with _hub_install_lock:
        task = _hub_install_tasks.get(task_id)
        if task is None:
            raise HTTPException(
                status_code=404,
                detail="install task not found",
            )
        if task.status in (
            HubInstallTaskStatus.COMPLETED,
            HubInstallTaskStatus.FAILED,
            HubInstallTaskStatus.CANCELLED,
        ):
            return {"task_id": task_id, "status": task.status.value}
        cancel_event = _hub_install_cancel_events.get(task_id)
        if cancel_event is not None:
            cancel_event.set()
        task.status = HubInstallTaskStatus.CANCELLED
        task.updated_at = time.time()
    return {"task_id": task_id, "status": "cancelled"}


@router.get("/pool")
async def list_pool_skills(
    request: Request,
    include_hidden: bool = False,
) -> list[PoolSkillSpec]:
    return _build_pool_skill_specs(request, include_hidden=include_hidden)


@router.post("/pool/refresh")
async def refresh_pool_skills(
    request: Request,
    include_hidden: bool = False,
) -> list[PoolSkillSpec]:
    """Force reconcile and return updated pool skill list."""
    reconcile_pool_manifest()
    return _build_pool_skill_specs(request, include_hidden=include_hidden)


@router.get("/pool/builtin-sources")
async def list_pool_builtin_sources() -> list[BuiltinImportSpec]:
    return [
        BuiltinImportSpec(**item) for item in list_builtin_import_candidates()
    ]


@router.get("/pool/builtin-notice")
async def get_pool_builtin_notice() -> BuiltinUpdateNotice:
    notice = get_pool_builtin_update_notice()
    return BuiltinUpdateNotice(
        fingerprint=str(notice.get("fingerprint", "") or ""),
        has_updates=bool(notice.get("has_updates", False)),
        total_changes=int(notice.get("total_changes", 0) or 0),
        actionable_skill_names=[
            str(name)
            for name in notice.get("actionable_skill_names", [])
            if str(name)
        ],
        added=[BuiltinImportSpec(**item) for item in notice.get("added", [])],
        missing=[
            BuiltinImportSpec(**item) for item in notice.get("missing", [])
        ],
        updated=[
            BuiltinImportSpec(**item) for item in notice.get("updated", [])
        ],
        removed=[
            BuiltinRemovedSpec(**item) for item in notice.get("removed", [])
        ],
    )


@router.post("")
async def create_skill(
    request: Request,
    body: CreateSkillRequest,
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    visibility = PRIVATE_VISIBILITY
    owner_user_id = current_user_id(request)
    try:
        created = SkillService(workspace_dir).create_skill(
            name=body.name,
            content=body.content,
            references=body.references,
            scripts=body.scripts,
            config=body.config,
            enable=body.enable,
            visibility=visibility,
            owner_user_id=owner_user_id,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not created:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "conflict",
                "suggested_name": suggest_conflict_name(body.name),
            },
        )
    if body.enable:
        schedule_agent_reload(request, workspace.agent_id)
    return {"created": True, "name": created}


@router.post("/upload")
async def upload_skill_zip(
    request: Request,
    file: UploadFile = File(...),
    enable: bool = True,
    target_name: str = "",
    rename_map: str = "",
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    data = await _read_validated_zip_upload(file)
    parsed_rename: dict[str, str] | None = None
    if rename_map.strip():
        try:
            parsed_rename = json.loads(rename_map)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="rename_map must be valid JSON",
            ) from exc
        if not isinstance(parsed_rename, dict):
            raise HTTPException(
                status_code=400,
                detail="rename_map must be a JSON object",
            )
    try:
        result = await asyncio.to_thread(
            SkillService(workspace_dir).import_from_zip,
            data=data,
            enable=enable,
            target_name=target_name,
            rename_map=parsed_rename,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("conflicts"):
        raise HTTPException(status_code=409, detail=result)
    if enable and result.get("count", 0) > 0:
        schedule_agent_reload(request, workspace.agent_id)
    return result


@router.post("/pool/create")
async def create_pool_skill(
    request: Request,
    body: CreateSkillRequest,
) -> dict[str, Any]:
    requested_visibility = str(body.visibility or "").strip()
    visibility = (
        _normalize_pool_visibility(requested_visibility)
        if is_admin_request(request)
        else PRIVATE_VISIBILITY
    )
    owner_user_id = (
        current_user_id(request)
        if visibility == PRIVATE_VISIBILITY
        else ""
    )
    try:
        created = SkillPoolService().create_skill(
            name=body.name,
            content=body.content,
            references=body.references,
            scripts=body.scripts,
            config=body.config,
            visibility=visibility,
            owner_user_id=owner_user_id,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not created:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "conflict",
                "suggested_name": suggest_conflict_name(body.name),
            },
        )
    _apply_pool_skill_governance(
        created,
        visibility=visibility,
        client_visible=body.client_visible,
        owner_user_id=owner_user_id,
    )
    if (body.config or {}).get("is_default") is True:
        _sync_default_skill_to_all_workspaces(created)
    return {"created": True, "name": created}


@router.put("/pool/save")
async def save_pool_skill(
    request: Request,
    body: SavePoolSkillRequest,
) -> dict[str, Any]:
    """Save one pool skill.

    ``overwrite`` only matters when the save would replace an existing target
    skill during rename/save-as.
    """
    source_name = body.source_name or body.name
    _require_pool_skill_access(request, source_name)
    requested_visibility = (
        PUBLIC_VISIBILITY
        if (body.config or {}).get("is_default") is True
        else body.visibility
    )
    _ensure_pool_skill_can_be_private(source_name, requested_visibility)
    if body.source_name and body.name != body.source_name:
        target_entry = _pool_manifest_entry(body.name)
        if target_entry is not None and not _can_access_skill_entry(
            request,
            target_entry,
        ):
            raise HTTPException(status_code=404, detail="Pool skill not found")
    service = SkillPoolService()
    try:
        result = service.save_pool_skill(
            skill_name=source_name,
            target_name=body.name,
            content=body.content,
            config=body.config,
            overwrite=body.overwrite,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("success"):
        reason = result.get("reason")
        status = 404 if reason == "not_found" else 409
        raise HTTPException(status_code=status, detail=result)
    saved_name = str(result.get("name") or body.name)
    governance_updated = _apply_pool_skill_governance(
        saved_name,
        visibility=body.visibility,
        client_visible=body.client_visible,
        owner_user_id=current_user_id(request),
    )
    if not governance_updated:
        raise HTTPException(status_code=404, detail="Pool skill not found")
    if (body.config or {}).get("is_default") is True:
        _sync_default_skill_to_all_workspaces(saved_name)
    return result


@router.post("/pool/upload-zip")
async def upload_skill_pool_zip(
    file: UploadFile = File(...),
    target_name: str = "",
    rename_map: str = "",
) -> dict[str, Any]:
    data = await _read_validated_zip_upload(file)
    parsed_rename: dict[str, str] | None = None
    if rename_map.strip():
        try:
            parsed_rename = json.loads(rename_map)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="rename_map must be valid JSON",
            ) from exc
        if not isinstance(parsed_rename, dict):
            raise HTTPException(
                status_code=400,
                detail="rename_map must be a JSON object",
            )
    try:
        result = await asyncio.to_thread(
            SkillPoolService().import_from_zip,
            data=data,
            target_name=target_name,
            rename_map=parsed_rename,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("conflicts"):
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/pool/import")
async def import_skill_pool_from_hub(
    body: HubInstallRequest,
) -> dict[str, Any]:
    try:
        result = import_pool_skill_from_hub(
            bundle_url=body.bundle_url,
            version=body.version,
            target_name=body.target_name,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SkillConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "installed": True,
        "name": result.name,
        "enabled": False,
        "source_url": result.source_url,
    }


@router.post("/pool/upload")
async def upload_workspace_skill_to_pool(
    request: Request,
    body: UploadToPoolRequest,
) -> dict[str, Any]:
    workspace_dir = await _workspace_dir_for_agent(body.workspace_id, request)
    try:
        result = SkillPoolService().upload_from_workspace(
            workspace_dir=workspace_dir,
            skill_name=body.skill_name,
            overwrite=body.overwrite,
            preview_only=body.preview_only,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("success"):
        status = 404 if result.get("reason") == "not_found" else 409
        raise HTTPException(status_code=status, detail=result)
    return result


async def _preflight_download_conflicts(
    request: Request,
    hub_service: SkillPoolService,
    targets: list[PoolDownloadTarget],
    skill_name: str,
    overwrite: bool,
) -> list[dict[str, Any]]:
    """Check all targets for conflicts before downloading."""
    conflicts: list[dict[str, Any]] = []
    for target in targets:
        workspace_dir = await _workspace_dir_for_agent(target.workspace_id, request)
        result = hub_service.preflight_download_to_workspace(
            skill_name=skill_name,
            workspace_dir=workspace_dir,
            overwrite=overwrite,
        )
        if not result.get("success"):
            conflicts.append(result)
    return conflicts


async def _resolve_and_preflight(
    request: Request,
    body: DownloadFromPoolRequest,
) -> tuple[list[PoolDownloadTarget], SkillPoolService]:
    """Resolve targets and reject if any conflicts exist."""
    _require_pool_skill_access(request, body.skill_name)
    targets = list(body.targets)
    if body.all_workspaces:
        targets = [
            PoolDownloadTarget(workspace_id=workspace["agent_id"])
            for workspace in list_workspaces()
        ]
        
        # Ensure the current request's agent is always included, even if not in global config
        from ..agent_context import get_agent_for_request
        current_agent = await get_agent_for_request(request)
        if not any(t.workspace_id == current_agent.agent_id for t in targets):
            targets.append(PoolDownloadTarget(workspace_id=current_agent.agent_id))
            
    if not targets:
        raise HTTPException(
            status_code=400,
            detail="No workspace targets provided",
        )
    hub_service = SkillPoolService()
    try:
        conflicts = await _preflight_download_conflicts(
            request,
            hub_service,
            targets,
            body.skill_name,
            body.overwrite,
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    if conflicts:
        raise HTTPException(
            status_code=409,
            detail={
                "downloaded": [],
                "conflicts": conflicts,
            },
        )
    return targets, hub_service


async def _build_download_plan(
    request: Request,
    targets: list[PoolDownloadTarget],
    skill_name: str,
) -> list[dict[str, Any]]:
    """Build execution plan with rollback snapshots."""
    plan: list[dict[str, Any]] = []
    for target in targets:
        workspace_dir = await _workspace_dir_for_agent(target.workspace_id, request)
        snapshot = _snapshot_workspace_skill(
            workspace_dir,
            str(skill_name),
        )
        plan.append(
            {
                "workspace_id": target.workspace_id,
                "workspace_dir": workspace_dir,
                "snapshot": snapshot,
            },
        )
    return plan


@router.post("/pool/download")
async def download_pool_skill_to_workspaces(
    request: Request,
    body: DownloadFromPoolRequest,
) -> dict[str, Any]:
    """Download one pool skill into one or more workspaces.

    All-or-nothing: if any target conflicts, reject everything.
    """
    targets, hub_service = await _resolve_and_preflight(request, body)
    if body.preview_only:
        return {"downloaded": []}

    execution_plan = await _build_download_plan(request, targets, body.skill_name)

    downloaded: list[dict[str, str]] = []
    try:
        for plan in execution_plan:
            result = hub_service.download_to_workspace(
                skill_name=body.skill_name,
                workspace_dir=plan["workspace_dir"],
                overwrite=body.overwrite,
            )
            if not result.get("success"):
                for rollback in reversed(execution_plan):
                    _restore_workspace_skill(rollback["snapshot"])
                raise HTTPException(
                    status_code=409,
                    detail={
                        "downloaded": [],
                        "conflicts": [result],
                    },
                )
            downloaded.append(
                {
                    "workspace_id": str(plan["workspace_id"]),
                    "workspace_name": str(
                        result.get("workspace_name", "") or "",
                    ),
                    "name": str(result.get("name", "")),
                },
            )
    except HTTPException:
        raise
    except SkillScanError as exc:
        for rollback in reversed(execution_plan):
            _restore_workspace_skill(rollback["snapshot"])
        return _scan_error_response(exc)
    except Exception:
        for rollback in reversed(execution_plan):
            _restore_workspace_skill(rollback["snapshot"])
        raise
    finally:
        for plan in execution_plan:
            backup_dir = plan["snapshot"].get("backup_dir")
            if backup_dir is not None:
                shutil.rmtree(Path(backup_dir).parent, ignore_errors=True)

    return {"downloaded": downloaded}


@router.post("/pool/import-builtin")
async def import_pool_builtins(
    body: ImportBuiltinRequest,
) -> dict[str, Any]:
    imports: list[dict[str, Any]] = (
        [item.model_dump() for item in body.imports]
        if body.imports
        else [{"skill_name": skill_name} for skill_name in body.skill_names]
    )
    result = import_builtin_skills(
        imports,
        overwrite_conflicts=body.overwrite_conflicts,
    )
    if result.get("conflicts") and not body.overwrite_conflicts:
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/pool/{skill_name}/update-builtin")
async def update_pool_builtin(
    skill_name: str,
    body: UpdateBuiltinRequest | None = Body(default=None),
) -> dict[str, Any]:
    language = body.language if body is not None else ""
    if language and language not in BUILTIN_SKILL_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid language '{language}', "
            f"must be one of {BUILTIN_SKILL_LANGUAGES}",
        )
    try:
        return update_single_builtin(skill_name, language=language or None)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/pool/{skill_name}/governance")
async def update_pool_skill_governance(
    request: Request,
    skill_name: str,
    body: PoolSkillGovernanceRequest,
) -> dict[str, Any]:
    if not is_admin_request(request):
        raise HTTPException(status_code=403, detail="Admin access required")
    _require_pool_skill_access(request, skill_name)
    if body.visibility is None and body.client_visible is None:
        raise HTTPException(status_code=400, detail="No governance fields provided")
    _ensure_pool_skill_can_be_private(skill_name, body.visibility)
    updated = _apply_pool_skill_governance(
        skill_name,
        visibility=body.visibility,
        client_visible=body.client_visible,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Pool skill not found")
    return {"updated": True}


@router.delete("/pool/{skill_name}")
async def delete_pool_skill(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    _require_pool_skill_access(request, skill_name)
    deleted = SkillPoolService().delete_skill(skill_name)
    if not deleted:
        raise HTTPException(
            status_code=409,
            detail="Skill pool entry cannot be deleted",
        )
    # Global sync: remove from all workspaces as well
    for ws in list_workspaces():
        try:
            ws_service = SkillService(Path(ws["workspace_dir"]))
            ws_service.disable_skill(skill_name)
            ws_service.delete_skill(skill_name)
        except Exception:
            pass
    return {"deleted": True}


@router.get("/pool/{skill_name}/config")
async def get_pool_skill_config(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    entry = _require_pool_skill_access(request, skill_name)
    return {"config": entry.get("config", {})}


@router.put("/pool/{skill_name}/config")
async def update_pool_skill_config(
    request: Request,
    skill_name: str,
    body: SkillConfigRequest,
) -> dict[str, Any]:
    _require_pool_skill_access(request, skill_name)
    manifest_path = get_pool_skill_manifest_path()

    def _update(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if entry is None:
            return False
        entry["config"] = dict(body.config)
        return True

    updated = mutate_json(manifest_path, default_pool_manifest(), _update)
    if not updated:
        raise HTTPException(status_code=404, detail="Pool skill not found")
    _apply_pool_skill_governance(skill_name)
    if body.config.get("is_default") is True:
        _sync_default_skill_to_all_workspaces(skill_name)
    return {"updated": True}


@router.delete("/pool/{skill_name}/config")
async def delete_pool_skill_config(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    _require_pool_skill_access(request, skill_name)
    manifest_path = get_pool_skill_manifest_path()

    def _update(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if entry is None:
            return False
        entry.pop("config", None)
        return True

    updated = mutate_json(manifest_path, default_pool_manifest(), _update)
    if not updated:
        raise HTTPException(status_code=404, detail="Pool skill not found")
    return {"cleared": True}


def _validate_tags(tags: list[str]) -> list[str]:
    if len(tags) > MAX_TAGS:
        raise HTTPException(
            status_code=422,
            detail=f"At most {MAX_TAGS} tags allowed",
        )
    cleaned: list[str] = []
    for t in tags:
        t = str(t).strip()[:MAX_TAG_LENGTH]
        if t:
            cleaned.append(t)
    return cleaned


@router.put("/pool/{skill_name}/tags")
async def update_pool_skill_tags(
    request: Request,
    skill_name: str,
    tags: list[str],
) -> dict[str, Any]:
    _require_pool_skill_access(request, skill_name)
    tags = _validate_tags(tags)
    updated = SkillPoolService().set_pool_skill_tags(skill_name, tags)
    if not updated:
        raise HTTPException(
            status_code=404,
            detail="Pool skill not found",
        )
    return {"updated": True, "tags": tags}


@router.post("/batch-delete")
async def batch_delete_skills(
    request: Request,
    skills: list[str],
) -> dict[str, Any]:
    """Auto-disable then delete each skill. Per-skill results."""
    workspace_dir = await _request_workspace_dir(request)
    service = SkillService(workspace_dir)
    results: dict[str, Any] = {}
    for skill_name in skills:
        try:
            _require_workspace_skill_access(request, workspace_dir, skill_name)
            service.disable_skill(skill_name)
            deleted = service.delete_skill(skill_name)
            results[skill_name] = {
                "success": deleted,
                "reason": None if deleted else "delete_failed",
            }
        except HTTPException:
            results[skill_name] = {
                "success": False,
                "reason": "not_found",
            }
        except Exception as exc:
            results[skill_name] = {
                "success": False,
                "reason": str(exc),
            }
    return {"results": results}


@router.post("/pool/batch-delete")
async def batch_delete_pool_skills(
    request: Request,
    skills: list[str],
) -> dict[str, Any]:
    """Delete multiple pool skills. Per-skill results."""
    service = SkillPoolService()
    results: dict[str, Any] = {}
    for skill_name in skills:
        try:
            _require_pool_skill_access(request, skill_name)
            deleted = service.delete_skill(skill_name)
            if deleted:
                # Global sync: remove from all workspaces as well
                for ws in list_workspaces():
                    try:
                        ws_service = SkillService(Path(ws["workspace_dir"]))
                        ws_service.disable_skill(skill_name)
                        ws_service.delete_skill(skill_name)
                    except Exception:
                        pass
            results[skill_name] = {
                "success": deleted,
                "reason": None if deleted else "delete_failed",
            }
        except HTTPException:
            results[skill_name] = {
                "success": False,
                "reason": "not_found",
            }
        except Exception as exc:
            results[skill_name] = {
                "success": False,
                "reason": str(exc),
            }
    return {"results": results}


@router.post("/batch-disable")
async def batch_disable_skills(
    request: Request,
    skills: list[str],
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    service = SkillService(workspace_dir)
    results: dict[str, Any] = {}
    for skill in skills:
        try:
            _require_workspace_skill_access(request, workspace_dir, skill)
            results[skill] = service.disable_skill(skill)
        except HTTPException:
            results[skill] = {"success": False, "reason": "not_found"}
    if any(result.get("success") for result in results.values()):
        schedule_agent_reload(request, workspace.agent_id)
    return {"results": results}


@router.post("/batch-enable")
async def batch_enable_skills(
    request: Request,
    skills: list[str],
) -> dict[str, Any]:
    """Enable each requested skill independently and collect per-skill results.

    Example:
        enabling ``["ok_skill", "blocked_skill"]`` returns success for the
        first item and ``reason="security_scan_failed"`` for the second,
        rather than aborting the entire batch.
    """
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    service = SkillService(workspace_dir)
    results: dict[str, Any] = {}
    for skill in skills:
        try:
            _require_workspace_skill_access(request, workspace_dir, skill)
            results[skill] = service.enable_skill(skill)
        except HTTPException:
            results[skill] = {"success": False, "reason": "not_found"}
        except SkillScanError as exc:
            results[skill] = {
                "success": False,
                "reason": "security_scan_failed",
                "detail": _scan_error_payload(exc),
            }
    if any(
        isinstance(result, dict) and result.get("success")
        for result in results.values()
    ):
        schedule_agent_reload(request, workspace.agent_id)
    return {"results": results}


@router.post("/{skill_name}/disable")
async def disable_skill(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    _require_workspace_skill_access(request, workspace_dir, skill_name)
    result = SkillService(workspace_dir).disable_skill(skill_name)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail="Skill not found")
    schedule_agent_reload(request, workspace.agent_id)
    return {"disabled": True, **result}


@router.post("/{skill_name}/enable")
async def enable_skill(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    """Enable one workspace skill after a fresh scan."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    _require_workspace_skill_access(request, workspace_dir, skill_name)
    try:
        result = SkillService(workspace_dir).enable_skill(skill_name)
    except SkillScanError as exc:
        return _scan_error_response(exc)
    if not result.get("success"):
        raise HTTPException(
            status_code=404,
            detail=result.get("reason", "Skill not found"),
        )
    schedule_agent_reload(request, workspace.agent_id)
    return {"enabled": True, **result}


@router.delete("/{skill_name}")
async def delete_skill(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    _require_workspace_skill_access(request, workspace_dir, skill_name)
    service = SkillService(workspace_dir)
    service.disable_skill(skill_name)
    deleted = service.delete_skill(skill_name)
    if not deleted:
        raise HTTPException(
            status_code=409,
            detail="Only disabled workspace skills can be deleted",
        )
    return {"deleted": True}


@router.get("/{skill_name}/files/{file_path:path}")
async def load_skill_file(
    request: Request,
    skill_name: str,
    file_path: str,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    _require_workspace_skill_access(request, workspace_dir, skill_name)
    content = SkillService(workspace_dir).load_skill_file(
        skill_name=skill_name,
        file_path=file_path,
    )
    if content is None:
        raise HTTPException(status_code=404, detail="File not found")
    return {"content": content}


@router.put("/save")
async def save_workspace_skill(
    request: Request,
    body: SaveSkillRequest,
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    source_name = body.source_name or body.name
    _require_workspace_skill_access(request, workspace_dir, source_name)
    if body.source_name and body.name != body.source_name:
        target_entry = _workspace_skill_entry_for_access(
            workspace_dir,
            body.name,
        )
        if target_entry is not None and not _can_access_skill_entry(
            request,
            target_entry,
        ):
            raise HTTPException(status_code=404, detail="Skill not found")
    try:
        result = SkillService(workspace_dir).save_skill(
            skill_name=source_name,
            content=body.content,
            target_name=body.name if body.source_name else None,
            config=body.config,
            overwrite=body.overwrite,
        )
    except SkillScanError as exc:
        return _scan_error_response(exc)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("success"):
        if result.get("reason") == "conflict":
            raise HTTPException(status_code=409, detail=result)
        raise HTTPException(status_code=404, detail="Skill not found")
    if result.get("mode") != "noop":
        schedule_agent_reload(request, workspace.agent_id)
    return result


@router.put("/{skill_name}/channels")
async def update_skill_channels_endpoint(
    request: Request,
    skill_name: str,
    channels: list[str],
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    _require_workspace_skill_access(request, workspace_dir, skill_name)
    updated = SkillService(workspace_dir).set_skill_channels(
        skill_name,
        channels,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Skill not found")
    schedule_agent_reload(request, workspace.agent_id)
    return {"updated": True, "channels": channels}


@router.put("/{skill_name}/tags")
async def update_skill_tags(
    request: Request,
    skill_name: str,
    tags: list[str],
) -> dict[str, Any]:
    from ..agent_context import get_agent_for_request

    tags = _validate_tags(tags)
    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    _require_workspace_skill_access(request, workspace_dir, skill_name)
    updated = SkillService(workspace_dir).set_skill_tags(
        skill_name,
        tags,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"updated": True, "tags": tags}


@router.get("/{skill_name}/config")
async def get_skill_config_endpoint(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    _require_workspace_skill_access(request, workspace_dir, skill_name)
    manifest = read_skill_manifest(workspace_dir)
    entry = manifest.get("skills", {}).get(skill_name)
    if entry is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"config": entry.get("config", {})}


@router.put("/{skill_name}/config")
async def update_skill_config_endpoint(
    request: Request,
    skill_name: str,
    body: SkillConfigRequest,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    _require_workspace_skill_access(request, workspace_dir, skill_name)
    manifest_path = get_workspace_skill_manifest_path(workspace_dir)

    def _update(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if entry is None:
            return False
        entry["config"] = dict(body.config)
        return True

    updated = mutate_json(
        manifest_path,
        default_workspace_manifest(),
        _update,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"updated": True}


@router.delete("/{skill_name}/config")
async def delete_skill_config_endpoint(
    request: Request,
    skill_name: str,
) -> dict[str, Any]:
    workspace_dir = await _request_workspace_dir(request)
    _require_workspace_skill_access(request, workspace_dir, skill_name)
    manifest_path = get_workspace_skill_manifest_path(workspace_dir)

    def _update(payload: dict[str, Any]) -> bool:
        entry = payload.get("skills", {}).get(skill_name)
        if entry is None:
            return False
        entry.pop("config", None)
        return True

    updated = mutate_json(
        manifest_path,
        default_workspace_manifest(),
        _update,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"cleared": True}
