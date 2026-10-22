# -*- coding: utf-8 -*-
"""Multi-agent management API.

Provides RESTful API for managing multiple agent instances.
"""

import asyncio
import json
import logging
from pathlib import Path
from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi import Path as PathParam
from pydantic import BaseModel, Field, field_validator
from ..chat_access import current_user_id
from ..guards import require_admin
from ..agent_package_import import (
    AgentPackageConflict,
    AgentPackageError,
    AgentPackageImportResult,
    AgentPackagePreview,
    import_agent_package,
    preview_agent_package,
)

from agentscope_runtime.engine.schemas.exception import (
    AppBaseException,
)

from ...agents.utils.file_handling import read_text_file_with_encoding_fallback
from ..utils import schedule_agent_reload
from ...config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    ModelSlotConfig,
    load_agent_config,
    save_agent_config,
    generate_short_agent_id,
    sanitize_agent_id,
    validate_agent_id,
)
from ...app.runner.repo.json_repo import JsonChatRepository
from ...app.runner.models import ChatSpec
from ...config.utils import load_config, save_config
from ...agents.utils import copy_workspace_md_files, normalize_agent_language
from ...agents.skill_system import SkillPoolService, get_workspace_skills_dir
from ...security.skill_scanner import SkillScanError
from ..multi_agent_manager import MultiAgentManager
from ...constant import WORKING_DIR
from ..storage.repos.chat_list_repo import get_chat_list_repository
from ..storage.repos.open_api_repo import get_open_api_repository
from ..sealed_agents.models import AgentCapabilities, SealedCapability
from ..sealed_agents.policy import assert_sealed_capability
from ..sealed_agents.registry import get_sealed_agent_registry
from ..usage_counts import get_settled_agent_usage_counts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])

_ALLOWED_ZIP_TYPES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/octet-stream",
}
_MAX_AGENT_PACKAGE_UPLOAD_BYTES = 200 * 1024 * 1024


class AgentSummary(BaseModel):
    """Agent summary information."""

    id: str
    name: str
    description: str
    workspace_dir: str | None = None
    enabled: bool
    active_model: ModelSlotConfig | None = None
    agent_type: str = "standard"
    scope: str = "private"
    version: str | None = None
    availability: str = "available"
    open_api_enabled: bool = False
    avatar: str | None = None
    usage_count: int = 0
    declared_capabilities: list[str] = Field(default_factory=list)
    capabilities: AgentCapabilities = Field(
        default_factory=AgentCapabilities.for_standard,
    )


class AgentListResponse(BaseModel):
    """Response for listing agents."""

    agents: list[AgentSummary]


class ReorderAgentsRequest(BaseModel):
    """Request model for persisting agent order."""

    agent_ids: list[str]


class CreateAgentRequest(BaseModel):
    """Request model for creating a new agent.

    The ``id`` field is optional.  When provided the server uses it as
    the agent identifier (after sanitization); when omitted a random
    short UUID is generated automatically.
    """

    id: str | None = None
    name: str
    description: str = ""
    workspace_dir: str | None = None
    language: str | None = None
    skill_names: list[str] | None = None
    active_model: ModelSlotConfig | None = None

    @field_validator("id", mode="before")
    @classmethod
    def sanitize_id(cls, value: str | None) -> str | None:
        """Strip whitespace from the custom ID."""
        if value is None:
            return None
        if isinstance(value, str):
            sanitized = sanitize_agent_id(value)
            return sanitized if sanitized else None
        return value

    @field_validator("workspace_dir", mode="before")
    @classmethod
    def strip_workspace_dir(cls, value: str | None) -> str | None:
        """Strip accidental whitespace"""
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else None
        return value


def _get_multi_agent_manager(request: Request) -> MultiAgentManager:
    """Get MultiAgentManager from app state."""
    if not hasattr(request.app.state, "multi_agent_manager"):
        raise HTTPException(
            status_code=500,
            detail="MultiAgentManager not initialized",
        )
    return request.app.state.multi_agent_manager


def _normalized_agent_order(config) -> list[str]:
    """Return a deduplicated agent order covering every configured agent."""
    profile_ids = list(config.agents.profiles.keys())
    ordered_ids: list[str] = []

    for agent_id in config.agents.agent_order:
        if agent_id in config.agents.profiles and agent_id not in ordered_ids:
            ordered_ids.append(agent_id)

    for agent_id in profile_ids:
        if agent_id not in ordered_ids:
            ordered_ids.append(agent_id)

    return ordered_ids


def _read_profile_description(workspace_dir: str) -> str:
    """Read description from PROFILE.md if exists."""
    try:
        profile_path = Path(workspace_dir) / "PROFILE.md"
        if not profile_path.exists():
            return ""

        content = read_text_file_with_encoding_fallback(profile_path).strip()
        lines = []
        in_identity = False

        for line in content.split("\n"):
            if line.strip().startswith("## 身份") or line.strip().startswith(
                "## Identity",
            ):
                in_identity = True
                continue
            if in_identity:
                if line.strip().startswith("##"):
                    break
                if line.strip() and not line.strip().startswith("#"):
                    lines.append(line.strip())

        return " ".join(lines)[:200] if lines else ""
    except Exception:  # noqa: E722
        return ""


def _chat_meta_is_archived(meta: dict) -> bool:
    return bool(meta.get("archived_at") or meta.get("archived") is True)


async def _read_agent_package_upload(file: UploadFile) -> bytes:
    """Read an uploaded zip after lightweight content checks."""
    if file.content_type and file.content_type not in _ALLOWED_ZIP_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Expected a zip file, "
                f"got content-type: {file.content_type}"
            ),
        )

    data = await file.read()
    if len(data) > _MAX_AGENT_PACKAGE_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File too large ({len(data) // (1024 * 1024)} MB). "
                "Maximum is "
                f"{_MAX_AGENT_PACKAGE_UPLOAD_BYTES // (1024 * 1024)} MB."
            ),
        )
    return data


def _agent_package_bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get(
    "",
    response_model=AgentListResponse,
    summary="List all agents",
    description="Get list of all configured agents",
)
async def list_agents(exclude_open_api: bool = False) -> AgentListResponse:
    """List all configured agents."""
    config = load_config()
    ordered_agent_ids = _normalized_agent_order(config)
    open_api_agent_ids = {
        str(publication.get("target_id"))
        for publication in get_open_api_repository().list_publications(
            enabled_only=True,
        )
        if publication.get("target_type") == "agent"
        and publication.get("target_id")
    }
    try:
        usage_counts = get_settled_agent_usage_counts()
    except Exception:
        logger.exception("Failed to load settled agent usage counts")
        usage_counts = {}

    agents = []
    sealed_registry = get_sealed_agent_registry()
    for agent_id in ordered_agent_ids:
        if sealed_registry.is_sealed(agent_id):
            continue
        agent_ref = config.agents.profiles[agent_id]
        try:
            agent_config = load_agent_config(agent_id)
            description = agent_config.description or ""

            profile_desc = _read_profile_description(agent_ref.workspace_dir)
            if profile_desc:
                if description.strip():
                    description = f"{description.strip()} | {profile_desc}"
                else:
                    description = profile_desc

            active_model = agent_config.active_model

            agents.append(
                AgentSummary(
                    id=agent_id,
                    name=agent_config.name,
                    description=description,
                    workspace_dir=agent_ref.workspace_dir,
                    enabled=getattr(agent_ref, "enabled", True),
                    active_model=active_model,
                    open_api_enabled=agent_id in open_api_agent_ids,
                    usage_count=usage_counts.get(agent_id, 0),
                ),
            )
        except Exception:  # noqa: E722
            agents.append(
                AgentSummary(
                    id=agent_id,
                    name=agent_id.title(),
                    description="",
                    workspace_dir=agent_ref.workspace_dir,
                    enabled=getattr(agent_ref, "enabled", True),
                    open_api_enabled=agent_id in open_api_agent_ids,
                    usage_count=usage_counts.get(agent_id, 0),
                ),
            )

    configured_ids = {agent.id for agent in agents}
    for sealed in sealed_registry.list_agents():
        if sealed.agent_id in configured_ids:
            logger.error(
                "Ignoring sealed agent whose id conflicts with a standard agent: %s",
                sealed.agent_id,
            )
            continue
        active_release = sealed.active_release
        try:
            active_model = load_agent_config(sealed.agent_id).active_model
        except Exception:
            active_model = None
        agents.append(
            AgentSummary(
                id=sealed.agent_id,
                name=sealed.name,
                description=sealed.description,
                workspace_dir=None,
                enabled=sealed.enabled,
                active_model=active_model,
                agent_type="sealed",
                scope="global",
                version=active_release.version if active_release else None,
                availability=(
                    "available"
                    if sealed.enabled and active_release is not None
                    else "unavailable"
                ),
                open_api_enabled=sealed.agent_id in open_api_agent_ids,
                avatar=sealed.avatar,
                usage_count=usage_counts.get(sealed.agent_id, 0),
                declared_capabilities=(
                    [item[0] for item in active_release.declared_capabilities]
                    if active_release
                    else []
                ),
                capabilities=AgentCapabilities.for_sealed_global(),
            ),
        )

    if exclude_open_api:
        agents = [
            agent
            for agent in agents
            if agent.enabled
            and (agent.agent_type == "sealed" or not agent.open_api_enabled)
        ]

    return AgentListResponse(agents=agents)


@router.get(
    "/all-chats",
    response_model=list[dict],
    summary="List all chats across all agents",
    description="Get aggregated chat history from all enabled agents",
)
async def list_all_chats(request: Request) -> list[dict]:
    """Aggregate chats across all agents from SQLite and sort by update time."""
    config = load_config()
    user_id = current_user_id(request)
    all_chats = []

    # Get enabled agent IDs
    enabled_agent_ids = [
        agent_id for agent_id, agent_ref in config.agents.profiles.items()
        if getattr(agent_ref, "enabled", True)
    ]
    
    if not enabled_agent_ids:
        return []

    running_chat_ids: set[str] = set()
    try:
        manager = _get_multi_agent_manager(request)
        loaded_agents = getattr(manager, "agents", {})
        for agent_id, workspace in loaded_agents.items():
            if agent_id not in enabled_agent_ids:
                continue
            try:
                tracker = getattr(workspace, "task_tracker", None)
                if tracker is None:
                    continue
                running_chat_ids.update(await tracker.list_active_tasks())
            except Exception as exc:
                logger.debug(
                    "Failed to read active tasks for loaded agent %s: %s",
                    agent_id,
                    exc,
                )
    except Exception as exc:
        logger.debug("Failed to resolve active chat statuses: %s", exc)

    try:
        repo = get_chat_list_repository()
        rows = repo.list_recent_chats(
            enabled_agent_ids=enabled_agent_ids,
            user_id=user_id,
            limit=50,
        )
        
        for row in rows:
            meta = {}
            raw_meta = row.get("meta")
            if isinstance(raw_meta, dict):
                meta = dict(raw_meta)
            elif raw_meta:
                try:
                    meta = json.loads(raw_meta)
                except json.JSONDecodeError:
                    pass

            if _chat_meta_is_archived(meta):
                continue
                    
            meta["agent_id"] = row["agent_id"]
            
            chat_dict = {
                "id": row["id"],
                "user_id": str(row["user_id"]),
                "session_id": row["session_id"],
                "channel": row["channel"],
                "name": row["name"],
                "status": (
                    "running"
                    if row["id"] in running_chat_ids
                    else row["status"] or "idle"
                ),
                "task_status": row["task_status"],
                "pinned": bool(row["pinned"]),
                "meta": meta,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "message_count": row["message_count"],
            }
            all_chats.append(chat_dict)
            
    except Exception as e:
        logger.error(f"Failed to read all chats: {e}")

    return all_chats



@router.put(
    "/order",
    summary="Persist agent order",
    description="Save the full ordered list of configured agent IDs",
    dependencies=[Depends(require_admin)]
)
async def reorder_agents(
    reorder_request: ReorderAgentsRequest = Body(...),
) -> dict:
    """Persist the full ordered list of agent IDs."""
    config = load_config()
    configured_ids = list(config.agents.profiles.keys())

    if len(reorder_request.agent_ids) != len(set(reorder_request.agent_ids)):
        raise HTTPException(
            status_code=400,
            detail="Each configured agent ID must appear exactly once.",
        )

    if set(reorder_request.agent_ids) != set(configured_ids):
        raise HTTPException(
            status_code=400,
            detail="Each configured agent ID must appear exactly once.",
        )

    config.agents.agent_order = list(reorder_request.agent_ids)
    save_config(config)

    return {"success": True, "agent_ids": config.agents.agent_order}


@router.post(
    "/import-package/preview",
    response_model=AgentPackagePreview,
    summary="Preview an uploaded agent package",
    description="Inspect a zip package before importing it as an agent",
    dependencies=[Depends(require_admin)],
)
async def preview_agent_package_upload(
    file: UploadFile = File(...),
    agent_id: str = Form(default=""),
) -> AgentPackagePreview:
    """Preview an agent zip package without writing files."""
    data = await _read_agent_package_upload(file)
    config = load_config()
    try:
        return await asyncio.to_thread(
            preview_agent_package,
            data,
            existing_ids=set(config.agents.profiles.keys()),
            requested_id=agent_id or None,
        )
    except (AgentPackageError, SkillScanError, ValueError) as exc:
        raise _agent_package_bad_request(exc) from exc


@router.post(
    "/import-package",
    response_model=AgentPackageImportResult,
    status_code=201,
    summary="Import an uploaded agent package",
    description="Install a zip package as a configured local agent",
    dependencies=[Depends(require_admin)],
)
async def import_agent_package_upload(
    request: Request,
    file: UploadFile = File(...),
    agent_id: str = Form(default=""),
    enabled: bool = Form(default=True),
    mode: str = Form(default="create"),
) -> AgentPackageImportResult:
    """Import an agent zip package into the configured workspaces."""
    data = await _read_agent_package_upload(file)
    try:
        preview = await asyncio.to_thread(
            preview_agent_package,
            data,
            existing_ids=set(load_config().agents.profiles.keys()),
            requested_id=agent_id or None,
        )
        if get_sealed_agent_registry().is_sealed(preview.id):
            raise HTTPException(
                status_code=403,
                detail="Sealed agent asset access denied",
            )
        result = await asyncio.to_thread(
            import_agent_package,
            data,
            requested_id=agent_id or None,
            enabled=enabled,
            mode=mode,
        )
    except HTTPException:
        raise
    except AgentPackageConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except (AgentPackageError, SkillScanError, ValueError) as exc:
        raise _agent_package_bad_request(exc) from exc

    schedule_agent_reload(request, result.agent_id)
    return result


@router.get(
    "/{agentId}",
    response_model=AgentProfileConfig,
    summary="Get agent details",
    description="Get complete configuration for a specific agent",
)
async def get_agent(agentId: str = PathParam(...)) -> AgentProfileConfig:
    """Get agent configuration."""
    assert_sealed_capability(
        agentId,
        SealedCapability.INSPECT,
        is_sealed=get_sealed_agent_registry().is_sealed(agentId),
    )
    try:
        agent_config = load_agent_config(agentId)
        return agent_config
    except (ValueError, AppBaseException) as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def _generate_unique_id(existing_ids: set[str]) -> str:
    """Generate a unique random short agent ID.

    Raises:
        HTTPException: If a unique ID could not be generated.
    """
    max_attempts = 10
    for _ in range(max_attempts):
        candidate_id = generate_short_agent_id()
        if candidate_id not in existing_ids:
            return candidate_id
    raise HTTPException(
        status_code=500,
        detail="Failed to generate unique agent ID after 10 attempts",
    )


@router.post(
    "",
    response_model=AgentProfileRef,
    status_code=201,
    summary="Create new agent",
    description="Create a new agent with optional custom ID",
    dependencies=[Depends(require_admin)]
)
async def create_agent(
    request: CreateAgentRequest = Body(...),
) -> AgentProfileRef:
    """Create a new agent.

    When ``request.id`` is provided, it is used as the agent identifier
    (validated for URL-safe characters, length, reserved words, and
    uniqueness).  Otherwise a random short UUID is generated.
    """
    config = load_config()
    existing_ids = set(config.agents.profiles.keys())

    if request.id:
        try:
            validate_agent_id(request.id, existing_ids)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=str(e),
            ) from e
        new_id = request.id
    else:
        new_id = _generate_unique_id(existing_ids)

    workspace_dir = Path(
        request.workspace_dir or f"{WORKING_DIR}/workspaces/{new_id}",
    ).expanduser()
    workspace_dir.mkdir(parents=True, exist_ok=True)

    from ...config.config import (
        ChannelConfig,
        MCPConfig,
        HeartbeatConfig,
        ToolsConfig,
    )

    language = normalize_agent_language(
        request.language or config.agents.language or "en",
    )

    agent_config = AgentProfileConfig(
        id=new_id,
        name=request.name,
        description=request.description,
        workspace_dir=str(workspace_dir),
        language=language,
        channels=ChannelConfig(),
        mcp=MCPConfig(),
        heartbeat=HeartbeatConfig(),
        tools=ToolsConfig(),
        active_model=request.active_model,
    )

    _initialize_agent_workspace(
        workspace_dir,
        skill_names=(
            request.skill_names if request.skill_names is not None else []
        ),
        language=language,
    )

    agent_ref = AgentProfileRef(
        id=new_id,
        workspace_dir=str(workspace_dir),
        enabled=True,
    )

    config.agents.profiles[new_id] = agent_ref
    config.agents.agent_order = _normalized_agent_order(config)
    save_config(config)
    save_agent_config(new_id, agent_config)

    logger.info(f"Created new agent: {new_id} (name={request.name})")

    return agent_ref


@router.put(
    "/{agentId}",
    response_model=AgentProfileConfig,
    summary="Update agent",
    description="Update agent configuration and trigger reload",
    dependencies=[Depends(require_admin)]
)
async def update_agent(
    agentId: str = PathParam(...),
    agent_config: AgentProfileConfig = Body(...),
    request: Request = None,
) -> AgentProfileConfig:
    """Update agent configuration."""
    assert_sealed_capability(
        agentId,
        SealedCapability.EDIT,
        is_sealed=get_sealed_agent_registry().is_sealed(agentId),
    )
    config = load_config()

    if agentId not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found",
        )

    existing_config = load_agent_config(agentId)

    update_data = agent_config.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key != "id":
            setattr(existing_config, key, value)

    existing_config.id = agentId
    save_agent_config(agentId, existing_config)
    schedule_agent_reload(request, agentId)

    return agent_config


@router.delete(
    "/{agentId}",
    summary="Delete agent",
    description="Delete agent and workspace (cannot delete default agent)",
    dependencies=[Depends(require_admin)]
)
async def delete_agent(
    agentId: str = PathParam(...),
    request: Request = None,
) -> dict:
    """Delete an agent."""
    assert_sealed_capability(
        agentId,
        SealedCapability.EDIT,
        is_sealed=get_sealed_agent_registry().is_sealed(agentId),
    )
    config = load_config()

    if agentId not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found",
        )

    if agentId == "default":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the default agent",
        )

    manager = _get_multi_agent_manager(request)
    await manager.stop_agent(agentId)

    del config.agents.profiles[agentId]
    config.agents.agent_order = _normalized_agent_order(config)
    save_config(config)

    return {"success": True, "agent_id": agentId}


@router.patch(
    "/{agentId}/toggle",
    summary="Toggle agent enabled state",
    description="Enable or disable an agent (cannot disable default agent)",
    dependencies=[Depends(require_admin)]
)
async def toggle_agent_enabled(
    agentId: str = PathParam(...),
    enabled: bool = Body(..., embed=True),
    request: Request = None,
) -> dict:
    """Toggle agent enabled state."""
    assert_sealed_capability(
        agentId,
        SealedCapability.EDIT,
        is_sealed=get_sealed_agent_registry().is_sealed(agentId),
    )
    config = load_config()

    if agentId not in config.agents.profiles:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agentId}' not found",
        )

    if agentId == "default":
        raise HTTPException(
            status_code=400,
            detail="Cannot disable the default agent",
        )

    agent_ref = config.agents.profiles[agentId]
    manager = _get_multi_agent_manager(request)

    if not enabled and getattr(agent_ref, "enabled", True):
        await manager.stop_agent(agentId)

    agent_ref.enabled = enabled
    save_config(config)

    if enabled:
        try:
            await manager.get_agent(agentId)
            logger.info(f"Agent {agentId} started successfully")
        except Exception as e:
            logger.error(f"Failed to start agent {agentId}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Agent enabled but failed to start: {str(e)}",
            ) from e

    return {
        "success": True,
        "agent_id": agentId,
        "enabled": enabled,
    }


def _apply_workspace_md_templates(
    workspace_dir: Path,
    language: str,
    *,
    md_template_id: str | None,
) -> None:
    """Copy common and template-specific markdown files for a workspace."""
    copy_workspace_md_files(
        language,
        workspace_dir,
        md_template_id=md_template_id,
    )


def _ensure_heartbeat_file(workspace_dir: Path, language: str) -> None:
    """Create the default HEARTBEAT.md if it is missing."""
    heartbeat_file = workspace_dir / "HEARTBEAT.md"
    if heartbeat_file.exists():
        return

    default_heartbeat_mds = {
        "zh": """# Heartbeat checklist
- 扫描收件箱紧急邮件
- 查看未来 2h 的日历
- 检查待办是否卡住
- 若安静超过 8h，轻量 check-in
""",
        "en": """# Heartbeat checklist
- Scan inbox for urgent email
- Check calendar for next 2h
- Check tasks for blockers
- Light check-in if quiet for 8h
""",
        "ru": """# Heartbeat checklist
- Проверить входящие на срочные письма
- Просмотреть календарь на ближайшие 2 часа
- Проверить задачи на наличие блокировок
- Лёгкая проверка при отсутствии активности более 8 часов
""",
    }
    heartbeat_content = default_heartbeat_mds.get(
        language,
        default_heartbeat_mds["en"],
    )
    with open(heartbeat_file, "w", encoding="utf-8") as file:
        file.write(heartbeat_content.strip())


def _install_initial_skills(
    workspace_dir: Path,
    skill_names: list[str] | None,
) -> None:
    """Install requested initial skills from the skill pool."""
    pool_service = SkillPoolService()
    install_names: list[str] = []
    for skill_name in [
        *pool_service.list_default_skill_names(),
        *(skill_names or []),
    ]:
        if skill_name and skill_name not in install_names:
            install_names.append(skill_name)

    if not install_names:
        return

    for skill_name in install_names:
        try:
            result = pool_service.download_to_workspace(
                skill_name=skill_name,
                workspace_dir=workspace_dir,
                overwrite=False,
            )
            if result.get("success"):
                continue
            logger.warning(
                "Failed to install initial skill %s for %s: %s",
                skill_name,
                workspace_dir,
                result.get("reason", "unknown"),
            )
        except Exception as e:
            logger.warning(
                "Failed to install initial skill %s for %s: %s",
                skill_name,
                workspace_dir,
                e,
            )


def _initialize_agent_workspace(
    workspace_dir: Path,
    skill_names: list[str] | None = None,
    md_template_id: str | None = None,
    language: str | None = None,
) -> None:
    """Initialize agent workspace with only explicitly requested skills."""
    from ...config import load_config as load_global_config

    (workspace_dir / "sessions").mkdir(exist_ok=True)
    (workspace_dir / "memory").mkdir(exist_ok=True)
    get_workspace_skills_dir(workspace_dir).mkdir(exist_ok=True)

    config = load_global_config()
    if not language:
        language = config.agents.language or "zh"

    _apply_workspace_md_templates(
        workspace_dir,
        language,
        md_template_id=md_template_id,
    )
    _ensure_heartbeat_file(workspace_dir, language)
    _install_initial_skills(workspace_dir, skill_names)

    jobs_file = workspace_dir / "jobs.json"
    if not jobs_file.exists():
        with open(jobs_file, "w", encoding="utf-8") as file:
            json.dump(
                {"version": 1, "jobs": []},
                file,
                ensure_ascii=False,
                indent=2,
            )

    chats_file = workspace_dir / "chats.json"
    if not chats_file.exists():
        with open(chats_file, "w", encoding="utf-8") as file:
            json.dump(
                {"version": 1, "chats": []},
                file,
                ensure_ascii=False,
                indent=2,
            )
