# -*- coding: utf-8 -*-
"""Workspace API – download / upload the entire WORKING_DIR as a zip.

Also includes agent file management, language settings, audio/transcription
configuration, running config, and system prompt files.
"""

from __future__ import annotations

import asyncio
import io
import shutil
import tempfile
import os
import zipfile
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Body, HTTPException, UploadFile, File, Request, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..utils import schedule_agent_reload
from ...config import (
    load_config,
    save_config,
    AgentsRunningConfig,
)
from ...config.config import load_agent_config, save_agent_config
from ...agents.model_factory import create_model_and_formatter
from ...agents.memory.agent_md_manager import AgentMdManager
from ...agents.templates import get_workspace_md_template_id
from ...agents.utils import copy_workspace_md_files
from ...constant import BUILTIN_QA_AGENT_ID, SUPPORTED_AGENT_LANGUAGES, WORKING_DIR
from ...mindspace import MindspaceScope, MindspaceService
from ...mindspace.models import (
    MindspaceDoc,
    normalize_knowledge_category,
    normalize_knowledge_tags,
    normalize_mindspace_scope,
)
from ...mindspace.cloud_auth import CloudAuthStore
from ...mindspace.connectors import CloudConnectorRegistry
from ...mindspace.jobs import KnowledgeJobOperation, enqueue_knowledge_job
from ..artifact_filter import (
    extract_user_task_files_from_text,
    is_internal_task_file,
    strip_session_data_prefix,
)
from ..agent_context import get_agent_for_request
from ..auth import is_auth_enabled
from ..chat_access import current_user_id, ensure_chat_access, is_admin_request
from ..storage.repos.workspace_context_repo import get_workspace_context_repository


router = APIRouter(prefix="/workspace", tags=["workspace"])


class MdFileInfo(BaseModel):
    """Markdown file metadata."""

    filename: str = Field(..., description="File name")
    path: str = Field(..., description="File path")
    size: int = Field(..., description="Size in bytes")
    created_time: str = Field(..., description="Created time")
    modified_time: str = Field(..., description="Modified time")


class MdFileContent(BaseModel):
    """Markdown file content."""

    content: str = Field(..., description="File content")


def _dir_stats(root: Path) -> tuple[int, int]:
    """Return (file_count, total_size) for *root* recursively."""
    count = 0
    size = 0
    if root.is_dir():
        for p in root.rglob("*"):
            if p.is_file():
                count += 1
                size += p.stat().st_size
    return count, size


def _zip_directory(root: Path) -> io.BytesIO:
    """Create an in-memory zip archive of *root* and return the buffer.

    All files **and** directories (including empty ones) are included.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in sorted(root.rglob("*")):
            arcname = entry.relative_to(root).as_posix()
            if entry.is_file():
                zf.write(entry, arcname)
            elif entry.is_dir():
                # Zip spec: directory entries end with '/'
                zf.write(entry, arcname + "/")
    buf.seek(0)
    return buf


def _zip_files(files: list[tuple[Path, str]]) -> io.BytesIO:
    """Create an in-memory zip archive from explicit workspace file paths."""
    buf = io.BytesIO()
    seen: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for target_path, archive_name in sorted(files, key=lambda item: item[1]):
            if archive_name in seen:
                continue
            seen.add(archive_name)
            zf.write(target_path, archive_name)
    buf.seek(0)
    return buf


PREVIEW_CONTEXT_PREFIX = "__qwenpaw_preview__"


def _legacy_chat_files(workspace_dir: Path) -> list[Path]:
    """Return possible legacy chat index files for an agent workspace."""
    candidates = [workspace_dir / "chats.json"]
    users_dir = workspace_dir / "users"
    if users_dir.exists() and users_dir.is_dir():
        candidates.extend(sorted(users_dir.glob("*/chats.json")))

    seen: set[Path] = set()
    result: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(candidate)
    return result


def resolve_session_id_for_chat_id(chat_id: str, workspace_dir: Path) -> str:
    """Resolve a backend chat UUID to the physical session sandbox id."""
    if not chat_id or chat_id == "claw-global-session":
        return chat_id

    resolved_chat_id = chat_id

    # 1. Try durable chat storage first when available.
    try:
        session_id = get_workspace_context_repository().get_session_id_for_chat_id(
            chat_id,
        )
        if session_id:
            return session_id
    except Exception:
        pass

    # 2. Fallback to legacy per-user chat stores.
    if "-" in resolved_chat_id:
        for chats_file in _legacy_chat_files(workspace_dir):
            if not chats_file.exists():
                continue
            try:
                with open(chats_file, "r", encoding="utf-8", errors="replace") as cf:
                    chats_data = json.load(cf)
                for chat in chats_data.get("chats", []):
                    if chat.get("id") == resolved_chat_id:
                        real_session_id = chat.get("session_id")
                        if real_session_id:
                            return real_session_id
            except Exception:
                pass

    return resolved_chat_id


def get_workspace_dir_for_request(
    request: Request,
    workspace_dir: Path,
    chat_id_override: str | None = None,
) -> Path:
    """Helper to resolve the physical session isolated workspace directory."""
    chat_id = chat_id_override or request.query_params.get("chatId") or request.query_params.get("session_id")
    if not chat_id:
        chat_id = request.headers.get("X-Session-Id") or request.headers.get("X-Chat-Id")

    # Fallback to Referer header for iframe relative assets (e.g. css/js loaded by html)
    if not chat_id:
        referer = request.headers.get("referer")
        if referer:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(referer)
            qs = parse_qs(parsed.query)
            chat_id = (qs.get("chatId") or qs.get("session_id") or [None])[0]
            if not chat_id:
                parts = [part for part in parsed.path.split("/") if part]
                if len(parts) >= 2 and parts[0] in {"task", "claw"}:
                    chat_id = parts[1]
    
    if chat_id == "claw-global-session" and _user_requires_chat_context(request):
        raise HTTPException(
            status_code=403,
            detail="Global workspace access denied",
        )

    if chat_id and chat_id != "claw-global-session":
        chat_id = _normalize_owned_session_id(request, chat_id)

    resolved_dir = workspace_dir
    if chat_id:
        # Physical sandbox penetration for Claw main global session
        if chat_id == "claw-global-session" and "sessions_data" not in workspace_dir.parts:
            sessions_data_dir = workspace_dir / "sessions_data"
            if sessions_data_dir.exists() and sessions_data_dir.is_dir():
                try:
                    subdirs = [
                        d for d in sessions_data_dir.iterdir()
                        if d.is_dir() and d.name != "claw-global-session"
                    ]
                    if subdirs:
                        resolved_dir = max(subdirs, key=lambda d: d.stat().st_mtime)
                    else:
                        resolved_dir = workspace_dir / "sessions_data" / chat_id
                except Exception as e:
                    logger.warning(f"Failed to auto-penetrate sessions_data: {e}")
                    resolved_dir = workspace_dir / "sessions_data" / chat_id
            else:
                resolved_dir = workspace_dir / "sessions_data" / chat_id
        else:
            if "sessions_data" not in workspace_dir.parts:
                resolved_dir = workspace_dir / "sessions_data" / chat_id

    # 统一的物理智能缺省 index.html 自动清理逻辑（彻底去重，由路由层虚拟 Fallback 接管）
    if resolved_dir.exists() and resolved_dir.is_dir():
        try:
            index_path = resolved_dir / "index.html"
            if index_path.exists() and index_path.is_file():
                # 检测是否有唯一的其它 HTML 文件
                html_files = [
                    f for f in resolved_dir.iterdir()
                    if f.is_file() and f.suffix.lower() == ".html" and f.name.lower() != "index.html"
                ]
                if len(html_files) == 1:
                    # 如果 index.html 内容与该 HTML 完全一致，说明是之前自动复制遗留的，直接清理掉
                    import filecmp
                    if filecmp.cmp(html_files[0], index_path, shallow=False):
                        index_path.unlink(missing_ok=True)
                        logger.info(f"Auto-cleaned duplicate physical index.html at {resolved_dir} (delegating to virtual fallback)")
        except Exception as clean_err:
            logger.warning(f"Failed to clean duplicate physical index.html: {clean_err}")

    return resolved_dir


def parse_preview_context_path(file_path: str) -> tuple[str | None, str | None, str]:
    """Extract agent/chat context from preview URLs that must survive relative assets."""
    from urllib.parse import unquote

    parts = file_path.split("/", 3)
    if len(parts) < 4 or parts[0] != PREVIEW_CONTEXT_PREFIX:
        return None, None, file_path

    agent_id = unquote(parts[1])
    chat_id = unquote(parts[2])
    preview_path = parts[3] or "index.html"
    return agent_id, chat_id, preview_path


def _root_workspace_from_session_dir(workspace_dir: Path) -> Path | None:
    parts = workspace_dir.resolve().parts
    if "sessions_data" not in parts:
        return None
    idx = parts.index("sessions_data")
    if idx <= 0:
        return None
    return Path(*parts[:idx])


def _is_within_directory(path: Path, directory: Path) -> bool:
    """Return whether path is inside directory after resolving symlinks."""
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def _normalize_download_path(file_path: str) -> str:
    normalized = file_path.strip().lstrip("/")
    pure_path = PurePosixPath(normalized)
    if (
        not normalized
        or pure_path.is_absolute()
        or any(part in {"", ".", ".."} for part in pure_path.parts)
    ):
        raise HTTPException(status_code=400, detail="Invalid file path")
    return pure_path.as_posix()


def _resolve_downloadable_workspace_file(
    request: Request,
    workspace_dir: Path,
    requested_chat_id: str | None,
    file_path: str,
) -> Path:
    rel_path = _normalize_download_path(file_path)
    target_path = resolve_workspace_file_for_read(workspace_dir, rel_path)
    if not _is_within_directory(target_path, workspace_dir):
        root_workspace = _root_workspace_from_session_dir(workspace_dir)
        if not root_workspace or not _is_within_directory(target_path, root_workspace):
            raise HTTPException(status_code=403, detail="Access denied")
        _assert_root_fallback_allowed(
            request,
            requested_chat_id,
            rel_path,
            root_workspace,
        )

    if not target_path.exists() or not target_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return target_path


def _request_chat_id(request: Request) -> str | None:
    chat_id = request.query_params.get("chatId") or request.query_params.get("session_id")
    if not chat_id:
        chat_id = request.headers.get("X-Session-Id") or request.headers.get("X-Chat-Id")
    if not chat_id:
        referer = request.headers.get("referer")
        if referer:
            from urllib.parse import parse_qs, urlparse

            parsed = urlparse(referer)
            qs = parse_qs(parsed.query)
            chat_id = (qs.get("chatId") or qs.get("session_id") or [None])[0]
            if not chat_id:
                parts = [part for part in parsed.path.split("/") if part]
                if len(parts) >= 2 and parts[0] in {"task", "claw"}:
                    chat_id = parts[1]
    return chat_id


def _user_requires_chat_context(request: Request) -> bool:
    return is_auth_enabled() and not is_admin_request(request)


def _require_chat_context_for_user(
    request: Request,
    chat_id: str | None,
) -> None:
    if _user_requires_chat_context(request) and not chat_id:
        raise HTTPException(status_code=400, detail="chatId is required")


def _owned_chat_row(request: Request, chat_id: str | None):
    if not chat_id:
        return None
    if chat_id == "claw-global-session":
        if _user_requires_chat_context(request):
            raise HTTPException(
                status_code=403,
                detail="Global workspace access denied",
            )
        return None
    return ensure_chat_access(request, chat_id)


def _normalize_owned_chat_id(
    request: Request,
    chat_id: str | None,
) -> str | None:
    row = _owned_chat_row(request, chat_id)
    return str(row["id"]) if row is not None else chat_id


def _normalize_owned_session_id(
    request: Request,
    chat_id: str | None,
) -> str | None:
    row = _owned_chat_row(request, chat_id)
    return str(row["session_id"] or row["id"]) if row is not None else chat_id


def _assert_owned_chat_agent_context(
    request: Request,
    chat_id: str | None,
    agent_id: str | None,
) -> None:
    if not chat_id or not agent_id:
        return
    row = _owned_chat_row(request, chat_id)
    if row is None:
        return
    owned_agent_id = str(row.get("agent_id") or "")
    if owned_agent_id and owned_agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Chat not found")


def _workspace_dir_for_user_context(
    request: Request,
    workspace_dir: Path,
) -> Path:
    requested_chat_id = _request_chat_id(request)
    _require_chat_context_for_user(request, requested_chat_id)
    return get_workspace_dir_for_request(
        request,
        workspace_dir,
        chat_id_override=requested_chat_id,
    )


def _assert_root_fallback_allowed(
    request: Request,
    requested_chat_id: str | None,
    file_path: str,
    root_workspace: Path,
) -> None:
    if not _user_requires_chat_context(request):
        return
    if not requested_chat_id:
        raise HTTPException(status_code=400, detail="chatId is required")
    owned_chat_id = _normalize_owned_chat_id(request, requested_chat_id)
    allowed = set(_explicit_artifact_files_for_chat(owned_chat_id, root_workspace))
    if file_path not in allowed:
        raise HTTPException(
            status_code=403,
            detail="File is not part of this chat",
        )


def _structured_media_files_from_state(
    state_text: str,
    workspace_dir: Path,
) -> list[str]:
    """Return local media paths explicitly embedded in structured chat state."""
    try:
        payload = json.loads(state_text)
    except (TypeError, ValueError):
        return []

    root = workspace_dir.resolve()
    result: list[str] = []
    seen: set[str] = set()

    def add_candidate(value: object) -> None:
        if not isinstance(value, str):
            return
        candidate = value.strip()
        if candidate.startswith("file://"):
            candidate = candidate.removeprefix("file://")
        elif "://" in candidate or candidate.startswith(("data:", "blob:")):
            return

        candidate_path = Path(candidate)
        resolved = (
            candidate_path.resolve()
            if candidate_path.is_absolute()
            else (root / candidate_path).resolve()
        )
        try:
            rel_path = resolved.relative_to(root).as_posix()
        except ValueError:
            return
        if (
            not rel_path
            or is_internal_task_file(rel_path)
            or not resolved.is_file()
            or rel_path in seen
        ):
            return
        seen.add(rel_path)
        result.append(rel_path)

    def walk(value: object) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item)
            return
        if not isinstance(value, dict):
            return

        if value.get("type") in {"image", "video", "audio", "file"}:
            source = value.get("source")
            if isinstance(source, dict) and source.get("type") == "url":
                add_candidate(source.get("url"))
            for key in ("image_url", "video_url", "file_url", "data"):
                add_candidate(value.get(key))

        for child in value.values():
            if isinstance(child, (dict, list)):
                walk(child)

    walk(payload)
    return result


def _explicit_artifact_files_for_chat(chat_id: str | None, workspace_dir: Path) -> list[str]:
    """Return user artifact files explicitly mentioned by a chat's state."""
    if not chat_id:
        return []

    chat_ids = [chat_id]
    try:
        repo = get_workspace_context_repository()
        for row in repo.list_chat_identity_rows(chat_id):
            for value in (row["id"], row["session_id"]):
                if value and value not in chat_ids:
                    chat_ids.append(value)

        state_texts = repo.get_session_state_texts(chat_ids)

        session_ids = set()
        for candidate in chat_ids:
            if candidate and "-" not in candidate:
                session_ids.add(candidate)
        result: list[str] = []
        seen: set[str] = set()
        for state_text in state_texts:
            paths = extract_user_task_files_from_text(state_text, workspace_dir)
            paths.extend(_structured_media_files_from_state(state_text, workspace_dir))
            for path in paths:
                for session_id in session_ids:
                    path = strip_session_data_prefix(path, session_id)
                if path in seen:
                    continue
                seen.add(path)
                result.append(path)
        return result
    except Exception:
        return []


def _file_info_for_workspace_path(workspace_dir: Path, rel_path: str) -> MdFileInfo | None:
    target = resolve_workspace_file_for_read(workspace_dir, rel_path)
    if not target.exists() or not target.is_file():
        return None
    stat = target.stat()
    return MdFileInfo(
        filename=rel_path,
        path=rel_path,
        size=stat.st_size,
        created_time=datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
        modified_time=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    )


def resolve_workspace_file_for_read(workspace_dir: Path, file_path: str) -> Path:
    """Resolve a user-requested workspace file with a safe root fallback.

    Session sandboxes are the preferred source.  Some older skills/tools wrote
    final deliverables to the root workspace while the active chat was isolated;
    if the file is missing in the sandbox, allow a fallback only for non-internal
    user artifact paths.
    """
    workspace_dir = workspace_dir.resolve()
    target_path = (workspace_dir / file_path).resolve()
    if target_path.exists():
        return target_path

    if is_internal_task_file(file_path):
        return target_path

    root_workspace = _root_workspace_from_session_dir(workspace_dir)
    if not root_workspace:
        return target_path

    fallback_path = (root_workspace / file_path).resolve()
    if _is_within_directory(fallback_path, root_workspace) and fallback_path.exists():
        return fallback_path

    return target_path


# ---------------------------------------------------------------------------
# Agent File Management Endpoints
# ---------------------------------------------------------------------------

import logging
logger = logging.getLogger(__name__)


@router.get(
    "/files",
    response_model=list[MdFileInfo],
    summary="List working files",
    description="List all working files (uses active agent)",
)
async def list_working_files(
    request: Request,
) -> list[MdFileInfo]:
    """List working directory markdown files."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_dir = Path(workspace.workspace_dir).resolve()
        workspace_dir = _workspace_dir_for_user_context(request, workspace_dir)

        # Automatically initialize md templates if isolated workspace doesn't exist
        if "sessions_data" in workspace_dir.parts and not workspace_dir.exists():
            workspace_dir.mkdir(parents=True, exist_ok=True)
            try:
                agent_config = load_agent_config(workspace.agent_id)
                copy_workspace_md_files(
                    agent_config.language,
                    workspace_dir,
                    md_template_id=get_workspace_md_template_id(
                        agent_config.template_id
                        or ("qa" if workspace.agent_id == BUILTIN_QA_AGENT_ID else None)
                    ),
                    only_if_missing=True,
                )
                logger.info(f"Auto-initialized isolated markdown files at {workspace_dir}")
            except Exception as copy_exc:
                logger.warning(f"Failed to auto-copy md files to {workspace_dir}: {copy_exc}")

        workspace_manager = AgentMdManager(
            str(workspace_dir),
            agent_id=workspace.agent_id,
        )
        files = [
            MdFileInfo.model_validate(file)
            for file in workspace_manager.list_working_mds()
        ]
        return files
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/files/{md_name}",
    response_model=MdFileContent,
    summary="Read a working file",
    description="Read a working markdown file (uses active agent)",
)
async def read_working_file(
    md_name: str,
    request: Request,
) -> MdFileContent:
    """Read a working directory markdown file."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_dir = Path(workspace.workspace_dir).resolve()
        workspace_dir = _workspace_dir_for_user_context(request, workspace_dir)

        # Ensure directory and templates exist for reads
        if "sessions_data" in workspace_dir.parts and not workspace_dir.exists():
            workspace_dir.mkdir(parents=True, exist_ok=True)
            try:
                agent_config = load_agent_config(workspace.agent_id)
                copy_workspace_md_files(
                    agent_config.language,
                    workspace_dir,
                    md_template_id=get_workspace_md_template_id(
                        agent_config.template_id
                        or ("qa" if workspace.agent_id == BUILTIN_QA_AGENT_ID else None)
                    ),
                    only_if_missing=True,
                )
            except Exception as copy_exc:
                logger.warning(f"Failed to auto-copy md files: {copy_exc}")

        workspace_manager = AgentMdManager(
            str(workspace_dir),
            agent_id=workspace.agent_id,
        )
        content = workspace_manager.read_working_md(md_name)
        return MdFileContent(content=content)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put(
    "/files/{md_name}",
    response_model=dict,
    summary="Write a working file",
    description="Create or update a working file (uses active agent)",
)
async def write_working_file(
    md_name: str,
    body: MdFileContent,
    request: Request,
) -> dict:
    """Write a working directory markdown file."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_dir = Path(workspace.workspace_dir).resolve()
        workspace_dir = _workspace_dir_for_user_context(request, workspace_dir)

        if "sessions_data" in workspace_dir.parts and not workspace_dir.exists():
            workspace_dir.mkdir(parents=True, exist_ok=True)

        workspace_manager = AgentMdManager(
            str(workspace_dir),
            agent_id=workspace.agent_id,
        )
        workspace_manager.write_working_md(md_name, body.content)
        return {"written": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/memory",
    response_model=list[MdFileInfo],
    summary="List memory files",
    description="List all memory files (uses active agent)",
)
async def list_memory_files(
    request: Request,
) -> list[MdFileInfo]:
    """List memory directory markdown files."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_dir = Path(workspace.workspace_dir).resolve()
        workspace_dir = _workspace_dir_for_user_context(request, workspace_dir)

        if "sessions_data" in workspace_dir.parts and not workspace_dir.exists():
            workspace_dir.mkdir(parents=True, exist_ok=True)

        workspace_manager = AgentMdManager(
            str(workspace_dir),
            agent_id=workspace.agent_id,
        )
        files = [
            MdFileInfo.model_validate(file)
            for file in workspace_manager.list_memory_mds()
        ]
        return files
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/memory/{md_name}",
    response_model=MdFileContent,
    summary="Read a memory file",
    description="Read a memory markdown file (uses active agent)",
)
async def read_memory_file(
    md_name: str,
    request: Request,
) -> MdFileContent:
    """Read a memory directory markdown file."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_dir = Path(workspace.workspace_dir).resolve()
        workspace_dir = _workspace_dir_for_user_context(request, workspace_dir)

        if "sessions_data" in workspace_dir.parts and not workspace_dir.exists():
            workspace_dir.mkdir(parents=True, exist_ok=True)

        workspace_manager = AgentMdManager(
            str(workspace_dir),
            agent_id=workspace.agent_id,
        )
        content = workspace_manager.read_memory_md(md_name)
        return MdFileContent(content=content)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put(
    "/memory/{md_name}",
    response_model=dict,
    summary="Write a memory file",
    description="Create or update a memory file (uses active agent)",
)
async def write_memory_file(
    md_name: str,
    body: MdFileContent,
    request: Request,
) -> dict:
    """Write a memory directory markdown file."""
    try:
        workspace = await get_agent_for_request(request)
        workspace_dir = Path(workspace.workspace_dir).resolve()
        workspace_dir = _workspace_dir_for_user_context(request, workspace_dir)

        if "sessions_data" in workspace_dir.parts and not workspace_dir.exists():
            workspace_dir.mkdir(parents=True, exist_ok=True)

        workspace_manager = AgentMdManager(
            str(workspace_dir),
            agent_id=workspace.agent_id,
        )
        workspace_manager.write_memory_md(md_name, body.content)
        return {"written": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/language",
    summary="Get agent language",
    description="Get the language setting for agent MD files.",
)
async def get_agent_language(request: Request) -> dict:
    """Get agent language setting for current agent."""
    workspace = await get_agent_for_request(request)
    agent_config = load_agent_config(workspace.agent_id)
    return {
        "language": agent_config.language,
        "agent_id": workspace.agent_id,
    }


@router.put(
    "/language",
    summary="Update agent language",
    description=(
        "Update the language for agent MD files. "
        "Optionally copies MD files for the new language to agent workspace."
    ),
)
async def put_agent_language(
    request: Request,
    body: dict = Body(
        ...,
        description='Language setting, e.g. {"language": "id"}',
    ),
) -> dict:
    """
    Update agent language and optionally re-copy MD files to agent workspace.
    """
    language = (body.get("language") or "").strip().lower()
    valid = SUPPORTED_AGENT_LANGUAGES
    if language not in valid:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid language '{language}'. "
                f"Must be one of: {', '.join(sorted(valid))}"
            ),
        )

    workspace = await get_agent_for_request(request)
    agent_id = workspace.agent_id

    agent_config = load_agent_config(agent_id)
    old_language = agent_config.language

    agent_config.language = language
    save_agent_config(agent_id, agent_config)

    copied_files: list[str] = []
    if old_language != language:
        copied_files = copy_workspace_md_files(
            language,
            workspace.workspace_dir,
            md_template_id=get_workspace_md_template_id(
                agent_config.template_id
                or ("qa" if agent_id == BUILTIN_QA_AGENT_ID else None),
            ),
            only_if_missing=False,
        )

    return {
        "language": language,
        "copied_files": copied_files,
        "agent_id": agent_id,
    }


@router.get(
    "/audio-mode",
    summary="Get audio mode",
    description=(
        "Get the audio handling mode for incoming voice messages. "
        'Values: "auto", "native".'
    ),
)
async def get_audio_mode() -> dict:
    """Get audio mode setting."""
    config = load_config()
    return {"audio_mode": config.agents.audio_mode}


@router.put(
    "/audio-mode",
    summary="Update audio mode",
    description=(
        "Update how incoming audio/voice messages are handled. "
        '"auto": transcribe if provider available, else file placeholder; '
        '"native": send audio directly to model (may need ffmpeg).'
    ),
)
async def put_audio_mode(
    body: dict = Body(
        ...,
        description='Audio mode, e.g. {"audio_mode": "auto"}',
    ),
) -> dict:
    """Update audio mode setting."""
    raw = body.get("audio_mode")
    audio_mode = (str(raw) if raw is not None else "").strip().lower()
    valid = {"auto", "native"}
    if audio_mode not in valid:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid audio_mode '{audio_mode}'. "
                f"Must be one of: {', '.join(sorted(valid))}"
            ),
        )
    config = load_config()
    config.agents.audio_mode = audio_mode
    save_config(config)
    return {"audio_mode": audio_mode}


@router.get(
    "/transcription-provider-type",
    summary="Get transcription provider type",
    description=(
        "Get the transcription provider type. "
        'Values: "disabled", "whisper_api", "local_whisper".'
    ),
)
async def get_transcription_provider_type() -> dict:
    """Get transcription provider type setting."""
    config = load_config()
    return {
        "transcription_provider_type": (
            config.agents.transcription_provider_type
        ),
    }


@router.put(
    "/transcription-provider-type",
    summary="Set transcription provider type",
    description=(
        "Set the transcription provider type. "
        '"disabled": no transcription; '
        '"whisper_api": remote Whisper endpoint; '
        '"local_whisper": locally installed openai-whisper.'
    ),
)
async def put_transcription_provider_type(
    body: dict = Body(
        ...,
        description=(
            "Provider type, e.g. "
            '{"transcription_provider_type": "whisper_api"}'
        ),
    ),
) -> dict:
    """Set the transcription provider type."""
    raw = body.get("transcription_provider_type")
    provider_type = (str(raw) if raw is not None else "").strip().lower()
    valid = {"disabled", "whisper_api", "local_whisper"}
    if provider_type not in valid:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid transcription_provider_type '{provider_type}'. "
                f"Must be one of: {', '.join(sorted(valid))}"
            ),
        )
    config = load_config()
    config.agents.transcription_provider_type = provider_type
    save_config(config)
    return {"transcription_provider_type": provider_type}


@router.get(
    "/local-whisper-status",
    summary="Check local whisper availability",
    description=(
        "Check whether the local whisper provider can be used. "
        "Returns availability of ffmpeg and openai-whisper."
    ),
)
async def get_local_whisper_status() -> dict:
    """Check local whisper dependencies."""
    from ...agents.utils.audio_transcription import (
        check_local_whisper_available,
    )

    return check_local_whisper_available()


@router.get(
    "/transcription-providers",
    summary="List transcription providers",
    description=(
        "List providers capable of audio transcription (Whisper API). "
        "Returns available providers and the configured selection."
    ),
)
async def get_transcription_providers() -> dict:
    """List transcription-capable providers and configured selection."""
    from ...agents.utils.audio_transcription import (
        get_configured_transcription_provider_id,
        list_transcription_providers,
    )

    return {
        "providers": list_transcription_providers(),
        "configured_provider_id": (get_configured_transcription_provider_id()),
    }


@router.put(
    "/transcription-provider",
    summary="Set transcription provider",
    description=(
        "Set the provider to use for audio transcription. "
        'Use empty string "" to unset.'
    ),
)
async def put_transcription_provider(
    body: dict = Body(
        ...,
        description=(
            'Provider ID, e.g. {"provider_id": "openai"} '
            'or {"provider_id": ""} to unset'
        ),
    ),
) -> dict:
    """Set the transcription provider."""
    provider_id = (body.get("provider_id") or "").strip()
    config = load_config()
    config.agents.transcription_provider_id = provider_id
    save_config(config)
    return {"provider_id": provider_id}


@router.post(
    "/transcribe",
    summary="Transcribe audio to text",
    description=(
        "Transcribe an uploaded audio file "
        "using the configured Whisper provider. "
        "Returns the transcribed text."
    ),
)
async def post_transcribe_audio(
    file: UploadFile = File(..., description="Audio file to transcribe"),
) -> dict:
    """Transcribe uploaded audio file using configured Whisper provider."""
    from ...agents.utils.audio_transcription import transcribe_audio

    # Check transcription is enabled
    config = load_config()
    provider_type = config.agents.transcription_provider_type
    if provider_type == "disabled":
        raise HTTPException(
            status_code=400,
            detail={
                "code": "TRANSCRIPTION_DISABLED",
                "message": (
                    "Transcription is disabled. "
                    "Configure a transcription provider in Settings."
                ),
            },
        )

    # Validate file type
    allowed_extensions = {
        ".webm",
        ".mp4",
        ".m4a",
        ".wav",
        ".mp3",
        ".ogg",
        ".flac",
    }
    suffix = (
        os.path.splitext(file.filename or "audio.webm")[1].lower() or ".webm"
    )
    if suffix not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "UNSUPPORTED_FILE_TYPE",
                "message": (
                    f"Unsupported file type: {suffix}. "
                    f"Allowed: {', '.join(sorted(allowed_extensions))}"
                ),
            },
        )

    # Validate file size (25 MB max)
    max_size_bytes = 25 * 1024 * 1024
    data = await file.read()
    if len(data) > max_size_bytes:
        size_mb = len(data) / 1024 / 1024
        raise HTTPException(
            status_code=400,
            detail={
                "code": "FILE_TOO_LARGE",
                "message": (
                    f"File too large ({size_mb:.1f}MB). "
                    "Maximum allowed: 25MB."
                ),
            },
        )

    # Save uploaded file to temp directory
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        text = await transcribe_audio(tmp_path)
        if text is None:
            raise HTTPException(
                status_code=500,
                detail="Transcription failed. Check provider configuration.",
            )
        return {"text": text}
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.get(
    "/running-config",
    response_model=AgentsRunningConfig,
    summary="Get agent running config",
    description="Get running configuration for active agent",
)
async def get_agents_running_config(
    request: Request,
) -> AgentsRunningConfig:
    """Get agent running configuration."""
    workspace = await get_agent_for_request(request)
    agent_config = load_agent_config(workspace.agent_id)
    running = agent_config.running or AgentsRunningConfig()
    running.approval_level = getattr(agent_config, "approval_level", "AUTO")
    return running


@router.put(
    "/running-config",
    response_model=AgentsRunningConfig,
    summary="Update agent running config",
    description="Update running configuration for active agent",
)
async def put_agents_running_config(
    running_config: AgentsRunningConfig = Body(
        ...,
        description="Updated agent running configuration",
    ),
    request: Request = None,
) -> AgentsRunningConfig:
    """Update agent running configuration."""
    workspace = await get_agent_for_request(request)
    agent_config = load_agent_config(workspace.agent_id)

    if running_config.approval_level is not None:
        agent_config.approval_level = running_config.approval_level

    running_config.approval_level = None
    agent_config.running = running_config
    save_agent_config(workspace.agent_id, agent_config)

    schedule_agent_reload(request, workspace.agent_id)

    running_config.approval_level = agent_config.approval_level
    return running_config


@router.get(
    "/system-prompt-files",
    response_model=list[str],
    summary="Get system prompt files",
    description="Get system prompt files for active agent",
)
async def get_system_prompt_files(
    request: Request,
) -> list[str]:
    """Get list of enabled system prompt files."""
    workspace = await get_agent_for_request(request)
    agent_config = load_agent_config(workspace.agent_id)
    return agent_config.system_prompt_files or []


@router.put(
    "/system-prompt-files",
    response_model=list[str],
    summary="Update system prompt files",
    description="Update system prompt files for active agent",
)
async def put_system_prompt_files(
    files: list[str] = Body(
        ...,
        description="Markdown filenames to load into system prompt",
    ),
    request: Request = None,
) -> list[str]:
    """Update list of enabled system prompt files."""
    workspace = await get_agent_for_request(request)
    agent_config = load_agent_config(workspace.agent_id)
    agent_config.system_prompt_files = files
    save_agent_config(workspace.agent_id, agent_config)

    schedule_agent_reload(request, workspace.agent_id)

    return files


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_zip_data(data: bytes, workspace_dir: Path) -> None:
    """Ensure *data* is a valid zip without path-traversal entries."""
    if not zipfile.is_zipfile(io.BytesIO(data)):
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is not a valid zip archive",
        )
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            resolved = (workspace_dir / name).resolve()
            if not _is_within_directory(resolved, workspace_dir):
                raise HTTPException(
                    status_code=400,
                    detail=f"Zip contains unsafe path: {name}",
                )


def _extract_and_merge_zip(data: bytes, workspace_dir: Path) -> None:
    """Extract zip data and merge into workspace_dir (blocking operation)."""
    tmp_dir = None
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix="qwenpaw_upload_"))
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(tmp_dir)

        top_entries = list(tmp_dir.iterdir())
        extract_root = tmp_dir
        if len(top_entries) == 1 and top_entries[0].is_dir():
            extract_root = top_entries[0]

        workspace_dir.mkdir(parents=True, exist_ok=True)

        for item in extract_root.iterdir():
            dest = workspace_dir / item.name
            if item.is_file():
                shutil.copy2(item, dest)
            else:
                if dest.exists() and dest.is_file():
                    dest.unlink()
                shutil.copytree(item, dest, dirs_exist_ok=True)
    finally:
        if tmp_dir and tmp_dir.is_dir():
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _validate_and_extract_zip(data: bytes, workspace_dir: Path) -> None:
    """Validate and extract zip data (blocking operation)."""
    _validate_zip_data(data, workspace_dir)
    _extract_and_merge_zip(data, workspace_dir)


# ---------------------------------------------------------------------------
# Workspace Download/Upload Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/download",
    summary="Download workspace as zip",
    description=(
        "Package the entire agent workspace into a zip archive and stream "
        "it back as a downloadable file."
    ),
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "Zip archive of agent workspace",
        },
    },
)
async def download_workspace(request: Request):
    """Stream agent workspace as a zip file."""

    agent = await get_agent_for_request(request)
    requested_chat_id = _request_chat_id(request)
    _require_chat_context_for_user(request, requested_chat_id)
    workspace_dir = get_workspace_dir_for_request(
        request,
        Path(agent.workspace_dir).resolve(),
        chat_id_override=requested_chat_id,
    )

    if not workspace_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"Workspace does not exist: {workspace_dir}",
        )

    buf = await asyncio.to_thread(_zip_directory, workspace_dir)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"qwenpaw_workspace_{agent.agent_id}_{timestamp}.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get(
    "/artifacts/download",
    summary="Download workspace artifacts as zip",
    description="Package only task artifacts for the current chat/session.",
)
async def download_workspace_artifacts(
    request: Request,
    session_id: str | None = None,
    agent_id: str | None = None,
):
    """Stream current chat artifacts as a zip file."""

    requested_chat_id = _request_chat_id(request) or session_id
    _assert_owned_chat_agent_context(request, requested_chat_id, agent_id)
    if agent_id:
        agent = await get_agent_for_request(request, agent_id=agent_id)
    else:
        agent = await get_agent_for_request(request)
    _require_chat_context_for_user(request, requested_chat_id)
    workspace_dir = get_workspace_dir_for_request(
        request,
        Path(agent.workspace_dir).resolve(),
        chat_id_override=requested_chat_id,
    )

    artifacts = await list_workspace_artifacts(
        request,
        session_id=requested_chat_id,
        agent_id=agent_id,
    )
    targets: list[tuple[Path, str]] = []
    for artifact in artifacts:
        rel_path = _normalize_download_path(artifact.path)
        target_path = _resolve_downloadable_workspace_file(
            request,
            workspace_dir,
            requested_chat_id,
            rel_path,
        )
        targets.append((target_path, rel_path))

    if not targets:
        raise HTTPException(status_code=404, detail="No artifacts to download")

    buf = await asyncio.to_thread(_zip_files, targets)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"qwenpaw_artifacts_{agent.agent_id}_{timestamp}.zip"

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get(
    "/files/download/{file_path:path}",
    summary="Download a workspace file",
    description="Download one file from the current chat/session workspace.",
)
async def download_workspace_file(file_path: str, request: Request):
    """Stream a single workspace file as an attachment."""

    import mimetypes

    requested_chat_id = _request_chat_id(request)
    _require_chat_context_for_user(request, requested_chat_id)
    owned_agent_id = None
    if requested_chat_id and _user_requires_chat_context(request):
        chat_row = _owned_chat_row(request, requested_chat_id)
        owned_agent_id = str(chat_row.get("agent_id") or "") or None
    agent = await get_agent_for_request(request, agent_id=owned_agent_id)
    workspace_dir = get_workspace_dir_for_request(
        request,
        Path(agent.workspace_dir).resolve(),
        chat_id_override=requested_chat_id,
    )
    target_path = _resolve_downloadable_workspace_file(
        request,
        workspace_dir,
        requested_chat_id,
        file_path,
    )

    media_type, _ = mimetypes.guess_type(target_path)
    return FileResponse(
        target_path,
        media_type=media_type or "application/octet-stream",
        filename=target_path.name,
    )


@router.post(
    "/upload",
    response_model=dict,
    summary="Upload zip and merge into workspace",
    description=(
        "Upload a zip archive.  Paths present in the zip are merged into "
        "agent workspace (files overwritten, dirs merged).  Paths not in "
        "the zip are left unchanged (e.g. qwenpaw.db, runtime dirs). "
        "Download packs the entire workspace; upload only "
        "overwrites/merges zip contents."
    ),
)
async def upload_workspace(
    request: Request,
    file: UploadFile = File(
        ...,
        description="Zip archive to merge into agent workspace",
    ),
) -> dict:
    """
    Merge uploaded zip contents into agent workspace (overwrite, not clear).
    """

    if file.content_type and file.content_type not in (
        "application/zip",
        "application/x-zip-compressed",
        "application/octet-stream",
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Expected a zip file, got content-type: {file.content_type}"
            ),
        )

    agent = await get_agent_for_request(request)
    requested_chat_id = _request_chat_id(request)
    _require_chat_context_for_user(request, requested_chat_id)
    workspace_dir = get_workspace_dir_for_request(
        request,
        Path(agent.workspace_dir).resolve(),
        chat_id_override=requested_chat_id,
    )
    data = await file.read()

    try:
        await asyncio.to_thread(_validate_and_extract_zip, data, workspace_dir)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to merge workspace: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Agent Synergy Mindspace & Shared RAG Endpoints
# ---------------------------------------------------------------------------

class CloudDocItem(BaseModel):
    """Agent synergy mindspace cloud & shared RAG document info."""
    id: str = Field(..., description="Document unique ID")
    name: str = Field(..., description="Document name")
    type: str = Field(..., description="Document type: tencent, lark, pdf, md, txt")
    url: str | None = Field(None, description="Document URL for cloud sources")
    size: str = Field(..., description="File size or type description")
    slices: int = Field(..., description="RAG slice chunk blocks count")
    status: str = Field(..., description="syncing, ready, failed")
    progress: int | None = Field(None, description="Syncing percentage progress")
    stage: int | None = Field(None, description="RAG stage: 1 (chunking), 2 (embedding), 3 (indexing)")
    updatedAt: str = Field(..., description="Last synchronized time")


class LinkCloudDocRequest(BaseModel):
    """Link cloud document request payload."""
    title: str
    url: str
    docType: str
    scope: str = "agent"
    cloud_account_id: str | None = None
    cloudAccountId: str | None = None
    category: str = "uncategorized"
    tags: list[str] = Field(default_factory=list)


class SyncCloudDocRequest(BaseModel):
    """Sync specific document request."""
    id: str
    scope: str | None = None


class KnowledgeMetadataRequest(BaseModel):
    category: str = "uncategorized"
    tags: list[str] = Field(default_factory=list)


def _parse_mindspace_scope(scope: str | None) -> MindspaceScope | None:
    resolved = normalize_mindspace_scope(scope)
    if not scope or scope == "all":
        return None
    if resolved is None:
        raise HTTPException(
            status_code=400,
            detail="scope must be enterprise, personal, global, agent, or all",
        )
    return resolved


def _scope_query_pattern(allow_all: bool = True) -> str:
    return (
        "^(enterprise|personal|global|agent|all)$"
        if allow_all
        else "^(enterprise|personal|global|agent)$"
    )


def _require_enterprise_write_allowed(request: Request, scope: MindspaceScope) -> None:
    if scope == MindspaceScope.ENTERPRISE and not is_admin_request(request):
        raise HTTPException(
            status_code=403,
            detail="Admin privileges required to modify enterprise knowledge.",
        )


def _get_writable_mindspace_doc(
    service: MindspaceService,
    doc_id: str,
    scope: MindspaceScope | None,
    request: Request,
):
    doc = service.get_document(doc_id, scope=scope)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    _require_enterprise_write_allowed(request, doc.scope)
    return doc


def _mindspace_global_root() -> Path:
    return Path(WORKING_DIR) / "mindspace"


def _mindspace_auth_store() -> CloudAuthStore:
    return CloudAuthStore(_mindspace_global_root())


async def _mindspace_service_for_request(request: Request) -> MindspaceService:
    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir).resolve()
    agent_id = getattr(workspace, "id", None) or workspace_dir.name
    auth_store = _mindspace_auth_store()
    return MindspaceService(
        global_root=_mindspace_global_root(),
        agent_workspace=workspace_dir,
        agent_id=str(agent_id),
        user_id=current_user_id(request),
        connectors=CloudConnectorRegistry(auth_store=auth_store),
    )


async def _enqueue_mindspace_document(
    service: MindspaceService,
    doc: MindspaceDoc,
    *,
    operation: KnowledgeJobOperation,
) -> dict:
    try:
        job_id = await enqueue_knowledge_job(
            service,
            doc,
            operation=operation,
        )
    except Exception as exc:
        await asyncio.to_thread(
            service.mark_document_failed,
            doc.id,
            scope=doc.scope,
            failed_stage="queue",
            error=f"Knowledge background queue is unavailable: {exc}",
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "Knowledge background queue is unavailable. "
                "Please retry later."
            ),
        ) from exc
    payload = doc.to_api_dict()
    payload.update({"accepted": True, "job_id": job_id})
    return payload


def _get_cloud_docs_file(workspace_dir: Path) -> Path:
    """Get the cloud docs list file location."""
    return workspace_dir / "cloud_docs.json"


def _load_cloud_docs_state(workspace_dir: Path) -> list[dict]:
    """Load or initialize cloud documents list state."""
    file_path = _get_cloud_docs_file(workspace_dir)
    if not file_path.exists():
        default_docs = []
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(default_docs, f, ensure_ascii=False, indent=2)
            return default_docs
        except Exception:
            return default_docs
            
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_cloud_docs_state(workspace_dir: Path, docs: list[dict]) -> None:
    """Save cloud documents state list to file."""
    file_path = _get_cloud_docs_file(workspace_dir)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)


async def _async_rag_sync_task(
    workspace_dir: Path,
    doc_id: str,
    title: str,
    doc_type: str,
    url: str | None = None,
    content: str | None = None
) -> None:
    """Asynchronous background task using LLM to extract wiki concepts."""
    try:
        # Step 1: Update state to syncing
        docs = _load_cloud_docs_state(workspace_dir)
        for doc in docs:
            if doc["id"] == doc_id:
                doc["status"] = "syncing"
                doc["progress"] = 25
                doc["stage"] = 1
                break
        _save_cloud_docs_state(workspace_dir, docs)

        if not content:
            raise ValueError(
                "Document content is required for legacy RAG sync; mock content is not allowed."
            )

        # Initialize LLM
        chat_model, formatter = create_model_and_formatter(BUILTIN_QA_AGENT_ID)
        
        docs = _load_cloud_docs_state(workspace_dir)
        for doc in docs:
            if doc["id"] == doc_id:
                doc["progress"] = 60
                doc["stage"] = 2
                break
        _save_cloud_docs_state(workspace_dir, docs)

        prompt = f"""Please analyze the following document content and extract its core concepts.
Return the result EXACTLY as a JSON array where each object has:
- "concept": string (The core concept name)
- "content": string (A detailed summary and explanation of this concept based on the document)
- "links": list of strings (Other related concept names mentioned in the document)

Document Content:
{content}
"""
        from agentscope.message import Msg
        user_msg = Msg(name="user", role="user", content=prompt)
        response = await chat_model.reply(user_msg)
        response_text = response.text if hasattr(response, 'text') else response.get_text_content()
        
        # Clean up JSON if it contains markdown formatting
        import re
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text)
        if json_match:
            response_text = json_match.group(1)
        
        try:
            concepts = json.loads(response_text)
            if not isinstance(concepts, list):
                concepts = [{"concept": f"{title}_Concept", "content": response_text, "links": []}]
        except json.JSONDecodeError:
            # Fallback mock if JSON parsing fails
            concepts = [
                {"concept": f"{title}_CoreConcept", "content": "Failed to parse LLM JSON, fallback.", "links": []}
            ]

        # Update state to writing
        docs = _load_cloud_docs_state(workspace_dir)
        for doc in docs:
            if doc["id"] == doc_id:
                doc["progress"] = 90
                doc["stage"] = 3
                break
        _save_cloud_docs_state(workspace_dir, docs)

        # Write to memory/wiki/
        wiki_dir = workspace_dir / "memory" / "wiki"
        wiki_dir.mkdir(parents=True, exist_ok=True)
        
        for concept in concepts:
            c_name = concept.get("concept", "Unknown").replace("/", "_")
            c_content = concept.get("content", "")
            c_links = concept.get("links", [])
            
            wiki_text = f"# {c_name}\n\n{c_content}\n\n"
            if c_links:
                wiki_text += "## 相关词条\n"
                for link in c_links:
                    wiki_text += f"- [[{link}]]\n"
                    
            wiki_file = wiki_dir / f"{c_name}.md"
            # Append if exists
            if wiki_file.exists():
                with open(wiki_file, "a", encoding="utf-8") as f:
                    f.write("\n\n---\n\n" + wiki_text)
            else:
                with open(wiki_file, "w", encoding="utf-8") as f:
                    f.write(wiki_text)

        slices = len(concepts)

        # Complete status in cloud_docs.json
        docs = _load_cloud_docs_state(workspace_dir)
        for doc in docs:
            if doc["id"] == doc_id:
                doc["status"] = "ready"
                doc["progress"] = None
                doc["stage"] = None
                doc["slices"] = slices
                doc["updatedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                break
        _save_cloud_docs_state(workspace_dir, docs)

    except Exception as e:
        import traceback
        traceback.print_exc()
        docs = _load_cloud_docs_state(workspace_dir)
        for doc in docs:
            if doc["id"] == doc_id:
                doc["status"] = "failed"
                doc["progress"] = None
                doc["stage"] = None
                break
        _save_cloud_docs_state(workspace_dir, docs)


@router.get(
    "/cloud-docs",
    response_model=list[dict],
    summary="List cloud and shared RAG docs",
    description="Get all Lark, Tencent and local RAG documents."
)
async def list_cloud_documents(
    request: Request,
    scope: str = Query("all", pattern=_scope_query_pattern()),
) -> list[dict]:
    """List cloud documents."""
    try:
        service = await _mindspace_service_for_request(request)
        docs = service.list_documents(_parse_mindspace_scope(scope))
        return [doc.to_api_dict() for doc in docs]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/cloud-docs/link",
    response_model=dict,
    summary="Link new cloud document",
    description="Associate an external Lark or Tencent Doc, pulling standard contents asynchronously."
)
async def link_cloud_document(
    request: Request,
    payload: LinkCloudDocRequest = Body(...),
) -> dict:
    """Link cloud document and start RAG syncing task."""
    try:
        service = await _mindspace_service_for_request(request)
        parsed_scope = _parse_mindspace_scope(payload.scope) or MindspaceScope.PERSONAL
        _require_enterprise_write_allowed(request, parsed_scope)
        doc = service.stage_cloud_document(
            title=payload.title,
            url=payload.url,
            source_type=payload.docType,
            scope=parsed_scope,
            cloud_account_id=payload.cloud_account_id or payload.cloudAccountId,
        )
        return await _enqueue_mindspace_document(service, doc, operation="link")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/cloud-docs/upload",
    response_model=dict,
    summary="Upload local file to RAG knowledge base",
    description="Upload a local PDF, DOCX, TXT, or MD, automatically chunking and vectorizing it."
)
async def upload_cloud_document(
    request: Request,
    file: UploadFile = File(...),
    scope: str = Query("personal", pattern=_scope_query_pattern(allow_all=False)),
) -> dict:
    """Upload local file and start RAG syncing task."""
    try:
        service = await _mindspace_service_for_request(request)
        filename = file.filename or "unknown_file.txt"
        suffix = os.path.splitext(filename)[1].lower().replace(".", "")
        if suffix not in (
            "pdf",
            "docx",
            "pptx",
            "xlsx",
            "xls",
            "csv",
            "md",
            "txt",
            "png",
            "jpg",
            "jpeg",
            "webp",
            "bmp",
            "gif",
            "tiff",
            "tif",
        ):
            raise HTTPException(
                status_code=400,
                detail=f"{suffix.upper() or 'UNKNOWN'} format is not supported.",
            )

        parsed_scope = _parse_mindspace_scope(scope) or MindspaceScope.PERSONAL
        _require_enterprise_write_allowed(request, parsed_scope)
        content_bytes = await file.read()
        doc = await asyncio.to_thread(
            service.stage_local_bytes,
            name=filename,
            source_type=suffix,
            content=content_bytes,
            scope=parsed_scope,
            mime_type=file.content_type,
        )
        return await _enqueue_mindspace_document(service, doc, operation="ingest")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/cloud-docs/sync",
    response_model=dict,
    summary="Re-sync and trigger RAG vector extraction",
    description="Manually trigger indexing and vector reconstruction for a specific doc."
)
async def sync_cloud_document(
    request: Request,
    payload: SyncCloudDocRequest = Body(...),
) -> dict:
    """Manually restart sync process for a document."""
    try:
        service = await _mindspace_service_for_request(request)
        parsed_scope = _parse_mindspace_scope(payload.scope)
        _get_writable_mindspace_doc(service, payload.id, parsed_scope, request)
        doc = await asyncio.to_thread(
            service.mark_document_queued,
            payload.id,
            scope=parsed_scope,
            operation="resync",
        )
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        return await _enqueue_mindspace_document(service, doc, operation="resync")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete(
    "/cloud-docs/{doc_id}",
    response_model=dict,
    summary="Remove document from RAG shared library",
    description="Delete local state and physical .md RAG files securely."
)
async def delete_cloud_document(
    doc_id: str,
    request: Request,
    scope: str = Query("all", pattern=_scope_query_pattern()),
) -> dict:
    """Delete document from state and clean up memory folder."""
    try:
        service = await _mindspace_service_for_request(request)
        parsed_scope = _parse_mindspace_scope(scope)
        _get_writable_mindspace_doc(service, doc_id, parsed_scope, request)
        deleted = service.delete_document(doc_id, scope=parsed_scope)
        if not deleted:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"deleted": True, "id": doc_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/mindspace/search",
    summary="Search Mindspace knowledge",
)
async def search_mindspace(
    request: Request,
    q: str = Query(..., min_length=1),
    scope: str = Query("all", pattern=_scope_query_pattern()),
    top_k: int = Query(5, ge=1, le=20),
    min_score: float = Query(0.15, ge=0, le=1),
) -> dict:
    try:
        service = await _mindspace_service_for_request(request)
        hits = service.search(
            q,
            scope=_parse_mindspace_scope(scope),
            top_k=top_k,
            min_score=min_score,
        )
        return {
            "hits": [hit.to_dict() for hit in hits],
            **service.search_capabilities(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/mindspace/docs/{doc_id}",
    summary="Read a Mindspace document and its chunks",
)
async def read_mindspace_document(
    doc_id: str,
    request: Request,
    scope: str = Query("all", pattern=_scope_query_pattern()),
) -> dict:
    try:
        service = await _mindspace_service_for_request(request)
        payload = service.read_document(doc_id, scope=_parse_mindspace_scope(scope))
        if payload is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return payload
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/mindspace/connectors",
    summary="List Mindspace connector configuration status",
)
async def list_mindspace_connectors(request: Request) -> dict:
    try:
        service = await _mindspace_service_for_request(request)
        return {"connectors": service.connector_status()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put(
    "/mindspace/connectors/{provider}",
    summary="Update Mindspace connector configuration metadata",
)
async def update_mindspace_connector(provider: str) -> dict:
    return {
        "provider": provider,
        "updated": False,
        "message": "Connector credentials are configured through environment variables or official connector endpoints.",
    }


@router.get(
    "/knowledge/docs",
    response_model=list[dict],
    summary="List enterprise and personal knowledge documents",
)
async def list_knowledge_documents(
    request: Request,
    scope: str = Query("all", pattern=_scope_query_pattern()),
    category: str | None = Query(None, max_length=64),
    tags: str | None = Query(None, max_length=512),
) -> list[dict]:
    service = await _mindspace_service_for_request(request)
    docs = service.list_documents(
        _parse_mindspace_scope(scope),
        category=category,
        tags=normalize_knowledge_tags(tags),
    )
    return [doc.to_api_dict() for doc in docs]


@router.get(
    "/knowledge/capabilities",
    summary="Describe current knowledge search capabilities",
)
async def knowledge_capabilities(request: Request) -> dict:
    service = await _mindspace_service_for_request(request)
    return service.search_capabilities()


@router.post(
    "/knowledge/upload",
    response_model=dict,
    summary="Upload a local file to the knowledge base",
)
async def upload_knowledge_document(
    request: Request,
    file: UploadFile = File(...),
    scope: str = Query("personal", pattern=_scope_query_pattern(allow_all=False)),
    category: str = Query("uncategorized", max_length=64),
    tags: str | None = Query(None, max_length=512),
) -> dict:
    service = await _mindspace_service_for_request(request)
    parsed_scope = _parse_mindspace_scope(scope) or MindspaceScope.PERSONAL
    _require_enterprise_write_allowed(request, parsed_scope)
    filename = file.filename or "unknown_file.txt"
    suffix = os.path.splitext(filename)[1].lower().replace(".", "") or "txt"
    content = await file.read()
    doc = await asyncio.to_thread(
        service.stage_local_bytes,
        name=filename,
        source_type=suffix,
        content=content,
        scope=parsed_scope,
        mime_type=file.content_type,
        category=normalize_knowledge_category(category),
        tags=normalize_knowledge_tags(tags),
    )
    return await _enqueue_mindspace_document(service, doc, operation="ingest")


@router.post(
    "/knowledge/link",
    response_model=dict,
    summary="Link a cloud document to the knowledge base",
)
async def link_knowledge_document(
    request: Request,
    payload: LinkCloudDocRequest = Body(...),
) -> dict:
    service = await _mindspace_service_for_request(request)
    parsed_scope = _parse_mindspace_scope(payload.scope) or MindspaceScope.PERSONAL
    _require_enterprise_write_allowed(request, parsed_scope)
    doc = service.stage_cloud_document(
        title=payload.title,
        url=payload.url,
        source_type=payload.docType,
        scope=parsed_scope,
        cloud_account_id=payload.cloud_account_id or payload.cloudAccountId,
        category=payload.category,
        tags=payload.tags,
    )
    return await _enqueue_mindspace_document(service, doc, operation="link")


@router.post(
    "/knowledge/sync",
    response_model=dict,
    summary="Resync a knowledge document",
)
async def sync_knowledge_document(
    request: Request,
    payload: SyncCloudDocRequest = Body(...),
) -> dict:
    service = await _mindspace_service_for_request(request)
    parsed_scope = _parse_mindspace_scope(payload.scope)
    _get_writable_mindspace_doc(service, payload.id, parsed_scope, request)
    doc = await asyncio.to_thread(
        service.mark_document_queued,
        payload.id,
        scope=parsed_scope,
        operation="resync",
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return await _enqueue_mindspace_document(service, doc, operation="resync")


@router.delete(
    "/knowledge/docs/{doc_id}",
    response_model=dict,
    summary="Delete a knowledge document and its derived index",
)
async def delete_knowledge_document(
    doc_id: str,
    request: Request,
    scope: str = Query("all", pattern=_scope_query_pattern()),
) -> dict:
    service = await _mindspace_service_for_request(request)
    parsed_scope = _parse_mindspace_scope(scope)
    _get_writable_mindspace_doc(service, doc_id, parsed_scope, request)
    deleted = service.delete_document(doc_id, scope=parsed_scope)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": True, "id": doc_id}


@router.patch(
    "/knowledge/docs/{doc_id}/metadata",
    response_model=dict,
    summary="Update knowledge classification metadata",
)
async def update_knowledge_document_metadata(
    doc_id: str,
    request: Request,
    payload: KnowledgeMetadataRequest = Body(...),
    scope: str = Query("all", pattern=_scope_query_pattern()),
) -> dict:
    service = await _mindspace_service_for_request(request)
    parsed_scope = _parse_mindspace_scope(scope)
    _get_writable_mindspace_doc(service, doc_id, parsed_scope, request)
    doc = service.update_document_metadata(
        doc_id,
        scope=parsed_scope,
        category=payload.category,
        tags=payload.tags,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc.to_api_dict()


@router.get(
    "/knowledge/search",
    summary="Search enterprise and personal knowledge",
)
async def search_knowledge(
    request: Request,
    q: str = Query(..., min_length=1),
    scope: str = Query("all", pattern=_scope_query_pattern()),
    top_k: int = Query(5, ge=1, le=20),
    min_score: float = Query(0.15, ge=0, le=1),
    category: str | None = Query(None, max_length=64),
    tags: str | None = Query(None, max_length=512),
) -> dict:
    service = await _mindspace_service_for_request(request)
    hits = service.search(
        q,
        scope=_parse_mindspace_scope(scope),
        top_k=top_k,
        min_score=min_score,
        category=category,
        tags=normalize_knowledge_tags(tags),
    )
    return {
        "hits": [hit.to_dict() for hit in hits],
        **service.search_capabilities(),
    }


@router.get(
    "/knowledge/docs/{doc_id}",
    summary="Read a knowledge document and its chunks",
)
async def read_knowledge_document(
    doc_id: str,
    request: Request,
    scope: str = Query("all", pattern=_scope_query_pattern()),
) -> dict:
    service = await _mindspace_service_for_request(request)
    payload = service.read_document(doc_id, scope=_parse_mindspace_scope(scope))
    if payload is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return payload


# ---------------------------------------------------------------------------
# Workspace Sidebar Core APIs (Products / All Files / Changes / Web Browser)
# ---------------------------------------------------------------------------


@router.get(
    "/all-files",
    summary="List all files in workspace recursively",
    description="Get hierarchical structure of all files in current agent workspace directory"
)
async def list_all_files_tree(request: Request) -> list[dict]:
    """Recursively list all files and subdirectories as a structured tree."""
    from ...agents.memory.agent_md_manager import AgentMdManager
    try:
        workspace = await get_agent_for_request(request)
        requested_chat_id = _request_chat_id(request)
        _require_chat_context_for_user(request, requested_chat_id)
        root_workspace_dir = Path(workspace.workspace_dir).resolve()
        owned_chat_id = _normalize_owned_chat_id(request, requested_chat_id)
        explicit_files = _explicit_artifact_files_for_chat(
            owned_chat_id,
            root_workspace_dir,
        )
        workspace_dir = get_workspace_dir_for_request(
            request,
            root_workspace_dir,
            chat_id_override=requested_chat_id,
        )
        
        if not workspace_dir.exists():
            return []
            
        def _build_file_tree(dir_path: Path, base_dir: Path) -> list[dict]:
            nodes = []
            try:
                for entry in sorted(dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
                    # Skip noise/ignored dirs/files
                    if entry.name in {
                        ".git", "__pycache__", "node_modules", "venv", ".pytest_cache", ".DS_Store",
                        "skills", "skill.json", "skills.json", "backup", "file_store", "renders", ".thumbnails"
                    } or entry.name.startswith(".skill") or entry.name.endswith(".lock") or (entry.name.startswith(".") and entry.name not in {".github", ".vscode", ".env", ".gitignore"}):
                        continue
                    
                    # Skip binary/media files
                    if entry.is_file() and entry.suffix.lower() in {
                        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico", ".svg",
                        ".mp4", ".mov", ".avi", ".mkv", ".webm",
                        ".mp3", ".wav", ".ogg", ".flac",
                        ".bin", ".exe", ".dll", ".so", ".dylib", ".class", ".pyc",
                        ".pdf", ".zip", ".tar", ".gz", ".rar", ".7z"
                    }:
                        continue
                    
                    rel_path = entry.relative_to(base_dir).as_posix()
                    node = {
                        "name": entry.name,
                        "path": rel_path,
                        "isDir": entry.is_dir(),
                    }
                    if entry.is_dir():
                        child_nodes = _build_file_tree(entry, base_dir)
                        node["children"] = child_nodes
                    else:
                        node["size"] = entry.stat().st_size
                        node["modifiedTime"] = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc).isoformat()
                    nodes.append(node)
            except Exception:
                pass
            return nodes

        tree = _build_file_tree(workspace_dir, workspace_dir)
        existing_paths = {
            node.get("path")
            for node in tree
            if isinstance(node, dict) and isinstance(node.get("path"), str)
        }
        for rel_path in explicit_files:
            if rel_path in existing_paths:
                continue
            info = _file_info_for_workspace_path(workspace_dir.resolve(), rel_path)
            if not info:
                continue
            tree.append(
                {
                    "name": Path(rel_path).name,
                    "path": rel_path,
                    "isDir": False,
                    "size": info.size,
                    "modifiedTime": info.modified_time,
                },
            )
        return tree
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/files/raw/{file_path:path}",
    summary="Read any file content in workspace",
    description="Get the raw text content of any file inside active agent workspace securely"
)
async def read_raw_file_content(file_path: str, request: Request) -> dict:
    """Read raw content of any workspace text file safely."""
    try:
        workspace = await get_agent_for_request(request)
        requested_chat_id = _request_chat_id(request)
        _require_chat_context_for_user(request, requested_chat_id)
        workspace_dir = get_workspace_dir_for_request(
            request,
            Path(workspace.workspace_dir).resolve(),
            chat_id_override=requested_chat_id,
        )
        
        # Prevent Path Traversal
        target_path = resolve_workspace_file_for_read(workspace_dir, file_path)
        if not _is_within_directory(target_path, workspace_dir):
            root_workspace = _root_workspace_from_session_dir(workspace_dir)
            if not root_workspace or not _is_within_directory(target_path, root_workspace):
                raise HTTPException(status_code=403, detail="Access denied")
            _assert_root_fallback_allowed(
                request,
                requested_chat_id,
                file_path,
                root_workspace,
            )
            
        if not target_path.exists() or not target_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
            
        # Try to read file safely with utf-8 encoding and fallback
        try:
            with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return {"content": content}
        except Exception as e:
            return {"content": f"[Error: Cannot read non-text or binary file. Raw error: {str(e)}]"}
            
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/changes",
    summary="Get recent file changes and git diffs",
    description="Get list of altered files and raw Git Diff if repo is initialized"
)
async def get_workspace_changes(request: Request) -> list[dict]:
    """Calculate file changes by looking at Git status, falling back to modified files."""
    import subprocess
    import time
    try:
        workspace = await get_agent_for_request(request)
        requested_chat_id = _request_chat_id(request)
        _require_chat_context_for_user(request, requested_chat_id)
        root_workspace_dir = Path(workspace.workspace_dir).resolve()
        owned_chat_id = _normalize_owned_chat_id(request, requested_chat_id)
        explicit_files = _explicit_artifact_files_for_chat(
            owned_chat_id,
            root_workspace_dir,
        )
        workspace_dir = get_workspace_dir_for_request(
            request,
            root_workspace_dir,
            chat_id_override=requested_chat_id,
        )
        
        changes = []
        if not workspace_dir.exists():
            return []
        
        def is_noise_file(filepath: str) -> bool:
            parts = Path(filepath).parts
            if is_internal_task_file(filepath):
                return True
            if any(p in parts for p in {
                ".git", "__pycache__", "node_modules", "venv", ".pytest_cache", ".DS_Store",
                "skills", "skill.json", "skills.json", "logs", ".gemini"
            }):
                return True
            filename = parts[-1] if parts else ""
            if filename.startswith(".skill") or filename.endswith(".lock") or filename in {
                "qwenpaw_app.log", "qwenpaw_app_new.log", "memory_file_metadata.json", "overview.md.lock"
            }:
                return True
            return False

        # Find the ancestor directory that contains .git (Adaptive Ancestry Git Backtracking)
        git_root = None
        curr = workspace_dir
        for _ in range(10):
            if (curr / ".git").is_dir():
                git_root = curr
                break
            if curr.parent == curr:
                break
            curr = curr.parent
            
        # 1. Attempt Git workflow
        if git_root is not None:
            try:
                # Get modified and untracked files from git_root
                res = subprocess.run(
                    ["git", "status", "--porcelain"],
                    cwd=str(git_root),
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if res.returncode == 0:
                    lines = res.stdout.strip().split("\n")
                    for line in lines:
                        if not line:
                            continue
                        # e.g., " M src/index.ts" or "?? newfile.md"
                        status_part = line[:2]
                        filepath_git_root = line[2:].strip().strip('"')
                        
                        # Check if this file belongs to our workspace_dir
                        full_path = git_root / filepath_git_root
                        try:
                            # Try to make it relative to workspace_dir
                            rel_to_workspace = full_path.relative_to(workspace_dir)
                            filepath_workspace = rel_to_workspace.as_posix()
                        except ValueError:
                            # Not in workspace_dir
                            continue
                        
                        # Apply noise filtering
                        if is_noise_file(filepath_workspace):
                            continue
                        
                        # Get diff content
                        diff_content = ""
                        if "M" in status_part or "A" in status_part:
                            diff_res = subprocess.run(
                                ["git", "diff", filepath_git_root],
                                cwd=str(git_root),
                                capture_output=True,
                                text=True,
                                timeout=5
                            )
                            if diff_res.returncode == 0:
                                diff_content = diff_res.stdout
                                
                        changes.append({
                            "filepath": filepath_workspace,
                            "status": status_part.strip(),
                            "diff": diff_content or f"+++ {filepath_workspace}\n(No diff output or untracked changes)"
                        })
                    existing = {item["filepath"] for item in changes}
                    for rel_path in explicit_files:
                        if rel_path in existing:
                            continue
                        info = _file_info_for_workspace_path(workspace_dir, rel_path)
                        if not info:
                            continue
                        changes.append(
                            {
                                "filepath": rel_path,
                                "status": "A",
                                "diff": (
                                    f"+++ {rel_path}\n"
                                    "Task artifact explicitly produced by this chat."
                                ),
                            },
                        )
                    return changes
            except Exception as e:
                logger.warning("Git status/diff failed in git_root %s: %s", git_root, e)
                
        # 2. Fallback workflow: scan files modified in last 1 hour
        try:
            for entry in workspace_dir.rglob("*"):
                if not entry.is_file():
                    continue
                # Skip ignored items
                if any(ignored in entry.parts for ignored in {".git", "__pycache__", "node_modules", "venv", ".pytest_cache"}):
                    continue
                
                mtime = entry.stat().st_mtime
                age_seconds = time.time() - mtime
                if age_seconds < 3600:  # 1 hour
                    rel_path = entry.relative_to(workspace_dir).as_posix()
                    
                    # Apply noise filtering
                    if is_noise_file(rel_path):
                        continue
                        
                    changes.append({
                        "filepath": rel_path,
                        "status": "M",
                        "diff": f"+++ {rel_path}\nModified: {datetime.fromtimestamp(mtime).isoformat()} ({int(age_seconds/60)} minutes ago)"
                    })
        except Exception:
            pass
            
        existing = {item["filepath"] for item in changes}
        for rel_path in explicit_files:
            if rel_path in existing:
                continue
            info = _file_info_for_workspace_path(workspace_dir, rel_path)
            if not info:
                continue
            changes.append(
                {
                    "filepath": rel_path,
                    "status": "A",
                    "diff": (
                        f"+++ {rel_path}\n"
                        "Task artifact explicitly produced by this chat."
                    ),
                },
            )
        return changes
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/artifacts",
    response_model=list[MdFileInfo],
    summary="List actual workspace artifacts (task outputs)",
    description="Get a list of actual deliverables (HTML, script, assets, etc.) produced by tasks, filtering out core system configs and developer dependencies."
)
async def list_workspace_artifacts(
    request: Request,
    session_id: str | None = None,
    agent_id: str | None = None,
) -> list[MdFileInfo]:
    """Recursively list all actual deliverables (artifacts) in workspace, filtering out system noise."""
    try:
        requested_chat_id = _request_chat_id(request) or session_id
        _assert_owned_chat_agent_context(request, requested_chat_id, agent_id)
        if agent_id:
            workspace = await get_agent_for_request(request, agent_id=agent_id)
        else:
            workspace = await get_agent_for_request(request)
        _require_chat_context_for_user(request, requested_chat_id)
        root_workspace_dir = Path(workspace.workspace_dir).resolve()
        owned_chat_id = _normalize_owned_chat_id(request, requested_chat_id)
        explicit_files = _explicit_artifact_files_for_chat(
            owned_chat_id,
            root_workspace_dir,
        )
        workspace_dir = get_workspace_dir_for_request(
            request,
            root_workspace_dir,
            chat_id_override=requested_chat_id,
        )
        
        # An owned sessions_data/<session> directory is already isolated to the
        # authenticated chat, so it is safe (and necessary) to scan it directly.
        # Shared/root workspaces must still rely on explicit chat evidence for
        # user-scoped requests to avoid exposing files from another task.
        is_session_workspace = "sessions_data" in workspace_dir.parts
        if is_session_workspace:
            session_id = None
            
        if not workspace_dir.exists():
            return []
            
        artifacts = []
        user_scoped = _user_requires_chat_context(request)
        
        # 1. Gather dynamic memory dir from agent if possible to prevent hardcoding only "memory"
        ignored_dirs = {
            ".git", ".github", "__pycache__", "node_modules", "venv", 
            ".pytest_cache", ".DS_Store", "logs", "missions", ".gemini",
            "src", "console", "tests", "deploy", "plugins", "scripts", "website",
            "file_store", "sessions", "dialog", "embedding_cache", "backup", "media", "browser", "tool_result", "cloud_docs",
            "skills"
        }
        try:
            from ...config.config import load_agent_config
            agent_config = load_agent_config(workspace.agent_id)
            if agent_config and agent_config.running and agent_config.running.daily_memory_dir:
                ignored_dirs.add(agent_config.running.daily_memory_dir)
        except Exception:
            pass
        ignored_dirs.add("memory")
        
        ignored_files = {
            # System config markdown files
            "BOOTSTRAP.md", "MEMORY.md", "PROFILE.md", "SOUL.md", "HEARTBEAT.md", "AGENTS.md",
            "AGENT_STANDARD.md", "SKILL_STANDARD.md", "STARTUP.md", "chats.json",
            "qwenpaw_app.log", "qwenpaw_app_new.log", "memory_file_metadata.json", "skills.json",
            "token_usage.json", "config.json", "jobs.json", "agent.json", "cloud_docs.json",
            ".bootstrap_completed", ".reme_store_v1", ".skill.json.lock", "skill.json",
            # General developer files we want to filter out since they belong to framework repo
            "pyproject.toml", "setup.py", "Makefile", "LICENSE", "init_experts.py", "docker-compose.yml",
            ".dockerignore", ".flake8", ".gitattributes", ".gitignore", ".pre-commit-config.yaml", ".python-version",
            "README.md", "README_ja.md", "README_ru.md", "README_zh.md", "CONTRIBUTING.md", "CONTRIBUTING_zh.md", "SECURITY.md"
        }

        # 2. Extract specific deliverables if session_id is provided
        session_files = set()
        has_session_isolation = False
        
        if session_id:
            sessions_dir = workspace_dir / "sessions"
            if sessions_dir.exists():
                session_path = None
                
                # 2a. Try direct filename match: session file named *{session_id}.json
                for p in sessions_dir.rglob("*.json"):
                    if p.name.endswith(f"{session_id}.json"):
                        session_path = p
                        break
                
                # 2b. If direct match failed, session_id might be a chat UUID.
                #     Resolve it via chats.json → real session_id (timestamp).
                if not session_path:
                    resolved_session_id = resolve_session_id_for_chat_id(
                        session_id,
                        workspace_dir,
                    )
                    
                    if resolved_session_id and resolved_session_id != session_id:
                        for p in sessions_dir.rglob("*.json"):
                            if p.name.endswith(f"{resolved_session_id}.json"):
                                session_path = p
                                break
                
                if session_path and session_path.exists():
                    try:
                        with open(session_path, "r", encoding="utf-8", errors="replace") as f:
                            session_data = json.load(f)
                            
                        # Robust recursive scanner to gather all file paths edited/written
                        def extract_paths(obj):
                            if isinstance(obj, dict):
                                for k, v in obj.items():
                                    if k in ["file_path", "TargetFile", "fileName", "filepath", "filename", "path", "file", "AbsolutePath"]:
                                        if isinstance(v, str) and v.strip():
                                            p = v.strip()
                                            if p.startswith("/"):
                                                try:
                                                    p = Path(p).relative_to(workspace_dir).as_posix()
                                                except ValueError:
                                                    p = Path(p).name
                                            if p.startswith("./"):
                                                p = p[2:]
                                            session_files.add(p)
                                    else:
                                        if isinstance(v, str) and v.strip().startswith("{") and v.strip().endswith("}"):
                                            try:
                                                parsed_v = json.loads(v)
                                                extract_paths(parsed_v)
                                            except Exception:
                                                pass
                                        extract_paths(v)
                            elif isinstance(obj, list):
                                for item in obj:
                                    extract_paths(item)
                                    
                        extract_paths(session_data)
                        has_session_isolation = True
                    except Exception:
                        pass

        # 3. Build artifact results from session isolated file set
        if has_session_isolation:
            for rel_path in session_files:
                entry = (workspace_dir / rel_path).resolve()
                if not entry.exists() or not entry.is_file():
                    continue
                
                # Security sanity check
                if not _is_within_directory(entry, workspace_dir):
                    continue
                    
                try:
                    rel_parts = entry.relative_to(workspace_dir).parts
                except Exception:
                    continue
                    
                if any(part in ignored_dirs for part in rel_parts[:-1]):
                    continue
                if any(part.startswith(".") for part in rel_parts[:-1]):
                    continue
                if entry.name in ignored_files or entry.name.startswith("."):
                    continue
                if is_internal_task_file(rel_path):
                    continue
                    
                stat = entry.stat()
                artifacts.append(
                    MdFileInfo(
                        filename=rel_path,
                        path=rel_path,
                        size=stat.st_size,
                        created_time=datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
                        modified_time=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
                    )
                )

        # 4. Fallback: recursively scan the entire isolated session workspace,
        # or a shared workspace only for non-user-scoped requests.
        if not has_session_isolation and (
            is_session_workspace or not user_scoped
        ):
            for entry in workspace_dir.rglob("*"):
                if not entry.is_file():
                    continue
                
                try:
                    rel_parts = entry.relative_to(workspace_dir).parts
                except Exception:
                    continue
                    
                # Filter directories
                if any(part in ignored_dirs for part in rel_parts[:-1]):
                    continue
                if any(part.startswith(".") for part in rel_parts[:-1]):
                    continue
                    
                # Filter files
                filename = entry.name
                if filename in ignored_files or filename.startswith("."):
                    continue
                    
                rel_path = entry.relative_to(workspace_dir).as_posix()
                if is_internal_task_file(rel_path):
                    continue
                
                stat = entry.stat()
                artifacts.append(
                    MdFileInfo(
                        filename=rel_path,
                        path=rel_path,
                        size=stat.st_size,
                        created_time=datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc).isoformat(),
                        modified_time=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
                    )
                )

        existing_artifact_paths = {artifact.path for artifact in artifacts}
        for rel_path in explicit_files:
            if rel_path in existing_artifact_paths:
                continue
            info = _file_info_for_workspace_path(workspace_dir, rel_path)
            if info:
                artifacts.append(info)
            
        # Sort artifacts by modified time descending (newest first)
        artifacts.sort(key=lambda x: x.modified_time, reverse=True)
        return artifacts
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/preview/{file_path:path}",
    summary="Static file server for workspace browser preview",
    description="Stream any workspace file as a static resource with correct content-type for previewing"
)
async def preview_workspace_file(file_path: str, request: Request):
    """Stream workspace static files to iframe preview container securely."""
    from fastapi.responses import FileResponse
    import mimetypes
    try:
        context_agent_id, context_chat_id, file_path = parse_preview_context_path(file_path)
        workspace = await get_agent_for_request(request, agent_id=context_agent_id)
        requested_chat_id = context_chat_id or _request_chat_id(request)
        _require_chat_context_for_user(request, requested_chat_id)
        workspace_dir = get_workspace_dir_for_request(
            request,
            Path(workspace.workspace_dir).resolve(),
            chat_id_override=requested_chat_id,
        )
        
        # Prevent Path Traversal
        target_path = resolve_workspace_file_for_read(workspace_dir, file_path)
        if not _is_within_directory(target_path, workspace_dir):
            root_workspace = _root_workspace_from_session_dir(workspace_dir)
            if not root_workspace or not _is_within_directory(target_path, root_workspace):
                raise HTTPException(status_code=403, detail="Access denied")
            _assert_root_fallback_allowed(
                request,
                requested_chat_id,
                file_path,
                root_workspace,
            )
            
        # High-robustness smart fallback for folder or missing HTML files
        is_dir = target_path.is_dir()
        is_missing_html = not target_path.exists() and (
            target_path.suffix.lower() == ".html" or target_path.name.lower() == "index.html"
        )
        
        if is_dir or is_missing_html:
            search_dir = target_path if is_dir else target_path.parent
            if search_dir.exists() and search_dir.is_dir():
                try:
                    index_file = search_dir / "index.html"
                    if index_file.is_file():
                        target_path = index_file
                    else:
                        html_files = [
                            f for f in search_dir.iterdir()
                            if f.is_file() and f.suffix.lower() == ".html" and f.name.lower() != "index.html"
                        ]
                        if html_files:
                            # Sort by modification time descending (newest first)
                            html_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                            
                            # Prioritize game/play/app/main patterns
                            game_file = None
                            for f in html_files:
                                fname_lower = f.name.lower()
                                if any(k in fname_lower for k in ["game", "play", "app", "main"]):
                                    game_file = f
                                    break
                            
                            target_path = game_file if game_file else html_files[0]
                except Exception:
                    pass

        if not target_path.exists() or not target_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
            
        # Guess mime type
        mime_type, _ = mimetypes.guess_type(target_path)
        if not mime_type:
            mime_type = "application/octet-stream"
            
        return FileResponse(target_path, media_type=mime_type)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/merge-to-main",
    summary="Merge session isolated workspace back to main",
    description="Merge modifications and newly created files in session isolated workspace back to main workspace trunk"
)
async def merge_session_to_main(
    request: Request,
    body: dict = Body(...)
) -> dict:
    """Merge files from session sandbox directory to the main workspace directory."""
    import shutil
    try:
        chat_id = body.get("chatId") or body.get("session_id")
        if not chat_id:
            raise HTTPException(status_code=400, detail="Missing chatId or session_id in request body")
            
        workspace = await get_agent_for_request(request)
        main_dir = Path(workspace.workspace_dir).resolve()
        chat_row = ensure_chat_access(request, chat_id)
        session_id = str(chat_row["session_id"] or chat_row["id"])
        session_dir = main_dir / "sessions_data" / session_id
        
        if not session_dir.exists():
            return {"merged": False, "reason": "Session sandbox directory does not exist", "files": []}
            
        merged_files = []
        # Directories to exclude
        excluded_dirs = {".git", "node_modules", "venv", "__pycache__", ".pytest_cache", ".DS_Store"}
        # Exclude system markdown board files to avoid polluting main project board
        excluded_files = {"task.md", "implementation_plan.md", "walkthrough.md", "workbuddy_analysis.md"}
        
        for entry in session_dir.rglob("*"):
            if entry.is_dir():
                continue
            # Skip symlink to avoid copying dependencies
            if entry.is_symlink():
                continue
            # Skip if any path part matches excluded directories
            if any(part in entry.parts for part in excluded_dirs):
                continue
            
            rel_path = entry.relative_to(session_dir)
            # Extra safety check to prevent sessions_data folder itself from being merged
            if any(part == "sessions_data" for part in rel_path.parts):
                continue
            if entry.name in excluded_files:
                continue
                
            target_path = (main_dir / rel_path).resolve()
            # Double check path traversal safety
            if not _is_within_directory(target_path, main_dir):
                continue
                
            # Create parent directories in trunk if missing
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy file contents and metadata
            shutil.copy2(entry, target_path)
            merged_files.append(rel_path.as_posix())
            
        logger.info(f"Successfully merged {len(merged_files)} files from session {chat_id} to main workspace")
        return {"merged": True, "files": merged_files}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/wiki/list",
    summary="List all LLM-Wiki concepts",
)
async def list_wiki_concepts(
    request: Request,
    scope: str = Query("all", pattern=_scope_query_pattern()),
) -> dict:
    try:
        service = await _mindspace_service_for_request(request)
        return {"concepts": service.list_wiki(scope=_parse_mindspace_scope(scope))}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/wiki/{concept}",
    summary="Get content of a specific LLM-Wiki concept",
)
async def get_wiki_concept(
    request: Request,
    concept: str,
    scope: str = Query("personal", pattern=_scope_query_pattern(allow_all=False)),
) -> dict:
    try:
        service = await _mindspace_service_for_request(request)
        parsed_scope = _parse_mindspace_scope(scope) or MindspaceScope.PERSONAL
        content = service.read_wiki(concept, parsed_scope)
        if content is None:
            raise HTTPException(status_code=404, detail=f"Concept {concept} not found")
        return {"concept": concept, "content": content, "scope": parsed_scope.value}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
