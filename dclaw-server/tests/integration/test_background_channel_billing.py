# -*- coding: utf-8 -*-
"""Billing ownership contracts for background channel executions."""
from __future__ import annotations

import pytest
from contextlib import contextmanager

from qwenpaw.app.billing import payer
from qwenpaw.app.billing.usage import InsufficientUsageCreditsError
from qwenpaw.app.crons.manager import CronManager
from qwenpaw.app.crons.models import CronJobSpec


@pytest.mark.parametrize("channel", ["wechat", "dingtalk"])
def test_authenticated_channel_binding_resolves_workspace_owner(
    channel,
    monkeypatch,
):
    monkeypatch.setattr(payer, "_user_exists", lambda user_id: user_id == "7")

    resolved = payer.resolve_channel_payer(
        channel,
        "external-user-123",
        {
            "bound_user_id": "7",
            "binding_authenticated": True,
        },
    )

    assert resolved == "7"


def test_unbound_channel_identity_fails_closed(monkeypatch):
    monkeypatch.setattr(payer, "_user_exists", lambda _user_id: True)

    with pytest.raises(payer.BillingPayerResolutionError):
        payer.resolve_channel_payer("wechat", "external-user-123", {})


def test_deleted_channel_owner_fails_closed(monkeypatch):
    monkeypatch.setattr(payer, "_user_exists", lambda _user_id: False)

    with pytest.raises(payer.BillingPayerResolutionError):
        payer.resolve_channel_payer(
            "dingtalk",
            "external-user-123",
            {
                "bound_user_id": "7",
                "binding_authenticated": True,
            },
        )


class _CronRepo:
    def __init__(self):
        self.history = []

    async def append_history(self, _job_id, record, *, limit):
        _ = limit
        self.history.append(record)
        return self.history


def _agent_job() -> CronJobSpec:
    return CronJobSpec(
        id="job-1",
        name="daily report",
        schedule={"type": "cron", "cron": "0 9 * * *"},
        task_type="agent",
        request={"input": "report"},
        dispatch={
            "channel": "console",
            "target": {"user_id": "99", "session_id": "session-1"},
        },
        meta={"created_by_user_id": "7"},
    )


@pytest.mark.asyncio
async def test_scheduled_job_uses_owner_billing_context(monkeypatch):
    repo = _CronRepo()
    manager = CronManager(repo=repo, runner=None, channel_manager=None)
    calls = []

    class _Prepared:
        @contextmanager
        def activate(self):
            calls.append("active")
            yield

        def finalize_completed(self):
            calls.append("completed")

        def finalize(self, state, error_code=None):
            calls.append((state, error_code))

    async def execute(_job):
        calls.append("provider")
        return {}

    manager._executor.execute = execute
    monkeypatch.setattr(
        "qwenpaw.app.crons.manager.resolve_job_payer",
        lambda _job: "7",
    )
    monkeypatch.setattr(
        "qwenpaw.app.crons.manager.prepare_user_billing_execution",
        lambda *_args, **_kwargs: _Prepared(),
    )

    await manager._execute_once(_agent_job())

    assert calls == ["active", "provider", "completed"]
    assert repo.history[-1].status == "success"


@pytest.mark.asyncio
async def test_scheduled_insufficient_balance_is_safe_and_not_retried(
    monkeypatch,
):
    repo = _CronRepo()
    manager = CronManager(repo=repo, runner=None, channel_manager=None)

    class _Prepared:
        @contextmanager
        def activate(self):
            yield

        def finalize(self, state, error_code=None):
            assert (state, error_code) == ("failed", "INSUFFICIENT_CREDITS")

    async def execute(_job):
        raise InsufficientUsageCreditsError(required=5, available=0)

    manager._executor.execute = execute
    monkeypatch.setattr(
        "qwenpaw.app.crons.manager.resolve_job_payer",
        lambda _job: "7",
    )
    monkeypatch.setattr(
        "qwenpaw.app.crons.manager.prepare_user_billing_execution",
        lambda *_args, **_kwargs: _Prepared(),
    )

    with pytest.raises(InsufficientUsageCreditsError):
        await manager._execute_once(_agent_job())

    assert repo.history[-1].status == "error"
    assert repo.history[-1].error == "INSUFFICIENT_CREDITS"
