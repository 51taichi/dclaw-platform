# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from qwenpaw.app.billing.context import BillingSource
from qwenpaw.app.billing.coordinator import (
    BillingCommand,
    BillingCoordinator,
    BillingRequestConflictError,
)
from qwenpaw.app.billing.pricing import (
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
)
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.schema import (
    billing_executions,
    billing_usage_orders,
    billing_wallets,
    create_all,
)
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def coordinator(tmp_path):
    engine = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "coordinator.db")},
        ),
    )
    create_all(engine)
    pricing = PriceCatalogService(PriceCatalogRepository(engine))
    pricing.publish(
        PriceCatalogDraft(
            version="2026-08-general",
            effective_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            rules=(
                PriceRule(
                    id="text-rule",
                    provider_id="provider",
                    model_key="model",
                    capability="text",
                    unit_type="tokens",
                    input_credits_per_1k=1,
                    output_credits_per_1k=1,
                    metadata={"economic_tier": "standard"},
                ),
            ),
        ),
    )
    try:
        yield BillingCoordinator(BillingRepository(engine), pricing), engine
    finally:
        engine.dispose()


def _command(payload=None):
    return BillingCommand(
        payer_user_id="user-1",
        source=BillingSource(
            type="client",
            id="chat-1",
            expert_id="luyu_traffic_operator",
        ),
        request_key="message-1",
        payload=payload or {"message": "secret customer prompt"},
    )


def test_begin_execution_atomically_locks_wallet_catalog_and_safe_snapshot(
    coordinator,
):
    service, engine = coordinator

    first = service.begin_execution(_command())
    replay = service.begin_execution(_command())

    assert replay == first
    assert first.payer_user_id == "user-1"
    assert first.catalog_version == "2026-08-general"
    assert first.mode == "enforced"
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(billing_wallets)) == 1
        assert (
            conn.scalar(select(func.count()).select_from(billing_usage_orders))
            == 1
        )
        assert (
            conn.scalar(select(func.count()).select_from(billing_executions))
            == 1
        )
        snapshot = conn.scalar(
            select(billing_usage_orders.c.request_snapshot_json),
        )
    decoded = json.loads(snapshot)
    assert decoded["source"] == {
        "expert_id": "luyu_traffic_operator",
        "expert_team_run_id": None,
        "id": "chat-1",
        "type": "client",
    }
    assert "secret customer prompt" not in snapshot


def test_begin_execution_rejects_same_key_payload_drift(coordinator):
    service, _engine = coordinator
    service.begin_execution(_command())

    with pytest.raises(BillingRequestConflictError):
        service.begin_execution(_command({"message": "changed"}))


def test_begin_execution_rolls_back_wallet_order_and_execution(tmp_path):
    engine = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "rollback.db")},
        ),
    )
    create_all(engine)
    pricing = PriceCatalogService(PriceCatalogRepository(engine))
    pricing.publish(
        PriceCatalogDraft(
            version="rollback-v1",
            effective_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            rules=(
                PriceRule(
                    id="rollback-text-rule",
                    provider_id="provider",
                    model_key="model",
                    capability="text",
                    unit_type="tokens",
                    input_credits_per_1k=1,
                    output_credits_per_1k=1,
                    metadata={"economic_tier": "standard"},
                ),
            ),
        ),
    )

    def fail_after_order():
        raise RuntimeError("injected failure")

    service = BillingCoordinator(
        BillingRepository(engine),
        pricing,
        after_order_insert=fail_after_order,
    )
    with pytest.raises(RuntimeError, match="injected failure"):
        service.begin_execution(_command())

    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(billing_wallets)) == 0
        assert conn.scalar(
            select(func.count()).select_from(billing_usage_orders),
        ) == 0
        assert conn.scalar(
            select(func.count()).select_from(billing_executions),
        ) == 0
    engine.dispose()
