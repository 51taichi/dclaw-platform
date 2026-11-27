# -*- coding: utf-8 -*-
"""Expert team APIs."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, Any

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from ..expert_teams import (
    ExpertTeamOrchestrator,
    ExpertTeamRunCreate,
    ExpertTeamTemplate,
    ExpertTeamTemplateInput,
    cancel_expert_team_run,
    create_expert_team_run,
    delete_expert_team_template,
    get_expert_team_run,
    get_expert_team_template,
    get_latest_expert_team_run_by_chat,
    list_expert_team_templates,
    patch_expert_team_template,
    publish_expert_team_run_state,
    resume_expert_team_run,
    upsert_expert_team_template,
)
from ..agent_context import get_agent_for_request
from ..billing.entrypoint import resume_user_billing_execution
from ..billing.usage import InsufficientUsageCreditsError
from ..channels.base import ContentType, TextContent
from ..chat_access import current_user_id, ensure_chat_access

user_router = APIRouter(tags=["expert-teams"])
admin_router = APIRouter(prefix="/expert-teams", tags=["admin-expert-teams"])


def _current_user_id(request: Request) -> str:
    return current_user_id(request)


def _ensure_user_run(run: Any, request: Request) -> Any:
    if run is None:
        raise HTTPException(status_code=404, detail="Expert team run not found")
    if run.user_id != _current_user_id(request):
        raise HTTPException(status_code=404, detail="Expert team run not found")
    return run


@user_router.get("/expert-teams", response_model=list[ExpertTeamTemplate])
async def list_user_expert_teams() -> list[ExpertTeamTemplate]:
    return list_expert_team_templates(enabled_only=True)


@user_router.get("/expert-teams/{team_id}", response_model=ExpertTeamTemplate)
async def get_user_expert_team(team_id: str) -> ExpertTeamTemplate:
    template = get_expert_team_template(team_id)
    if template is None or not template.enabled:
        raise HTTPException(status_code=404, detail="Expert team not found")
    return template


@user_router.post("/expert-teams/{team_id}/runs")
async def create_user_expert_team_run(
    team_id: str,
    payload: ExpertTeamRunCreate,
    request: Request,
) -> Any:
    chat_row = ensure_chat_access(request, payload.root_chat_id)
    root_chat_id = str(chat_row["id"])
    root_session_id = payload.root_session_id or str(
        chat_row["session_id"] or chat_row["id"],
    )
    try:
        return create_expert_team_run(
            team_id=team_id,
            root_chat_id=root_chat_id,
            root_session_id=root_session_id,
            user_id=_current_user_id(request),
            input_text=payload.input_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@user_router.get("/expert-team-runs/{run_id}")
async def get_user_expert_team_run(run_id: str, request: Request) -> Any:
    return _ensure_user_run(get_expert_team_run(run_id), request)


@user_router.get("/expert-team-runs/by-chat/{chat_id}")
async def get_user_expert_team_run_by_chat(chat_id: str, request: Request) -> Any:
    chat_row = ensure_chat_access(request, chat_id)
    run = get_latest_expert_team_run_by_chat(str(chat_row["id"]))
    if run is None:
        return None
    return _ensure_user_run(run, request)


@user_router.get("/expert-team-runs/{run_id}/stream")
async def stream_user_expert_team_run(run_id: str, request: Request) -> StreamingResponse:
    _ensure_user_run(get_expert_team_run(run_id), request)

    async def events() -> AsyncGenerator[str, None]:
        last = ""
        while True:
            run = get_expert_team_run(run_id)
            if run is None or run.user_id != _current_user_id(request):
                break
            data = json.dumps(run.model_dump(), ensure_ascii=False)
            if data != last:
                yield f"data: {data}\n\n"
                last = data
            if run.state in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(1.5)

    return StreamingResponse(events(), media_type="text/event-stream")


@user_router.post("/expert-team-runs/{run_id}/cancel")
async def cancel_user_expert_team_run(run_id: str, request: Request) -> Any:
    _ensure_user_run(get_expert_team_run(run_id), request)
    run = cancel_expert_team_run(run_id)
    return _ensure_user_run(run, request)


@user_router.post("/expert-teams/runs/{run_id}/continue")
async def continue_user_expert_team_run(run_id: str, request: Request) -> Any:
    """Resume one paused run with its original wallet/order/execution."""
    run = _ensure_user_run(get_expert_team_run(run_id), request)
    if (
        run.state != "paused_insufficient_balance"
        or not run.billing_usage_order_id
        or not run.next_member_key
    ):
        raise HTTPException(status_code=409, detail="Expert team run is not paused")
    user_id = _current_user_id(request)
    prepared = resume_user_billing_execution(
        run.billing_usage_order_id,
        user_id,
    )
    if prepared is None:
        raise HTTPException(status_code=409, detail="Expert team run is resuming")
    resumed = resume_expert_team_run(run_id, user_id)
    if resumed is None:
        prepared.pause_insufficient(
            next_member_key=run.next_member_key,
            required_credits=run.required_credits or 0,
        )
        raise HTTPException(status_code=409, detail="Expert team run is resuming")

    workspace = await get_agent_for_request(request)
    console_channel = await workspace.channel_manager.get_channel("console")
    if console_channel is None:
        prepared.pause_expert_team_insufficient(
            run_id=run.id,
            payer_user_id=user_id,
            next_member_key=run.next_member_key,
            required_credits=run.required_credits or 0,
        )
        raise HTTPException(status_code=503, detail="Channel Console not found")
    native_payload = {
        "channel_id": "console",
        "sender_id": user_id,
        "content_parts": [
            TextContent(type=ContentType.TEXT, text=run.input_text),
        ],
        "meta": {
            "session_id": run.root_session_id,
            "user_id": user_id,
            "expert_team_id": run.team_id,
            "expert_team_run_id": run.id,
        },
    }
    payload = {
        "run_id": run.id,
        "team_id": run.team_id,
        "root_chat_id": run.root_chat_id,
        "root_session_id": run.root_session_id,
        "native_payload": native_payload,
    }
    orchestrator = ExpertTeamOrchestrator(
        workspace=workspace,
        console_channel=console_channel,
    )

    async def producer(resume_payload):
        with prepared.activate():
            try:
                async for event in orchestrator.stream_one(resume_payload):
                    yield event
            except InsufficientUsageCreditsError as exc:
                current_run = get_expert_team_run(run.id)
                next_member = next(
                    (
                        member
                        for member in (
                            current_run.members if current_run is not None else []
                        )
                        if member.state
                        not in {"completed", "failed", "cancelled"}
                    ),
                    None,
                )
                if next_member is not None:
                    pause_saved = prepared.pause_expert_team_insufficient(
                        run_id=run.id,
                        payer_user_id=user_id,
                        next_member_key=next_member.member_key,
                        required_credits=exc.required,
                    )
                    if pause_saved:
                        publish_expert_team_run_state(run.id)
                yield "data: " + json.dumps(
                    {
                        "type": "billing.error",
                        "code": "INSUFFICIENT_CREDITS",
                        "available_credits": exc.available,
                        "required_credits": exc.required,
                        "top_up_path": "/wallet",
                    },
                ) + "\n\n"
                return
            except asyncio.CancelledError:
                prepared.finalize("cancelled", error_code="CANCELLED")
                raise
            except BaseException:
                prepared.finalize("failed", error_code="MODEL_ERROR")
                raise
            final_run = get_expert_team_run(run.id)
            if final_run is not None and final_run.state in {
                "failed",
                "cancelled",
            }:
                prepared.finalize(
                    "cancelled"
                    if final_run.state == "cancelled"
                    else "failed",
                    error_code="TEAM_RUN_" + final_run.state.upper(),
                )
            else:
                prepared.finalize_completed()

    try:
        _queue, is_new = await workspace.task_tracker.attach_or_start(
            run.root_chat_id,
            payload,
            producer,
        )
    except BaseException:
        prepared.pause_expert_team_insufficient(
            run_id=run.id,
            payer_user_id=user_id,
            next_member_key=run.next_member_key,
            required_credits=run.required_credits or 0,
        )
        raise
    if not is_new:
        prepared.pause_expert_team_insufficient(
            run_id=run.id,
            payer_user_id=user_id,
            next_member_key=run.next_member_key,
            required_credits=run.required_credits or 0,
        )
        raise HTTPException(status_code=409, detail="Expert team run is resuming")
    return {"run_id": run.id, "status": "running"}


@admin_router.get("", response_model=list[ExpertTeamTemplate])
async def list_admin_expert_teams() -> list[ExpertTeamTemplate]:
    return list_expert_team_templates(enabled_only=False)


@admin_router.post("", response_model=ExpertTeamTemplate)
async def create_admin_expert_team(payload: ExpertTeamTemplateInput) -> ExpertTeamTemplate:
    return upsert_expert_team_template(payload)


@admin_router.get("/{team_id}", response_model=ExpertTeamTemplate)
async def get_admin_expert_team(team_id: str) -> ExpertTeamTemplate:
    template = get_expert_team_template(team_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Expert team not found")
    return template


@admin_router.put("/{team_id}", response_model=ExpertTeamTemplate)
async def put_admin_expert_team(
    team_id: str,
    payload: ExpertTeamTemplateInput,
) -> ExpertTeamTemplate:
    data = payload.model_copy(update={"id": team_id})
    return upsert_expert_team_template(data)


@admin_router.patch("/{team_id}", response_model=ExpertTeamTemplate)
async def patch_admin_expert_team(team_id: str, payload: dict[str, Any]) -> ExpertTeamTemplate:
    template = patch_expert_team_template(team_id, payload)
    if template is None:
        raise HTTPException(status_code=404, detail="Expert team not found")
    return template


@admin_router.delete("/{team_id}")
async def delete_admin_expert_team(team_id: str) -> dict[str, bool]:
    return {"deleted": delete_expert_team_template(team_id)}
