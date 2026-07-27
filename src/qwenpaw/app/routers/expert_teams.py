# -*- coding: utf-8 -*-
"""Expert team APIs."""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, Any

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from ..expert_teams import (
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
    upsert_expert_team_template,
)
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
