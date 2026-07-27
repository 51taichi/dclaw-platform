# -*- coding: utf-8 -*-
"""Tests for user-scoped cron automation access."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.crons import api as cron_api
from qwenpaw.app.crons.models import CronJobSpec


class _FakeCronManager:
    def __init__(self, jobs: list[CronJobSpec]):
        self.jobs = jobs
        self.saved: CronJobSpec | None = None

    async def list_jobs(self) -> list[CronJobSpec]:
        return self.jobs

    async def get_job(self, job_id: str) -> CronJobSpec | None:
        return next((job for job in self.jobs if job.id == job_id), None)

    async def create_or_replace_job(self, spec: CronJobSpec) -> None:
        self.saved = spec

    def get_state(self, job_id: str):
        return SimpleNamespace(model_dump=lambda mode="json": {})


def _request(user_id: str, role: str = "user"):
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id, role=role))


def _job(job_id: str, user_id: str) -> CronJobSpec:
    return CronJobSpec(
        id=job_id,
        name=f"job-{job_id}",
        schedule={"type": "cron", "cron": "0 9 * * *", "timezone": "UTC"},
        task_type="agent",
        request={"input": "hello"},
        dispatch={
            "type": "channel",
            "channel": "console",
            "target": {"user_id": user_id, "session_id": f"session-{job_id}"},
            "mode": "final",
        },
    )


@pytest.mark.asyncio
async def test_user_cron_list_only_returns_current_users_jobs() -> None:
    mgr = _FakeCronManager([_job("a", "7"), _job("b", "8")])

    jobs = await cron_api.list_jobs(_request("7"), mgr)

    assert [job.id for job in jobs] == ["a"]


@pytest.mark.asyncio
async def test_user_cron_create_is_scoped_to_current_user() -> None:
    mgr = _FakeCronManager([])
    spec = _job("client-id", "default")

    created = await cron_api.create_job(_request("7"), spec, mgr)

    assert created.id != "client-id"
    assert created.dispatch.target.user_id == "7"
    assert created.request is not None
    assert created.request.user_id == "7"
    assert created.meta["created_by_user_id"] == "7"
    assert mgr.saved == created


@pytest.mark.asyncio
async def test_user_cron_get_rejects_other_users_job() -> None:
    mgr = _FakeCronManager([_job("b", "8")])

    with pytest.raises(HTTPException) as exc:
        await cron_api.get_job("b", _request("7"), mgr)

    assert exc.value.status_code == 404
