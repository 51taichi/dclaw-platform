# -*- coding: utf-8 -*-
from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .manager import CronManager
from .models import (
    CronDispatchTargetItem,
    CronDispatchTargetsResponse,
    CronExecutionRecord,
    CronJobSpec,
    CronJobView,
)
from ..chat_access import current_user_id, is_admin_request

router = APIRouter(prefix="/cron", tags=["cron"])


async def get_cron_manager(
    request: Request,
) -> CronManager:
    """Get cron manager for the active agent."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    if workspace.cron_manager is None:
        raise HTTPException(
            status_code=500,
            detail="CronManager not initialized",
        )
    return workspace.cron_manager


def _job_user_id(job: CronJobSpec) -> str:
    meta_user_id = job.meta.get("created_by_user_id")
    if meta_user_id is not None:
        return str(meta_user_id)
    if job.dispatch and job.dispatch.target:
        return str(job.dispatch.target.user_id)
    if job.request and job.request.user_id is not None:
        return str(job.request.user_id)
    return ""


def _can_access_job(request: Request, job: CronJobSpec) -> bool:
    if is_admin_request(request):
        return True
    return _job_user_id(job) == current_user_id(request)


def _scope_job_to_request_user(request: Request, spec: CronJobSpec) -> CronJobSpec:
    if is_admin_request(request):
        return spec

    user_id = current_user_id(request)
    target = spec.dispatch.target.model_copy(update={"user_id": user_id})
    dispatch = spec.dispatch.model_copy(update={"target": target})
    job_request = spec.request
    if job_request is not None:
        job_request = job_request.model_copy(
            update={
                "user_id": user_id,
                "session_id": target.session_id,
            },
        )
    meta = {**spec.meta, "created_by_user_id": user_id}
    return spec.model_copy(
        update={
            "dispatch": dispatch,
            "request": job_request,
            "meta": meta,
        },
    )


async def _get_accessible_job(
    request: Request,
    job_id: str,
    mgr: CronManager,
) -> CronJobSpec:
    job = await mgr.get_job(job_id)
    if not job or not _can_access_job(request, job):
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.get(
    "/dispatch-targets",
    response_model=CronDispatchTargetsResponse,
)
async def list_dispatch_targets(
    request: Request,
    channel: str
    | None = Query(
        default=None,
        description="Optional channel filter",
    ),
    keyword: str
    | None = Query(
        default=None,
        description="Optional keyword for user/session/channel",
    ),
    limit: int = Query(
        default=500,
        ge=1,
        le=2000,
        description="Max number of target items",
    ),
):
    """List candidate dispatch targets derived from known chats."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    chats = await workspace.chat_manager.list_chats(
        user_id=None if is_admin_request(request) else current_user_id(request),
        channel=channel,
    )
    kw = (keyword or "").strip().lower()

    deduped: dict[tuple[str, str, str], CronDispatchTargetItem] = {}
    for chat in chats:
        item = CronDispatchTargetItem(
            channel=chat.channel,
            user_id=chat.user_id,
            session_id=chat.session_id,
        )
        if kw:
            haystack = (
                f"{item.channel} {item.user_id} {item.session_id}".lower()
            )
            if kw not in haystack:
                continue
        deduped[(item.channel, item.user_id, item.session_id)] = item
        if len(deduped) >= limit:
            break

    items = list(deduped.values())
    channels = sorted({item.channel for item in items})
    if "console" not in channels:
        channels.insert(0, "console")
    return CronDispatchTargetsResponse(channels=channels, items=items)


@router.get("/jobs", response_model=list[CronJobSpec])
async def list_jobs(
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    jobs = await mgr.list_jobs()
    if is_admin_request(request):
        return jobs
    return [job for job in jobs if _can_access_job(request, job)]


@router.get("/jobs/{job_id}", response_model=CronJobView)
async def get_job(
    job_id: str,
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    job = await _get_accessible_job(request, job_id, mgr)
    return CronJobView(spec=job, state=mgr.get_state(job_id))


@router.post("/jobs", response_model=CronJobSpec)
async def create_job(
    request: Request,
    spec: CronJobSpec,
    mgr: CronManager = Depends(get_cron_manager),
):
    # server generates id; ignore client-provided spec.id
    job_id = str(uuid.uuid4())
    created = _scope_job_to_request_user(request, spec).model_copy(
        update={"id": job_id},
    )
    await mgr.create_or_replace_job(created)
    return created


@router.put("/jobs/{job_id}", response_model=CronJobSpec)
async def replace_job(
    job_id: str,
    request: Request,
    spec: CronJobSpec,
    mgr: CronManager = Depends(get_cron_manager),
):
    await _get_accessible_job(request, job_id, mgr)
    if spec.id is None:
        spec.id = job_id
    elif spec.id != job_id:
        raise HTTPException(status_code=400, detail="job_id mismatch")
    updated = _scope_job_to_request_user(request, spec)
    await mgr.create_or_replace_job(updated)
    return updated


@router.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    await _get_accessible_job(request, job_id, mgr)
    ok = await mgr.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="job not found")
    return {"deleted": True}


@router.post("/jobs/{job_id}/pause")
async def pause_job(
    job_id: str,
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    await _get_accessible_job(request, job_id, mgr)
    try:
        await mgr.pause_job(job_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"paused": True}


@router.post("/jobs/{job_id}/resume")
async def resume_job(
    job_id: str,
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    await _get_accessible_job(request, job_id, mgr)
    try:
        await mgr.resume_job(job_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"resumed": True}


@router.post("/jobs/{job_id}/run")
async def run_job(
    job_id: str,
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    await _get_accessible_job(request, job_id, mgr)
    try:
        await mgr.run_job(job_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="job not found") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"started": True}


@router.get("/jobs/{job_id}/state")
async def get_job_state(
    job_id: str,
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    await _get_accessible_job(request, job_id, mgr)
    return mgr.get_state(job_id).model_dump(mode="json")


@router.get("/jobs/{job_id}/history", response_model=list[CronExecutionRecord])
async def get_job_history(
    job_id: str,
    request: Request,
    mgr: CronManager = Depends(get_cron_manager),
):
    await _get_accessible_job(request, job_id, mgr)
    return await mgr.get_history(job_id)
