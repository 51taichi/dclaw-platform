# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, text, update

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_execution_repo import (
    BillingExecutionCommand,
    BillingExecutionRepository,
    ExecutionReplayConflictError,
)
from qwenpaw.app.storage.schema import (
    billing_price_catalogs,
    billing_executions,
    billing_usage_orders,
    billing_wallets,
    create_all,
)
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def execution_repo(tmp_path):
    engine = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "execution.db")},
        ),
    )
    create_all(engine)
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            insert(billing_wallets).values(
                id="wallet-1",
                owner_type="user",
                owner_id="user-1",
            ),
        )
        conn.execute(
            insert(billing_price_catalogs).values(
                id="catalog-1",
                version="v1",
                status="published",
                effective_at=now,
            ),
        )
        conn.execute(
            insert(billing_usage_orders).values(
                id="order-1",
                wallet_id="wallet-1",
                catalog_id="catalog-1",
                business_key="billing:client:chat-1:request-1",
                source_type="client",
                source_id="chat-1",
                provider_id="request",
                model_key="request",
                capability="text",
            ),
        )
    try:
        yield BillingExecutionRepository(engine)
    finally:
        engine.dispose()


def _command(request_sha256: str = "a" * 64) -> BillingExecutionCommand:
    return BillingExecutionCommand(
        execution_id="execution-1",
        usage_order_id="order-1",
        payer_user_id="user-1",
        source_type="client",
        source_id="chat-1",
        request_sha256=request_sha256,
    )


def test_create_replays_matching_execution_and_rejects_payload_drift(
    execution_repo,
):
    first = execution_repo.create_or_replay(_command())
    replay = execution_repo.create_or_replay(_command())

    assert replay == first
    assert first.state == "accepted"
    assert first.fence_generation == 0

    with pytest.raises(ExecutionReplayConflictError):
        execution_repo.create_or_replay(_command("b" * 64))


def test_claim_renew_finalize_uses_owner_and_generation(execution_repo):
    execution_repo.create_or_replay(_command())

    fence = execution_repo.claim(
        "execution-1",
        "worker-a",
        lease_seconds=30,
    )

    assert fence is not None
    assert fence.owner_token == "worker-a"
    assert fence.generation == 1
    assert execution_repo.claim(
        "execution-1",
        "worker-b",
        lease_seconds=30,
    ) is None
    assert execution_repo.renew(
        "execution-1",
        fence,
        lease_seconds=30,
    )
    assert not execution_repo.finalize(
        "execution-1",
        type(fence)(owner_token="worker-b", generation=1),
        state="succeeded",
        error_code=None,
    )
    assert execution_repo.finalize(
        "execution-1",
        fence,
        state="succeeded",
        error_code=None,
    )
    assert execution_repo.get("execution-1").state == "succeeded"


def test_takeover_requires_expired_lease_and_fences_old_owner(execution_repo):
    execution_repo.create_or_replay(_command())
    old_fence = execution_repo.claim(
        "execution-1",
        "worker-a",
        lease_seconds=30,
    )
    assert old_fence is not None

    assert execution_repo.takeover(
        "execution-1",
        "worker-b",
        lease_seconds=30,
    ) is None

    with execution_repo.engine.begin() as conn:
        conn.execute(
            update(billing_executions)
            .where(billing_executions.c.id == "execution-1")
            .values(lease_expires_at=text("datetime('now', '-1 second')")),
        )

    new_fence = execution_repo.takeover(
        "execution-1",
        "worker-b",
        lease_seconds=30,
    )
    assert new_fence is not None
    assert new_fence.owner_token == "worker-b"
    assert new_fence.generation == 2
    assert not execution_repo.finalize(
        "execution-1",
        old_fence,
        state="succeeded",
        error_code=None,
    )
