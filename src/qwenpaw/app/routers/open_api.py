# -*- coding: utf-8 -*-
"""External Open API message runtime routes."""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from ..expert_teams import (
    ExpertTeamOrchestrator,
    attach_run_to_chat,
    create_expert_team_run,
    get_expert_team_template,
    get_latest_expert_team_run_by_chat,
)
from ..open_api.runtime import (
    OpenMessageRequest,
    PreparedOpenRun,
    prepare_open_agent_chat,
    prepare_open_expert_team_chat,
)
from ..storage.repos.open_api_repo import get_open_api_repository
from ..task_limits import get_task_limiter


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/open/v1", tags=["open-api"])


@router.post("/targets/{public_id}/messages", status_code=200)
async def post_open_message(
    public_id: str,
    payload: OpenMessageRequest,
    request: Request,
) -> StreamingResponse:
    started_at = time.monotonic()
    invocation_id = str(uuid.uuid4())
    repo = get_open_api_repository()
    publication = repo.get_enabled_publication_by_public_id(public_id)
    attached_existing_run = False
    if publication is None:
        raise HTTPException(
            status_code=404,
            detail="Open API publication not found",
        )
    if str(getattr(request.state, "open_publication_id", "")) != str(publication["id"]):
        raise HTTPException(
            status_code=403,
            detail="Open API key is not allowed for this publication",
        )

    prepared: PreparedOpenRun | None = None
    expert_team_run_id = ""
    try:
        if payload.stream is False:
            raise HTTPException(
                status_code=400,
                detail="Open API messages currently require stream=true",
            )
        target_type = str(publication["target_type"])
        if target_type == "agent":
            prepared = await prepare_open_agent_chat(request, publication, payload)
            stream_fn = prepared.console_channel.stream_one
            stream_payload = prepared.payload
        elif target_type == "expert_team":
            team = get_expert_team_template(str(publication["target_id"]))
            if team is None or not bool(getattr(team, "enabled", False)):
                raise HTTPException(
                    status_code=404,
                    detail="Open API expert team not found",
                )
            prepared = await prepare_open_expert_team_chat(
                request,
                publication,
                payload,
                leader_agent_id=str(getattr(team, "leader_agent_id")),
            )
            expert_team_run_id = str(uuid.uuid4())
            stream_payload = {
                "run_id": expert_team_run_id,
                "team_id": str(team.id),
                "root_chat_id": prepared.chat_id,
                "root_session_id": prepared.session_id,
                "native_payload": prepared.payload,
            }
            orchestrator = ExpertTeamOrchestrator(
                workspace=prepared.workspace,
                console_channel=prepared.console_channel,
            )

            async def stream_fn(team_payload):
                run = create_expert_team_run(
                    team_id=str(team.id),
                    root_chat_id=prepared.chat_id,
                    root_session_id=prepared.session_id,
                    user_id=str(request.state.user_id),
                    input_text=payload.message,
                    run_id=str(team_payload["run_id"]),
                )
                team_payload["run_id"] = str(run.id)
                await attach_run_to_chat(
                    prepared.workspace,
                    prepared.chat_id,
                    run,
                )
                async for item in orchestrator.stream_one(team_payload):
                    yield item
        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported Open API target type",
            )

        permit = await get_task_limiter(request.app).try_acquire(
            agent_id=prepared.agent_id,
            user_id=str(request.state.user_id),
        )
        if permit is None:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Too many running tasks. Please wait for an existing task "
                    "to finish and try again."
                ),
            )

        repo.create_invocation(
            _invocation_row(
                invocation_id=invocation_id,
                request=request,
                publication=publication,
                payload=payload,
                chat_id=prepared.chat_id,
                status="accepted",
                status_code=202,
                latency_ms=_latency_ms(started_at),
                error_summary="",
            ),
        )

        async def limited_stream_fn(stream_payload):
            stream_started_at = time.monotonic()
            stream_failure: tuple[str, str] | None = None
            try:
                async for item in stream_fn(stream_payload):
                    if stream_failure is None:
                        stream_failure = _extract_stream_failure(item)
                    yield item
                if stream_failure is not None:
                    status, error_summary = stream_failure
                    _update_invocation_status(
                        repo,
                        invocation_id=invocation_id,
                        status=status,
                        status_code=_stream_failure_status_code(status),
                        latency_ms=_latency_ms(stream_started_at),
                        error_summary=error_summary,
                    )
                    return
                _update_invocation_status(
                    repo,
                    invocation_id=invocation_id,
                    status="succeeded",
                    status_code=200,
                    latency_ms=_latency_ms(stream_started_at),
                    error_summary="",
                )
            except Exception as exc:
                _update_invocation_status(
                    repo,
                    invocation_id=invocation_id,
                    status="failed",
                    status_code=500,
                    latency_ms=_latency_ms(stream_started_at),
                    error_summary=str(exc),
                )
                raise
            finally:
                if permit is not None:
                    await permit.release()

        try:
            queue, is_new_run = await prepared.workspace.task_tracker.attach_or_start(
                prepared.chat_id,
                stream_payload,
                limited_stream_fn,
                on_finish=permit.release if permit is not None else None,
            )
        except Exception:
            if permit is not None:
                await permit.release()
            raise
        attached_existing_run = not is_new_run
        _update_invocation_status(
            repo,
            invocation_id=invocation_id,
            status="running",
            status_code=202,
            latency_ms=_latency_ms(started_at),
            error_summary="",
        )
        if not is_new_run and permit is not None:
            await permit.release()
        if not is_new_run and target_type == "expert_team":
            expert_team_run_id = ""
            running_payload = await _get_tracker_payload(
                prepared.workspace.task_tracker,
                prepared.chat_id,
            )
            if isinstance(running_payload, dict):
                expert_team_run_id = str(running_payload.get("run_id") or "")
            if not expert_team_run_id:
                latest_run = get_latest_expert_team_run_by_chat(prepared.chat_id)
                expert_team_run_id = str(latest_run.id) if latest_run else ""
    except HTTPException as exc:
        _record_failed_invocation(
            repo,
            invocation_id=invocation_id,
            request=request,
            publication=publication,
            payload=payload,
            prepared=prepared,
            status_code=exc.status_code,
            started_at=started_at,
            error_summary=str(exc.detail),
        )
        raise
    except Exception as exc:
        _record_failed_invocation(
            repo,
            invocation_id=invocation_id,
            request=request,
            publication=publication,
            payload=payload,
            prepared=prepared,
            status_code=500,
            started_at=started_at,
            error_summary=str(exc),
        )
        raise

    tracker = prepared.workspace.task_tracker

    async def event_generator() -> AsyncGenerator[str, None]:
        stream_it = tracker.stream_from_queue(queue, prepared.chat_id)
        status_recorded = False
        stream_completed = False
        observed_failure: tuple[str, str] | None = None
        try:
            try:
                async for event_data in stream_it:
                    if attached_existing_run and observed_failure is None:
                        observed_failure = _extract_stream_failure(event_data)
                    yield event_data
                disconnected = await _request_is_disconnected(request)
                stream_completed = not disconnected
                if attached_existing_run:
                    status_recorded = True
                    if disconnected:
                        _update_invocation_status(
                            repo,
                            invocation_id=invocation_id,
                            status="cancelled",
                            status_code=499,
                            latency_ms=_latency_ms(started_at),
                            error_summary="stream closed before completion",
                        )
                    elif observed_failure is not None:
                        status, error_summary = observed_failure
                        _update_invocation_status(
                            repo,
                            invocation_id=invocation_id,
                            status=status,
                            status_code=_stream_failure_status_code(status),
                            latency_ms=_latency_ms(started_at),
                            error_summary=error_summary,
                        )
                    else:
                        _update_invocation_status(
                            repo,
                            invocation_id=invocation_id,
                            status="succeeded",
                            status_code=200,
                            latency_ms=_latency_ms(started_at),
                            error_summary="",
                        )
            except Exception as exc:
                logger.exception("Open API message stream error")
                if attached_existing_run:
                    status_recorded = True
                    _update_invocation_status(
                        repo,
                        invocation_id=invocation_id,
                        status="failed",
                        status_code=500,
                        latency_ms=_latency_ms(started_at),
                        error_summary=str(exc),
                    )
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        finally:
            await stream_it.aclose()
            if attached_existing_run and not stream_completed and not status_recorded:
                _update_invocation_status(
                    repo,
                    invocation_id=invocation_id,
                    status="cancelled",
                    status_code=499,
                    latency_ms=_latency_ms(started_at),
                    error_summary="stream closed before completion",
                )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-QwenPaw-Chat-Id": prepared.chat_id,
            "X-QwenPaw-Session-Id": prepared.session_id,
            "X-QwenPaw-Open-Invocation-Id": invocation_id,
            "X-QwenPaw-Expert-Team-Run-Id": expert_team_run_id,
        },
    )


def _record_failed_invocation(
    repo: Any,
    *,
    invocation_id: str,
    request: Request,
    publication: dict[str, Any],
    payload: OpenMessageRequest,
    prepared: PreparedOpenRun | None,
    status_code: int,
    started_at: float,
    error_summary: str,
) -> None:
    try:
        updated = repo.update_invocation_status(
            invocation_id,
            status="failed",
            status_code=status_code,
            latency_ms=_latency_ms(started_at),
            error_summary=error_summary,
        )
        if updated is not None:
            return
        repo.create_invocation(
            _invocation_row(
                invocation_id=invocation_id,
                request=request,
                publication=publication,
                payload=payload,
                chat_id=prepared.chat_id if prepared else None,
                status="failed",
                status_code=status_code,
                latency_ms=_latency_ms(started_at),
                error_summary=error_summary,
            ),
        )
    except Exception:
        logger.exception("Failed to record Open API invocation failure")


def _update_invocation_status(
    repo: Any,
    *,
    invocation_id: str,
    status: str,
    status_code: int,
    latency_ms: int,
    error_summary: str,
) -> None:
    try:
        repo.update_invocation_status(
            invocation_id,
            status=status,
            status_code=status_code,
            latency_ms=latency_ms,
            error_summary=error_summary,
        )
    except Exception:
        logger.exception("Failed to update Open API invocation status")


def _extract_stream_failure(event_data: str) -> tuple[str, str] | None:
    for raw_line in event_data.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        error = payload.get("error")
        if isinstance(error, str):
            return "failed", error
        if isinstance(error, dict):
            return "failed", json.dumps(error, ensure_ascii=False)
        run = payload.get("run")
        if isinstance(run, dict):
            state = run.get("state")
            if state == "failed":
                summary = run.get("error")
                return "failed", str(summary or "Expert team run failed")
            if state == "cancelled":
                summary = run.get("error")
                return "cancelled", str(summary or "Expert team run cancelled")
    return None


def _stream_failure_status_code(status: str) -> int:
    return 499 if status == "cancelled" else 500


async def _request_is_disconnected(request: Request) -> bool:
    try:
        return bool(await request.is_disconnected())
    except Exception:
        return False


async def _get_tracker_payload(tracker: Any, run_key: str) -> Any | None:
    getter = getattr(tracker, "get_payload", None)
    if not callable(getter):
        return None
    try:
        return await getter(run_key)
    except Exception:
        logger.exception("Failed to read active Open API run payload")
        return None


def _invocation_row(
    *,
    invocation_id: str,
    request: Request,
    publication: dict[str, Any],
    payload: OpenMessageRequest,
    chat_id: str | None,
    status: str,
    status_code: int,
    latency_ms: int,
    error_summary: str,
) -> dict[str, Any]:
    return {
        "id": invocation_id,
        "app_id": str(request.state.open_app_id),
        "publication_id": str(publication["id"]),
        "api_key_id": str(request.state.open_api_key_id),
        "target_type": str(publication["target_type"]),
        "target_id": str(publication["target_id"]),
        "chat_id": chat_id,
        "external_session_id": payload.external_session_id or "default",
        "external_user_id": payload.external_user_id,
        "status": status,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "token_summary": {},
        "error_summary": error_summary,
    }


def _latency_ms(started_at: float) -> int:
    return max(0, int((time.monotonic() - started_at) * 1000))
