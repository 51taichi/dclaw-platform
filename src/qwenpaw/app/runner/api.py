# -*- coding: utf-8 -*-
"""Chat management API."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from agentscope.memory import InMemoryMemory

from .manager import ChatManager
from .models import (
    ChatSpec,
    ChatUpdate,
    ChatHistory,
    ChatStatus,
)
from .utils import agentscope_msg_to_message
from ..chat_access import current_user_id, ensure_chat_access, ensure_chat_ids_access
from ..artifact_filter import extract_user_task_files_from_texts, is_internal_task_file
from ...security.local_access import (
    LOCAL_ACCESS_MODE_META_KEY,
    parse_local_access_mode,
)


router = APIRouter(prefix="/chats", tags=["chats"])


def _validate_local_access_meta(meta: dict[str, Any] | None) -> None:
    if not meta or LOCAL_ACCESS_MODE_META_KEY not in meta:
        return
    if parse_local_access_mode(
        meta[LOCAL_ACCESS_MODE_META_KEY],
        default=None,
    ) is None:
        raise HTTPException(
            status_code=422,
            detail="Invalid local access mode",
        )


async def get_workspace(request: Request):
    """Get the workspace for the active agent."""
    from ..agent_context import get_agent_for_request

    return await get_agent_for_request(request)


async def get_chat_manager(
    request: Request,
) -> ChatManager:
    """Get the chat manager for the active agent.

    Args:
        request: FastAPI request object

    Returns:
        ChatManager instance for the specified agent

    Raises:
        HTTPException: If manager is not initialized
    """
    workspace = await get_workspace(request)
    return workspace.chat_manager


async def get_session(
    request: Request,
) -> Any:
    """Get the session for the active agent.

    Args:
        request: FastAPI request object

    Returns:
        Session instance for the specified agent

    Raises:
        HTTPException: If session is not initialized
    """
    workspace = await get_workspace(request)
    return workspace.runner.session


@router.get("", response_model=list[ChatSpec])
async def list_chats(
    request: Request,
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    channel: Optional[str] = Query(None, description="Filter by channel"),
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """List all chats with optional filters.

    Args:
        user_id: Optional user ID to filter chats
        channel: Optional channel name to filter chats
        mgr: Chat manager dependency
    """
    _ = user_id  # Client-supplied user ids are ignored for tenant isolation.
    chats = await mgr.list_chats(
        user_id=current_user_id(request),
        channel=channel,
    )
    tracker = workspace.task_tracker
    result = []
    for spec in chats:
        status = await tracker.get_status(spec.id)
        result.append(spec.model_copy(update={"status": status}))
    return result


@router.post("", response_model=ChatSpec)
async def create_chat(
    request: Request,
    payload: ChatSpec,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Create a new chat.

    Server generates chat_id (UUID) automatically.

    Args:
        request: Chat creation request
        mgr: Chat manager dependency

    Returns:
        Created chat spec with UUID
    """
    _validate_local_access_meta(payload.meta)
    chat_id = str(uuid4())
    spec = ChatSpec(
        id=chat_id,
        name=payload.name,
        session_id=payload.session_id or chat_id,
        user_id=current_user_id(request),
        channel=payload.channel,
        meta=payload.meta,
    )
    return await mgr.create_chat(spec)


@router.post("/batch-delete", response_model=dict)
async def batch_delete_chats(
    request: Request,
    chat_ids: list[str],
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Delete chats by chat IDs.

    Args:
        chat_ids: List of chat IDs
        mgr: Chat manager dependency
    Returns:
        True if deleted, False if failed

    """
    ensure_chat_ids_access(request, chat_ids)
    deleted = await mgr.delete_chats(chat_ids=chat_ids)
    return {"deleted": deleted}


def _scan_session_files(workspace_dir: Path, chat_id: str) -> list[str]:
    """Scan only a chat's isolated session folder for artifact files."""
    files = []
    if not workspace_dir or not workspace_dir.exists():
        return files

    session_data_dir = workspace_dir / "sessions_data" / chat_id
    if session_data_dir.exists() and session_data_dir.is_dir():
        try:
            for p in session_data_dir.rglob("*"):
                if p.is_dir():
                    continue
                try:
                    rel_p = p.relative_to(session_data_dir)
                    parts = rel_p.parts
                except ValueError:
                    continue

                if is_internal_task_file(str(rel_p)):
                    continue

                files.append(str(rel_p))
        except Exception:
            pass

    # Deduplicate while preserving order
    return list(dict.fromkeys(files))


def _message_texts(messages) -> list[str]:
    texts: list[str] = []
    for msg in messages or []:
        if getattr(msg, "role", None) == "user":
            continue
        content = getattr(msg, "content", None)
        if isinstance(content, str):
            texts.append(content)
            continue
        if isinstance(content, list):
            for block in content:
                block_text = getattr(block, "text", None)
                if isinstance(block_text, str):
                    texts.append(block_text)
                output = getattr(block, "output", None)
                if isinstance(output, str):
                    texts.append(output)
    return texts


def _recover_explicit_artifacts_from_messages(
    messages,
    workspace_dir: Path,
) -> list[str]:
    """Recover root-written artifacts that are explicitly named by this chat."""
    return extract_user_task_files_from_texts(_message_texts(messages), workspace_dir)


@router.get("/{chat_id}/status", response_model=ChatStatus)
async def get_chat_status(
    request: Request,
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    workspace=Depends(get_workspace),
):
    """Return lightweight chat status for high-frequency polling."""
    chat_row = ensure_chat_access(request, chat_id)
    chat_spec = await mgr.get_chat(chat_row["id"])
    if not chat_spec:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    runtime_status = await workspace.task_tracker.get_status(chat_spec.id)
    return ChatStatus(
        id=chat_spec.id,
        status=runtime_status,
        task_status=chat_spec.task_status,
        updated_at=chat_spec.updated_at,
        message_count=await mgr.count_messages(chat_spec.id),
    )


@router.get("/{chat_id}", response_model=ChatHistory)
async def get_chat(
    request: Request,
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
    session: Any = Depends(get_session),
    workspace=Depends(get_workspace),
):
    """Get detailed information about a specific chat by UUID.

    Args:
        request: FastAPI request (for agent context)
        chat_id: Chat UUID
        mgr: Chat manager dependency
        session: Session dependency

    Returns:
        ChatHistory with messages and status (idle/running)

    Raises:
        HTTPException: If chat not found (404)
    """
    chat_row = ensure_chat_access(request, chat_id)
    chat_spec = await mgr.get_chat(chat_row["id"])
    if not chat_spec:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )

    state = await session.get_session_state_dict(
        chat_spec.session_id,
        chat_spec.user_id,
        chat_spec.channel,
    )
    status = await workspace.task_tracker.get_status(chat_spec.id)
    if not state:
        return ChatHistory(messages=[], status=status)
    memory_state = state.get("agent", {}).get("memory", {})
    memory = InMemoryMemory()
    memory.load_state_dict(memory_state, strict=False)

    memories = await memory.get_memory(prepend_summary=False)
    messages = agentscope_msg_to_message(memories)

    # Auto-patch delivery card trigger HTML for historical chats if not already present
    has_card_trigger = False
    for msg in messages:
        if isinstance(msg.content, str) and "qwenpaw-artifact-card-trigger" in msg.content:
            has_card_trigger = True
            break
        elif isinstance(msg.content, list):
            for block in msg.content:
                if hasattr(block, "text") and block.text and "qwenpaw-artifact-card-trigger" in block.text:
                    has_card_trigger = True
                    break
            if has_card_trigger:
                break

    if not has_card_trigger and messages:
        # Find the last assistant message
        last_assistant_idx = -1
        for idx in range(len(messages) - 1, -1, -1):
            if messages[idx].role == "assistant":
                last_assistant_idx = idx
                break

        if last_assistant_idx != -1:
            from pathlib import Path
            import json
            import html

            workspace_path = Path(workspace.workspace_dir)
            
            real_session_id = None
            if chat_spec.meta and chat_spec.meta.get("session_id"):
                real_session_id = chat_spec.meta["session_id"]

            modified_files = []
            if real_session_id:
                modified_files = _scan_session_files(workspace_path, real_session_id)
            if not modified_files and chat_spec.session_id:
                modified_files = _scan_session_files(workspace_path, chat_spec.session_id)
            if not modified_files:
                modified_files = _scan_session_files(workspace_path, chat_spec.id)
            if not modified_files:
                modified_files = _recover_explicit_artifacts_from_messages(
                    messages,
                    workspace_path,
                )

            if modified_files:
                import base64
                files_json = json.dumps(modified_files)
                encoded_files = base64.b64encode(files_json.encode('utf-8')).decode('utf-8')
                trigger_html = f'\n\n[qwenpaw-artifact-card-trigger](http://qwenpaw.local/?data={encoded_files})\n'

                content_patched = False
                if isinstance(messages[last_assistant_idx].content, list) and messages[last_assistant_idx].content:
                    last_node = messages[last_assistant_idx].content[-1]
                    if hasattr(last_node, "text") and isinstance(last_node.text, str):
                        last_node.text += trigger_html
                        content_patched = True

                if not content_patched:
                    from agentscope_runtime.engine.schemas.agent_schemas import TextContent
                    text_content = TextContent(
                        delta=False,
                        index=None,
                        text=trigger_html,
                    )
                    messages[last_assistant_idx].add_content(new_content=text_content)

    return ChatHistory(messages=messages, status=status)



@router.put("/{chat_id}", response_model=ChatSpec)
async def update_chat(
    request: Request,
    chat_id: str,
    spec: ChatUpdate,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Update an existing chat.

    Args:
        chat_id: Chat UUID
        spec: Partial chat update payload
        mgr: Chat manager dependency

    Returns:
        Updated chat spec

    Raises:
        HTTPException: If chat not found (404)
    """
    _validate_local_access_meta(spec.meta)
    chat_row = ensure_chat_access(request, chat_id)
    updated = await mgr.patch_chat(chat_row["id"], spec)
    if updated is None:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    return updated


@router.delete("/{chat_id}", response_model=dict)
async def delete_chat(
    request: Request,
    chat_id: str,
    mgr: ChatManager = Depends(get_chat_manager),
):
    """Delete a chat by UUID.

    Note: This only deletes the chat spec (UUID mapping).
    JSONSession state is NOT deleted.

    Args:
        chat_id: Chat UUID
        mgr: Chat manager dependency

    Returns:
        True if deleted, False if failed

    Raises:
        HTTPException: If chat not found (404)
    """
    chat_row = ensure_chat_access(request, chat_id)
    deleted = await mgr.delete_chats(chat_ids=[chat_row["id"]])
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Chat not found: {chat_id}",
        )
    return {"deleted": True}
