# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, HTTPException, Request

from ...config.utils import load_config
from ...security.tool_guard.approval import ApprovalDecision
from ..agent_context import get_agent_for_request
from ..approvals import get_approval_service
from ..chat_access import current_user_id, ensure_chat_access
from ..mobile.models import (
    MobileArtifactSummary,
    MobileConfirmationActionResponse,
    MobilePendingConfirmation,
    MobileTaskDetailResponse,
    MobileTaskSummary,
    MobileWorkbenchResponse,
)
from ..mobile.service import (
    derive_mobile_display_status,
    serialize_artifact_summary,
    serialize_pending_confirmation,
)
from ..runner.api import get_chat as get_runner_chat
from ..runner.models import ChatSpec, ChatUpdate
from ..storage.repos.chat_list_repo import get_chat_list_repository
from .workspace import list_workspace_artifacts

router = APIRouter(prefix="/mobile", tags=["mobile"])


@dataclass
class _MobileTaskSource:
    chat: ChatSpec
    workspace: Any
    agent_id: str | None = None
    artifact_agent_id: str | None = None
    message_count: int | None = None


async def _visible_pending_approvals(request: Request) -> list:
    approval_svc = get_approval_service()
    pending = await approval_svc.list_all_pending()
    visible = []

    for item in pending:
        try:
            ensure_chat_access(
                request,
                item.root_session_id,
                allow_admin=False,
            )
        except HTTPException:
            continue
        visible.append(item)

    return visible


def _count_pending_by_root(pending: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in pending:
        root_session_id = str(getattr(item, "root_session_id", "") or "")
        if not root_session_id:
            continue
        counts[root_session_id] = counts.get(root_session_id, 0) + 1
    return counts


def _timestamp(value) -> float | None:
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _message_type(message: dict) -> str:
    msg_type = message.get("type")
    if isinstance(msg_type, str):
        return msg_type
    if msg_type is None:
        return ""
    return str(getattr(msg_type, "value", msg_type))


def _is_mobile_visible_message(message: dict) -> bool:
    msg_type = _message_type(message)
    return msg_type in {"", "message"}


def _serialize_mobile_message(message) -> dict | None:
    if isinstance(message, dict):
        return dict(message)
    if hasattr(message, "model_dump"):
        return message.model_dump(mode="json")
    if hasattr(message, "dict"):
        return message.dict()
    return None


def _mobile_message_text(message: dict) -> str | None:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return None

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"])
    return "\n".join(part for part in parts if part) if parts else None


def _mobile_message_has_non_text_content(message: dict) -> bool:
    content = message.get("content")
    if not isinstance(content, list):
        return False
    for item in content:
        if isinstance(item, str):
            continue
        if not isinstance(item, dict):
            return True
        item_type = str(item.get("type") or "")
        if item_type not in {"", "text"} or not isinstance(
            item.get("text"),
            str,
        ):
            return True
    return False


def _merge_adjacent_mobile_assistant_message(
    previous: dict,
    current: dict,
) -> bool:
    if _message_role(previous) != "assistant" or _message_role(current) != "assistant":
        return False
    if _mobile_message_has_non_text_content(
        previous,
    ) or _mobile_message_has_non_text_content(current):
        return False
    previous_text = _mobile_message_text(previous)
    current_text = _mobile_message_text(current)
    if not previous_text or not current_text:
        return False
    previous["content"] = f"{previous_text.rstrip()}\n\n{current_text.lstrip()}"
    return True


def _serialize_mobile_messages(messages: list) -> list[dict]:
    serialized: list[dict] = []
    for message in messages:
        item = _serialize_mobile_message(message)
        if item is None or not _is_mobile_visible_message(item):
            continue
        if serialized and _merge_adjacent_mobile_assistant_message(serialized[-1], item):
            continue
        serialized.append(item)
    return serialized


def _mobile_session_media_reference(
    value: Any,
    session_workspace: Path,
) -> Any:
    if not isinstance(value, str) or not value:
        return value
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https", "data", "blob", "wxfile"}:
        return value
    raw_path = unquote(parsed.path) if parsed.scheme == "file" else value
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        return value
    try:
        return (
            candidate.resolve()
            .relative_to(session_workspace.resolve())
            .as_posix()
        )
    except ValueError:
        return value


def _normalize_mobile_message_media_paths(
    messages: list[dict],
    workspace,
    session_id: str,
) -> list[dict]:
    workspace_dir = getattr(workspace, "workspace_dir", None)
    if not workspace_dir:
        return messages
    root_workspace = Path(workspace_dir).resolve()
    session_workspace = root_workspace / "sessions_data" / session_id
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").lower()
            if "image" not in item_type:
                continue
            for key in ("image_url", "path", "file_path"):
                if key in item:
                    item[key] = _mobile_session_media_reference(
                        item[key],
                        session_workspace,
                    )
            source = item.get("source")
            if isinstance(source, dict):
                for key in ("url", "path", "file_path"):
                    if key in source:
                        source[key] = _mobile_session_media_reference(
                            source[key],
                            session_workspace,
                        )
    return messages


def _message_role(message: dict) -> str:
    role = message.get("role")
    if isinstance(role, str):
        return role
    return ""


def _has_assistant_response(messages: list[dict]) -> bool:
    return any(_message_role(message) == "assistant" for message in messages)


def _chat_meta(chat) -> dict:
    meta = getattr(chat, "meta", None)
    return meta if isinstance(meta, dict) else {}


def _meta_is_archived(meta: dict) -> bool:
    return bool(meta.get("archived_at") or meta.get("archived") is True)


def _chat_is_archived(chat) -> bool:
    return _meta_is_archived(_chat_meta(chat))


def _chat_agent_id(chat) -> str | None:
    agent_id = _chat_meta(chat).get("agent_id")
    return str(agent_id) if agent_id else None


def _chat_expert_team_id(chat) -> str | None:
    expert_team_id = _chat_meta(chat).get("expert_team_id")
    return str(expert_team_id) if expert_team_id else None


def _chat_active_mode(chat) -> str | None:
    meta = _chat_meta(chat)
    if "active_mode" not in meta:
        return None
    active_mode = meta.get("active_mode")
    return str(active_mode) if active_mode is not None else None


def _request_has_multi_agent_manager(request: Request) -> bool:
    app = getattr(request, "app", None)
    state = getattr(app, "state", None)
    return hasattr(state, "multi_agent_manager")


def _enabled_agent_ids() -> list[str]:
    config = load_config()
    return [
        agent_id
        for agent_id, agent_ref in config.agents.profiles.items()
        if getattr(agent_ref, "enabled", True)
    ]


def _row_meta(row: dict) -> dict:
    raw_meta = row.get("meta")
    if isinstance(raw_meta, dict):
        return dict(raw_meta)
    if raw_meta:
        try:
            parsed = json.loads(str(raw_meta))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _row_agent_id(row: dict) -> str | None:
    agent_id = row.get("agent_id") or _row_meta(row).get("agent_id")
    return str(agent_id) if agent_id else None


def _row_message_count(row: dict) -> int:
    try:
        return int(row.get("message_count") or 0)
    except (TypeError, ValueError):
        return 0


def _is_visible_mobile_task_row(row: dict) -> bool:
    chat_id = str(row.get("id") or "").strip()
    if not chat_id or chat_id in {"undefined", "null", "claw-global-session"}:
        return False
    if _meta_is_archived(_row_meta(row)):
        return False
    if row.get("channel") == "claw":
        return False
    if _row_meta(row).get("mode") == "claw":
        return False

    name = str(row.get("name") or "").strip()
    status = str(row.get("status") or "idle")
    if name == "New Chat" and status != "running" and _row_message_count(row) == 0:
        return False

    return True


def _chat_spec_from_row(row: dict) -> ChatSpec:
    meta = _row_meta(row)
    agent_id = row.get("agent_id")
    if agent_id and "agent_id" not in meta:
        meta["agent_id"] = agent_id

    return ChatSpec(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        session_id=str(row.get("session_id") or row["id"]),
        channel=str(row.get("channel") or "default"),
        name=str(row.get("name") or "New Chat"),
        status=str(row.get("status") or "idle"),
        task_status=str(row.get("task_status") or "pending"),
        pinned=bool(row.get("pinned")),
        meta=meta,
        created_at=row.get("created_at") or datetime.now(),
        updated_at=row.get("updated_at") or datetime.now(),
    )


async def _workspace_for_agent(
    request: Request,
    agent_id: str,
    cache: dict[str, Any],
) -> Any:
    if agent_id not in cache:
        cache[agent_id] = await get_agent_for_request(request, agent_id=agent_id)
    return cache[agent_id]


async def _mobile_task_sources(request: Request) -> list[_MobileTaskSource]:
    if not _request_has_multi_agent_manager(request):
        workspace = await get_agent_for_request(request)
        chats = await workspace.chat_manager.list_chats(
            user_id=current_user_id(request),
            channel="console",
        )
        return [
            _MobileTaskSource(
                chat=chat,
                workspace=workspace,
                agent_id=getattr(workspace, "agent_id", None),
                artifact_agent_id=None,
            )
            for chat in chats
            if not _chat_is_archived(chat)
        ]

    enabled_agent_ids = _enabled_agent_ids()
    rows = get_chat_list_repository().list_recent_chats(
        enabled_agent_ids=enabled_agent_ids,
        user_id=current_user_id(request),
        limit=50,
    )
    workspace_cache: dict[str, Any] = {}
    sources: list[_MobileTaskSource] = []
    for row in rows:
        if not _is_visible_mobile_task_row(row):
            continue
        agent_id = _row_agent_id(row)
        if not agent_id:
            continue
        workspace = await _workspace_for_agent(request, agent_id, workspace_cache)
        chat = await workspace.chat_manager.get_chat(str(row["id"]))
        if chat is None:
            chat = _chat_spec_from_row(row)
        if _chat_is_archived(chat):
            continue
        sources.append(
            _MobileTaskSource(
                chat=chat,
                workspace=workspace,
                agent_id=agent_id,
                artifact_agent_id=agent_id,
                message_count=_row_message_count(row),
            ),
        )
    return sources


async def _chat_messages_for_mobile(
    request: Request,
    workspace,
    chat_id: str,
    session_id: str,
) -> list[dict]:
    chat_history = await get_runner_chat(
        request,
        chat_id,
        mgr=workspace.chat_manager,
        session=workspace.runner.session,
        workspace=workspace,
    )
    messages = _serialize_mobile_messages(chat_history.messages)
    return _normalize_mobile_message_media_paths(
        messages,
        workspace,
        session_id,
    )


async def _artifact_summaries_for_session(
    request: Request,
    session_id: str,
    agent_id: str | None = None,
) -> list[MobileArtifactSummary]:
    if agent_id:
        artifacts = await list_workspace_artifacts(
            request,
            session_id=session_id,
            agent_id=agent_id,
        )
    else:
        artifacts = await list_workspace_artifacts(request, session_id=session_id)
    return [serialize_artifact_summary(item) for item in artifacts]


async def _workspace_for_chat_row(request: Request, chat_row: dict):
    agent_id = str(chat_row.get("agent_id") or "") or None
    if agent_id:
        return await get_agent_for_request(request, agent_id=agent_id)
    return await get_agent_for_request(request)


@router.get("/confirmations", response_model=list[MobilePendingConfirmation])
async def get_mobile_confirmations(
    request: Request,
) -> list[MobilePendingConfirmation]:
    return [
        serialize_pending_confirmation(item)
        for item in await _visible_pending_approvals(request)
    ]


@router.post(
    "/confirmations/{request_id}/approve",
    response_model=MobileConfirmationActionResponse,
)
async def approve_mobile_confirmation(
    request_id: str,
    request: Request,
) -> MobileConfirmationActionResponse:
    approval_svc = get_approval_service()
    pending = await approval_svc.get_request(request_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="Approval request not found")

    ensure_chat_access(request, pending.root_session_id, allow_admin=False)
    resolved = await approval_svc.resolve_request(
        request_id,
        ApprovalDecision.APPROVED,
    )

    return MobileConfirmationActionResponse(
        success=True,
        message=f"Tool '{resolved.tool_name}' approved, executing...",
        request_id=request_id,
        tool_name=resolved.tool_name,
    )


@router.post(
    "/confirmations/{request_id}/deny",
    response_model=MobileConfirmationActionResponse,
)
async def deny_mobile_confirmation(
    request_id: str,
    request: Request,
) -> MobileConfirmationActionResponse:
    approval_svc = get_approval_service()
    pending = await approval_svc.get_request(request_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="Approval request not found")

    ensure_chat_access(request, pending.root_session_id, allow_admin=False)
    resolved = await approval_svc.resolve_request(
        request_id,
        ApprovalDecision.DENIED,
    )

    return MobileConfirmationActionResponse(
        success=True,
        message=f"Tool '{resolved.tool_name}' denied",
        request_id=request_id,
        tool_name=resolved.tool_name,
    )


@router.get("/workbench", response_model=MobileWorkbenchResponse)
async def get_mobile_workbench(request: Request) -> MobileWorkbenchResponse:
    tasks = await get_mobile_tasks(request)
    confirmations = await get_mobile_confirmations(request)
    recent_results: list[MobileArtifactSummary] = []
    for task in tasks:
        if task.artifact_count <= 0:
            continue
        recent_results = await get_mobile_results(task.id, request)
        if recent_results:
            break

    return MobileWorkbenchResponse(
        user_id=current_user_id(request),
        pending_confirmation_count=len(confirmations),
        running_task_count=sum(
            1 for task in tasks if task.display_status == "running"
        ),
        recent_tasks=tasks[:5],
        recent_results=recent_results[:5],
    )


@router.get("/tasks", response_model=list[MobileTaskSummary])
async def get_mobile_tasks(request: Request) -> list[MobileTaskSummary]:
    sources = await _mobile_task_sources(request)
    pending_counts = _count_pending_by_root(
        await _visible_pending_approvals(request),
    )

    summaries: list[MobileTaskSummary] = []
    for source in sources:
        chat = source.chat
        workspace = source.workspace
        session_id = str(getattr(chat, "session_id", "") or chat.id)
        ensure_chat_access(request, session_id, allow_admin=False)
        agent_id = _chat_agent_id(chat) or source.agent_id
        artifacts = await _artifact_summaries_for_session(
            request,
            session_id,
            agent_id=source.artifact_agent_id,
        )
        pending_confirmation_count = pending_counts.get(session_id, 0)
        runtime_status = await workspace.task_tracker.get_status(chat.id)
        task_status = getattr(chat, "task_status", None)
        messages: list[dict] = []
        if (
            runtime_status != "running"
            and pending_confirmation_count == 0
            and task_status not in {"completed", "failed"}
            and not artifacts
        ):
            messages = await _chat_messages_for_mobile(
                request,
                workspace,
                chat.id,
                session_id,
            )
        has_assistant_response = _has_assistant_response(messages)
        summaries.append(
            MobileTaskSummary(
                id=chat.id,
                session_id=session_id,
                name=chat.name,
                agent_id=agent_id,
                expert_team_id=_chat_expert_team_id(chat),
                active_mode=_chat_active_mode(chat),
                runtime_status=runtime_status,
                task_status=task_status,
                display_status=derive_mobile_display_status(
                    runtime_status=runtime_status,
                    task_status=task_status,
                    pending_confirmation_count=pending_confirmation_count,
                    artifact_count=len(artifacts),
                    has_assistant_response=has_assistant_response,
                ),
                pending_confirmation_count=pending_confirmation_count,
                artifact_count=len(artifacts),
                message_count=len(messages) if messages else (source.message_count or 0),
                has_assistant_response=has_assistant_response,
                updated_at=_timestamp(getattr(chat, "updated_at", None)),
            ),
        )

    summaries.sort(key=lambda item: item.updated_at or 0, reverse=True)
    return summaries


@router.post("/tasks/{chat_id}/archive", response_model=dict)
async def archive_mobile_task(
    chat_id: str,
    request: Request,
) -> dict:
    chat_row = ensure_chat_access(request, chat_id, allow_admin=False)
    workspace = await _workspace_for_chat_row(request, chat_row)
    chat = await workspace.chat_manager.get_chat(chat_row["id"])
    if chat is None:
        raise HTTPException(status_code=404, detail="Task not found")

    archived_at = datetime.now(timezone.utc).isoformat()
    meta = {**_chat_meta(chat), "archived_at": archived_at}
    updated = await workspace.chat_manager.patch_chat(
        chat_row["id"],
        ChatUpdate(meta=meta),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return {
        "archived": True,
        "id": chat_row["id"],
        "archived_at": archived_at,
    }


@router.delete("/tasks/{chat_id}", response_model=dict)
async def delete_mobile_task(
    chat_id: str,
    request: Request,
) -> dict:
    chat_row = ensure_chat_access(request, chat_id, allow_admin=False)
    workspace = await _workspace_for_chat_row(request, chat_row)
    deleted = await workspace.chat_manager.delete_chats([chat_row["id"]])
    if not deleted:
        raise HTTPException(status_code=404, detail="Task not found")

    return {"deleted": True, "id": chat_row["id"]}


@router.get("/tasks/{chat_id}", response_model=MobileTaskDetailResponse)
async def get_mobile_task_detail(
    chat_id: str,
    request: Request,
) -> MobileTaskDetailResponse:
    chat_row = ensure_chat_access(request, chat_id, allow_admin=False)
    agent_id = str(chat_row.get("agent_id") or "") or None
    if agent_id:
        workspace = await get_agent_for_request(request, agent_id=agent_id)
    else:
        workspace = await get_agent_for_request(request)
    chat = await workspace.chat_manager.get_chat(chat_row["id"])
    if chat is None:
        raise HTTPException(status_code=404, detail="Task not found")

    session_id = str(getattr(chat, "session_id", "") or chat.id)
    pending = [
        serialize_pending_confirmation(item)
        for item in await _visible_pending_approvals(request)
        if getattr(item, "root_session_id", None) == session_id
    ]
    agent_id = _chat_agent_id(chat) or agent_id
    artifacts = await _artifact_summaries_for_session(
        request,
        session_id,
        agent_id=agent_id,
    )
    runtime_status = await workspace.task_tracker.get_status(chat.id)
    messages = await _chat_messages_for_mobile(
        request,
        workspace,
        chat.id,
        session_id,
    )
    has_assistant_response = _has_assistant_response(messages)
    task = MobileTaskSummary(
        id=chat.id,
        session_id=session_id,
        name=chat.name,
        agent_id=agent_id,
        expert_team_id=_chat_expert_team_id(chat),
        active_mode=_chat_active_mode(chat),
        runtime_status=runtime_status,
        task_status=getattr(chat, "task_status", None),
        display_status=derive_mobile_display_status(
            runtime_status=runtime_status,
            task_status=getattr(chat, "task_status", None),
            pending_confirmation_count=len(pending),
            artifact_count=len(artifacts),
            has_assistant_response=has_assistant_response,
        ),
        pending_confirmation_count=len(pending),
        artifact_count=len(artifacts),
        message_count=len(messages),
        has_assistant_response=has_assistant_response,
        updated_at=_timestamp(getattr(chat, "updated_at", None)),
    )

    return MobileTaskDetailResponse(
        task=task,
        messages=messages,
        confirmations=pending,
        artifacts=artifacts,
    )


@router.get("/results/{chat_id}", response_model=list[MobileArtifactSummary])
async def get_mobile_results(
    chat_id: str,
    request: Request,
) -> list[MobileArtifactSummary]:
    chat_row = ensure_chat_access(request, chat_id, allow_admin=False)
    session_id = str(chat_row.get("session_id") or chat_id)
    agent_id = str(chat_row.get("agent_id") or "") or None
    return await _artifact_summaries_for_session(
        request,
        session_id,
        agent_id=agent_id,
    )
