# -*- coding: utf-8 -*-
"""Console APIs: push messages, chat, and file upload for chat."""
from __future__ import annotations

import asyncio
from hashlib import sha256
import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Union

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, Depends, Body
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel
from starlette.responses import Response, StreamingResponse

from qwenpaw.runtime.contracts import AgentRequest
from ...utils.logging import LOG_FILE_PATH
from ..agent_context import get_agent_for_request, set_current_chat_model
from ..billing.context import BillingSource
from ..billing.entrypoint import (
    prepare_user_billing_execution,
    resume_user_billing_execution,
)
from ..billing.usage import InsufficientUsageCreditsError
from ..channels.base import ContentType, TextContent
from ..expert_teams import (
    ExpertTeamOrchestrator,
    attach_run_to_chat,
    create_expert_team_run,
    get_latest_expert_team_run_by_chat,
    publish_expert_team_run_state,
    resume_expert_team_run,
)
from ..runner.title_generator import generate_and_update_title
from ..guards import require_admin
from ..chat_access import current_user_id, ensure_chat_access, is_admin_request
from ..task_limits import get_task_limiter
from ...providers import ProviderManager
from ...providers.model_aliases import resolve_task_model_override


logger = logging.getLogger(__name__)

_BILLING_EXECUTION_LEASE_SECONDS = 600.0
_BILLING_EXECUTION_RENEW_INTERVAL_SECONDS = 60.0

router = APIRouter(prefix="/console", tags=["console"])

_title_tasks: dict[tuple[str, str], asyncio.Task] = {}


def _schedule_chat_title(*, workspace, chat_id, user_message, placeholder_name,
                         payer_user_id, source, request_key):
    """Title work must not keep the conversation run or its billing open."""
    key = (workspace.agent_id, chat_id)
    existing = _title_tasks.get(key)
    if existing is not None and not existing.done():
        return existing

    async def generate():
        prepared = None
        try:
            prepared = prepare_user_billing_execution(
                payer_user_id, source, request_key + ":title",
                {"chat_id": chat_id, "message_sha256": sha256(user_message.encode()).hexdigest()},
            )
            with prepared.activate():
                await generate_and_update_title(
                    workspace=workspace, chat_id=chat_id,
                    user_message=user_message, placeholder_name=placeholder_name,
                )
            prepared.finalize_completed()
        except asyncio.CancelledError:
            if prepared is not None:
                prepared.finalize("cancelled", error_code="CANCELLED")
            raise
        except Exception:
            if prepared is not None:
                prepared.finalize("failed", error_code="TITLE_GENERATION_FAILED")
            logger.exception("Background title generation failed")

    task = asyncio.create_task(generate())
    _title_tasks[key] = task

    def finished(completed):
        if _title_tasks.get(key) is completed:
            _title_tasks.pop(key, None)

    task.add_done_callback(finished)
    return task


class MarkInboxReadRequest(BaseModel):
    event_ids: list[str] = []
    all: bool = False


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_DEBUG_LOG_LINES = 1000


def _safe_filename(name: str) -> str:
    """Safe basename, alphanumeric/./-/_, max 200 chars."""
    base = Path(name).name if name else "file"
    return re.sub(r"[^\w.\-]", "_", base)[:200] or "file"


def _extract_placeholder_name(content_parts: list) -> tuple[str, str]:
    """Return ``(placeholder_name, first_user_text)`` for a new chat.

    The placeholder name shows up in the session drawer immediately while a
    background task asks the model for a real title. Content shapes match
    ``channels/base.py::_extract_chat_name``: dict blocks like
    ``{"type": "text", "text": "..."}``, raw strings, and objects with a
    ``.text`` attribute. Anything else (audio/image/file blocks) is treated
    as media and gets the generic "Media Message" placeholder.
    """
    if not content_parts:
        return "New Chat", ""
    content = content_parts[0]
    if not content:
        return "Media Message", ""
    if isinstance(content, str):
        first_text = content
    elif isinstance(content, dict):
        text = content.get("text", "")
        first_text = text if isinstance(text, str) else ""
    elif hasattr(content, "text"):
        first_text = content.text or ""
    else:
        first_text = ""
    if not first_text:
        return "Media Message", ""
    return first_text[:10], first_text


def _normalize_console_input_content(content: Any) -> list[Any]:
    """Normalize frontend chat content into runtime content parts."""
    if content is None:
        return []
    if isinstance(content, str):
        return [TextContent(type=ContentType.TEXT, text=content)]
    if isinstance(content, list):
        parts: list[Any] = []
        for item in content:
            parts.extend(_normalize_console_input_content(item))
        return parts
    if isinstance(content, dict):
        if content.get("type") == "text" and isinstance(content.get("text"), str):
            return [TextContent(type=ContentType.TEXT, text=content["text"])]
        return [content]
    return [content]


def _extract_session_and_payload(request_data: Union[AgentRequest, dict]):
    """Extract run_key (ChatSpec.id), session_id, and native payload.

    run_key must be ChatSpec.id (chat_id) so it matches list_chats/get_chat.
    """
    if isinstance(request_data, AgentRequest):
        channel_id = getattr(request_data, "channel", None) or "console"
        sender_id = request_data.user_id or "default"
        session_id = request_data.session_id or "default"
        content_parts = _normalize_console_input_content(
            list(request_data.input[0].content) if request_data.input else []
        )
    else:
        channel_id = request_data.get("channel", "console")
        sender_id = request_data.get("user_id", "default")
        session_id = (
            request_data.get("session_id")
            or request_data.get("chat_id")
            or "default"
        )
        expert_team_id = request_data.get("expert_team_id")
        input_data = request_data.get("input", [])
        content_parts = []
        for content_part in input_data:
            if hasattr(content_part, "content"):
                content_parts.extend(
                    _normalize_console_input_content(
                        getattr(content_part, "content", None),
                    ),
                )
            elif isinstance(content_part, dict) and "content" in content_part:
                content_parts.extend(
                    _normalize_console_input_content(
                        content_part.get("content"),
                    ),
                )

    native_payload: dict[str, Any] = {
        "channel_id": channel_id,
        "sender_id": sender_id,
        "content_parts": content_parts,
        "meta": {
            "session_id": session_id,
            "user_id": sender_id,
        },
    }
    if not isinstance(request_data, AgentRequest) and expert_team_id:
        native_payload["meta"]["expert_team_id"] = expert_team_id
    return native_payload


def _tail_text_file(
    path: Path,
    *,
    lines: int = 200,
    max_bytes: int = 512 * 1024,
) -> str:
    """Read the last N lines from a text file with bounded memory."""
    path = Path(path)
    if not path.exists() or not path.is_file():
        return ""
    try:
        size = path.stat().st_size
        if size == 0:
            return ""
        with open(path, "rb") as f:
            if size <= max_bytes:
                data = f.read()
            else:
                f.seek(max(size - max_bytes, 0))
                data = f.read()
        text = data.decode("utf-8", errors="replace")
        return "\n".join(text.splitlines()[-lines:])
    except Exception:
        logger.exception("Failed to read backend debug log file")
        return ""


def _request_user_id(request: Request, fallback: str = "default") -> str:
    state = getattr(request, "state", None)
    return str(getattr(state, "user_id", None) or fallback or "default")


def _bind_console_payload_to_request_user(
    request: Request,
    native_payload: dict,
) -> None:
    """Bind browser console chat ownership to the authenticated user."""
    user_id = current_user_id(request)
    native_payload["sender_id"] = user_id
    meta = native_payload.setdefault("meta", {})
    if isinstance(meta, dict):
        meta["user_id"] = user_id


def _billing_error_sse(exc: InsufficientUsageCreditsError) -> str:
    """Return the stable, redacted customer billing failure event."""
    payload = {
        "type": "billing.error",
        "code": "INSUFFICIENT_CREDITS",
        "available_credits": exc.available,
        "required_credits": exc.required,
        "top_up_path": "/wallet",
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _acquire_task_permit(
    request: Request,
    *,
    agent_id: str,
    user_id: str,
) -> Any | None:
    """Try to reserve a background task slot for real FastAPI requests."""
    app = getattr(request, "app", None)
    if app is None:
        return None
    permit = await get_task_limiter(app).try_acquire(
        agent_id=agent_id,
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
    return permit


@router.post(
    "/chat",
    status_code=200,
    summary="Chat with console (streaming response)",
    description="DClaw Agent API request format. Use body.reconnect=true "
    "to attach to a running stream.",
)
async def post_console_chat(
    request_data: Union[AgentRequest, dict],
    request: Request,
) -> Response:
    """Stream agent response. Run continues in background after disconnect.
    Stop via POST /console/chat/stop. Reconnect with body.reconnect=true.
    """
    workspace = await get_agent_for_request(request)
    channel_manager = workspace.channel_manager
    if channel_manager is None:
        raise HTTPException(
            status_code=503,
            detail="Console channel manager is unavailable",
        )
    console_channel = await channel_manager.get_channel("console")
    if console_channel is None:
        raise HTTPException(
            status_code=503,
            detail="Channel Console not found",
        )
    try:
        native_payload = _extract_session_and_payload(request_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _bind_console_payload_to_request_user(request, native_payload)
    session_id = console_channel.resolve_session_id(
        sender_id=native_payload["sender_id"],
        channel_meta=native_payload["meta"],
    )
    name, first_text = _extract_placeholder_name(
        native_payload["content_parts"],
    )
    chat = await workspace.chat_manager.get_or_create_chat(
        session_id,
        native_payload["sender_id"],
        native_payload["channel_id"],
        name=name,
    )
    if chat and chat.meta and "active_model" in chat.meta:
        stored_model = chat.meta["active_model"]
        app_state = getattr(getattr(request, "app", None), "state", None)
        provider_manager = getattr(app_state, "provider_manager", None)
        if provider_manager is None:
            provider_manager = ProviderManager.get_instance()
        active_model = resolve_task_model_override(
            provider_manager,
            stored_model,
        )
        if active_model != stored_model:
            from ..runner.models import ChatUpdate

            await workspace.chat_manager.patch_chat(
                chat.id,
                ChatUpdate(meta={"active_model": active_model}),
            )
            logger.info(
                "Normalized chat model override: chat_id=%s active=%s",
                chat.id,
                bool(active_model),
            )
        set_current_chat_model(active_model)
    else:
        set_current_chat_model(None)

    tracker = workspace.task_tracker

    is_reconnect = False
    if isinstance(request_data, dict):
        is_reconnect = request_data.get("reconnect") is True

    if is_reconnect:
        queue = await tracker.attach(chat.id)
        if queue is None:
            return
        expert_team_run_id = None
    else:
        expert_team_id = native_payload["meta"].get("expert_team_id")
        expert_team_run_id = None
        resumed_prepared = None
        resume_required_credits = 0
        resume_next_member_key = ""
        stream_payload = native_payload
        stream_fn = console_channel.stream_one
        if first_text.strip() == "继续":
            latest_run = get_latest_expert_team_run_by_chat(chat.id)
            request_user_id = _request_user_id(
                request,
                native_payload["sender_id"],
            )
            if (
                latest_run is not None
                and latest_run.user_id == request_user_id
                and latest_run.state == "paused_insufficient_balance"
                and latest_run.billing_usage_order_id
            ):
                resumed_prepared = resume_user_billing_execution(
                    latest_run.billing_usage_order_id,
                    request_user_id,
                    lease_seconds=_BILLING_EXECUTION_LEASE_SECONDS,
                )
                resumed_run = (
                    resume_expert_team_run(latest_run.id, request_user_id)
                    if resumed_prepared is not None
                    else None
                )
                if resumed_run is None:
                    raise HTTPException(
                        status_code=409,
                        detail="Expert team run is resuming",
                    )
                expert_team_id = resumed_run.team_id
                expert_team_run_id = resumed_run.id
                resume_required_credits = latest_run.required_credits or 0
                resume_next_member_key = latest_run.next_member_key or ""
                native_payload["content_parts"] = [
                    TextContent(
                        type=ContentType.TEXT,
                        text=resumed_run.input_text,
                    ),
                ]
        if expert_team_id:
            if expert_team_run_id is None:
                try:
                    run_user_id = _request_user_id(
                        request,
                        native_payload["sender_id"],
                    )
                    run = create_expert_team_run(
                        team_id=expert_team_id,
                        root_chat_id=chat.id,
                        root_session_id=session_id,
                        user_id=run_user_id,
                        input_text=first_text,
                    )
                except ValueError as e:
                    raise HTTPException(status_code=404, detail=str(e)) from e
                await attach_run_to_chat(workspace, chat.id, run)
                expert_team_run_id = run.id
            stream_payload = {
                "run_id": expert_team_run_id,
                "team_id": expert_team_id,
                "root_chat_id": chat.id,
                "root_session_id": session_id,
                "native_payload": native_payload,
            }
            stream_fn = ExpertTeamOrchestrator(
                workspace=workspace,
                console_channel=console_channel,
            ).stream_one

        try:
            permit = await _acquire_task_permit(
                request,
                agent_id=str(
                    getattr(workspace, "agent_id", "") or "default",
                ),
                user_id=_request_user_id(
                    request,
                    native_payload["sender_id"],
                ),
            )
        except BaseException:
            if resumed_prepared is not None and expert_team_run_id:
                resumed_prepared.pause_expert_team_insufficient(
                    run_id=expert_team_run_id,
                    payer_user_id=_request_user_id(
                        request,
                        native_payload["sender_id"],
                    ),
                    next_member_key=resume_next_member_key,
                    required_credits=resume_required_credits,
                )
            raise

        payer_user_id = _request_user_id(
            request,
            native_payload["sender_id"],
        )
        source_type = (
            "expert_team"
            if expert_team_id
            else (
                "mobile"
                if isinstance(request_data, dict)
                and request_data.get("stream") is False
                else "client"
            )
        )
        headers = getattr(request, "headers", {})
        request_key = str(
            headers.get("Idempotency-Key")
            or headers.get("idempotency-key")
            or uuid.uuid4()
        )
        request_fingerprint = {
            "message_sha256": sha256(first_text.encode()).hexdigest(),
            "chat_id": chat.id,
        }

        async def limited_stream_fn(payload):
            prepared = resumed_prepared or prepare_user_billing_execution(
                payer_user_id,
                BillingSource(
                    type=source_type,
                    id=chat.id,
                    expert_id=str(getattr(workspace, "agent_id", "") or "")
                    or None,
                    expert_team_run_id=expert_team_run_id,
                ),
                request_key,
                request_fingerprint,
                lease_seconds=_BILLING_EXECUTION_LEASE_SECONDS,
            )

            async def renew_billing_execution_lease():
                while True:
                    await asyncio.sleep(
                        _BILLING_EXECUTION_RENEW_INTERVAL_SECONDS,
                    )
                    try:
                        renewed = prepared.renew(
                            lease_seconds=_BILLING_EXECUTION_LEASE_SECONDS,
                        )
                    except Exception:
                        logger.exception(
                            "Billing execution lease renewal errored: "
                            "execution_id=%s chat_id=%s",
                            prepared.session.execution_id,
                            chat.id,
                        )
                        continue
                    if not renewed:
                        logger.error(
                            "Billing execution lease renewal failed: "
                            "execution_id=%s chat_id=%s",
                            prepared.session.execution_id,
                            chat.id,
                        )
                        return

            lease_renewal_task = asyncio.create_task(
                renew_billing_execution_lease(),
            )
            try:
                with prepared.activate():
                    try:
                        async for item in stream_fn(payload):
                            yield item
                        if first_text and chat.name == name:
                            _schedule_chat_title(
                                workspace=workspace, chat_id=chat.id,
                                user_message=first_text, placeholder_name=name,
                                payer_user_id=payer_user_id,
                                source=BillingSource(type=source_type, id=chat.id,
                                    expert_id=workspace.agent_id,
                                    expert_team_run_id=expert_team_run_id),
                                request_key=request_key,
                            )
                    except InsufficientUsageCreditsError as exc:
                        if expert_team_run_id:
                            current_run = get_latest_expert_team_run_by_chat(
                                chat.id,
                            )
                            next_member = next(
                                (
                                    member
                                    for member in (
                                        current_run.members
                                        if current_run is not None
                                        else []
                                    )
                                    if member.state
                                    not in {
                                        "completed",
                                        "failed",
                                        "cancelled",
                                    }
                                ),
                                None,
                            )
                            pause_saved = bool(
                                next_member is not None
                                and prepared.pause_expert_team_insufficient(
                                    run_id=expert_team_run_id,
                                    payer_user_id=payer_user_id,
                                    next_member_key=next_member.member_key,
                                    required_credits=exc.required,
                                )
                            )
                            if not pause_saved:
                                prepared.finalize(
                                    "failed",
                                    error_code="INSUFFICIENT_CREDITS",
                                )
                            else:
                                publish_expert_team_run_state(
                                    expert_team_run_id,
                                )
                        else:
                            prepared.finalize(
                                "failed",
                                error_code="INSUFFICIENT_CREDITS",
                            )
                        yield _billing_error_sse(exc)
                        return
                    except asyncio.CancelledError:
                        prepared.finalize("cancelled", error_code="CANCELLED")
                        raise
                    except BaseException:
                        prepared.finalize("failed", error_code="MODEL_ERROR")
                        raise
                    final_team_run = (
                        get_latest_expert_team_run_by_chat(chat.id)
                        if expert_team_run_id
                        else None
                    )
                    if final_team_run is not None and final_team_run.state in {
                        "failed",
                        "cancelled",
                    }:
                        prepared.finalize(
                            "cancelled"
                            if final_team_run.state == "cancelled"
                            else "failed",
                            error_code="TEAM_RUN_"
                            + final_team_run.state.upper(),
                        )
                    else:
                        prepared.finalize_completed()
            finally:
                lease_renewal_task.cancel()
                await asyncio.gather(
                    lease_renewal_task,
                    return_exceptions=True,
                )
                if permit is not None:
                    await permit.release()

        try:
            queue, is_new_run = await tracker.start_new(
                chat.id,
                stream_payload,
                limited_stream_fn,
                on_finish=permit.release if permit is not None else None,
            )
        except asyncio.CancelledError:
            # The request may disconnect while waiting for the previous turn.
            if permit is not None:
                await permit.release()
            raise
        except Exception:
            if permit is not None:
                await permit.release()
            if resumed_prepared is not None and expert_team_run_id:
                resumed_prepared.pause_expert_team_insufficient(
                    run_id=expert_team_run_id,
                    payer_user_id=payer_user_id,
                    next_member_key=resume_next_member_key,
                    required_credits=resume_required_credits,
                )
            raise
        if not is_new_run and permit is not None:
            await permit.release()
        if not is_new_run and resumed_prepared is not None and expert_team_run_id:
            resumed_prepared.pause_expert_team_insufficient(
                run_id=expert_team_run_id,
                payer_user_id=payer_user_id,
                next_member_key=resume_next_member_key,
                required_credits=resume_required_credits,
            )
    if isinstance(request_data, dict) and request_data.get("stream") is False:
        return JSONResponse(
            {
                "chat_id": chat.id,
                "session_id": session_id,
                "expert_team_run_id": expert_team_run_id or "",
                "status": "started",
            },
        )

    async def event_generator() -> AsyncGenerator[str, None]:
        # Hold iterator so finally can aclose(); guarantees stream_from_queue's
        # finally (detach_subscriber) on client abort / generator teardown.
        stream_it = tracker.stream_from_queue(queue, chat.id)
        try:
            try:
                async for event_data in stream_it:
                    yield event_data
            except Exception as e:
                logger.exception("Console chat stream error")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            await stream_it.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-QwenPaw-Chat-Id": chat.id,
            "X-QwenPaw-Session-Id": session_id,
            "X-QwenPaw-Expert-Team-Run-Id": expert_team_run_id or "",
        },
    )


@router.post(
    "/chat/stop",
    status_code=200,
    summary="Stop running console chat",
)
async def post_console_chat_stop(
    request: Request,
    chat_id: str = Query(..., description="Chat id (ChatSpec.id) to stop"),
) -> dict:
    """Stop the running chat. Only stops when called."""
    logger.debug("[STOP API] Received stop request for chat_id=%s", chat_id)
    workspace = await get_agent_for_request(request)

    try:
        chat_row = ensure_chat_access(request, chat_id)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        chat_manager = getattr(workspace.runner, "_chat_manager", None)
        if not chat_manager:
            return {"stopped": False}
        resolved_chat_id = await chat_manager.get_chat_id_by_session(
            session_id=chat_id,
            channel="console",
            user_id=current_user_id(request),
        )
        if not resolved_chat_id:
            return {"stopped": False}
        chat_row = ensure_chat_access(request, resolved_chat_id)

    canonical_chat_id = str(chat_row["id"])
    logger.debug(
        "[STOP API] Got owned chat, calling task_tracker.request_stop...",
    )
    stopped = await workspace.task_tracker.request_stop(canonical_chat_id)

    logger.debug(
        "[STOP API] task_tracker.request_stop returned: stopped=%s",
        stopped,
    )
    return {"stopped": stopped}


@router.post("/upload", response_model=dict, summary="Upload file for chat")
async def post_console_upload(
    request: Request,
    file: UploadFile = File(..., description="File to attach"),
) -> dict:
    """Save to console channel media_dir."""

    workspace = await get_agent_for_request(request)
    console_channel = await workspace.channel_manager.get_channel("console")
    if console_channel is None:
        raise HTTPException(
            status_code=503,
            detail="Channel Console not found",
        )
    media_dir = console_channel.media_dir
    media_dir.mkdir(parents=True, exist_ok=True)
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail="File too large (max "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB)",
        )
    safe_name = _safe_filename(file.filename or "file")
    stored_name = f"{uuid.uuid4().hex}_{safe_name}"

    path = (media_dir / stored_name).resolve()
    path.write_bytes(data)
    return {
        "url": path,
        "file_name": safe_name,
        "size": len(data),
    }


@router.get(
    "/debug/backend-logs",
    response_class=PlainTextResponse,
    summary="Get backend application logs",
    description="Returns the last N lines of the backend log file",
    dependencies=[Depends(require_admin)]
)
async def get_backend_debug_logs(
    lines: int = Query(
        200,
        ge=20,
        le=MAX_DEBUG_LOG_LINES,
        description="Number of trailing log lines to return",
    ),
) -> str:
    """Return the tail of the project log file for the debug UI."""
    log_path = LOG_FILE_PATH.resolve()
    return _tail_text_file(log_path, lines=lines)


@router.get("/push-messages")
async def get_push_messages(
    request: Request,
    session_id: str | None = Query(None, description="Optional session id"),
):
    """
    Return pending push messages and visible approval requests.

    Messages:
    - With session_id: consumed messages for that session
    - Without session_id: admins get recent messages, users get none

    Approvals:
    - Admins can see all pending approvals
    - Users only see approvals attached to their own root session
    - Includes session_id/root_session_id in each approval for filtering
    """
    from ..console_push_store import get_recent, take
    from ..approvals import get_approval_service

    # Get messages (session-specific or admin-only global)
    if session_id:
        ensure_chat_access(request, session_id, allow_admin=True)
        messages = await take(session_id)
    else:
        messages = await get_recent() if is_admin_request(request) else []

    # Get pending approvals visible to the current user. Session polling is the
    # hot path, so avoid scanning all pending approvals for every browser tab.
    approval_svc = get_approval_service()
    if session_id:
        all_pending = await approval_svc.list_pending_metadata_by_root_session(
            session_id,
        )
    elif is_admin_request(request):
        all_pending = await approval_svc.list_all_pending()
    else:
        all_pending = []

    # Serialize approval data with root_session_id for frontend filtering
    approvals_data = []
    for p in all_pending:
        try:
            ensure_chat_access(request, p.root_session_id, allow_admin=True)
        except HTTPException:
            continue
        approvals_data.append(
            {
                "request_id": p.request_id,
                "session_id": p.session_id,
                "root_session_id": p.root_session_id,
                "owner_agent_id": p.owner_agent_id,
                "agent_id": p.agent_id,
                "tool_name": p.tool_name,
                "severity": p.severity,
                "findings_count": p.findings_count,
                "findings_summary": p.result_summary,
                "tool_params": p.extra.get("tool_call", {}).get("input", {}),
                "created_at": p.created_at,
                "timeout_seconds": p.timeout_seconds,
            },
        )

    return {"messages": messages, "pending_approvals": approvals_data}


@router.get("/channels", dependencies=[Depends(require_admin)])
async def list_channels():
    from ..inbox_store import list_channels as _list_channels
    return {"channels": await _list_channels()}


@router.get("/inbox/events")
async def get_inbox_events(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    source_type: str | None = Query(None),
    status: str | None = Query(None),
    agent_id: str | None = Query(None),
    unread_only: bool = Query(False),
):
    from ..inbox_store import list_events

    events = await list_events(
        limit=limit,
        offset=offset,
        source_type=source_type,
        status=status,
        agent_id=agent_id,
        unread_only=unread_only,
    )
    return {"events": events}


@router.post("/inbox/read")
async def post_mark_inbox_read(payload: MarkInboxReadRequest):
    from ..inbox_store import mark_all_read, mark_read

    if payload.all:
        updated = await mark_all_read()
    else:
        updated = await mark_read(payload.event_ids)
    return {"updated": updated}


@router.delete("/inbox/events/{event_id}")
async def delete_inbox_event(event_id: str):
    from ..inbox_store import delete_event
    from ..inbox_trace_store import delete_trace

    deleted, run_id, run_id_still_referenced = await delete_event(event_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="event not found")
    trace_deleted = False
    if run_id and not run_id_still_referenced:
        trace_deleted = await delete_trace(run_id)
    return {
        "deleted": True,
        "trace_deleted": trace_deleted,
        "run_id": run_id,
    }


@router.get("/inbox/traces/{run_id}")
async def get_inbox_trace(run_id: str):
    from ..inbox_trace_store import get_trace

    trace = await get_trace(run_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="trace not found")
    return trace
