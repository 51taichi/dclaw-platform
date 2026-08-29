# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update

from qwenpaw.app.billing.context import BillingSource
from qwenpaw.app.billing.entrypoint import prepare_user_billing_execution
from qwenpaw.app.billing.pricing import (
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
)
from qwenpaw.app.billing.recovery import recover_general_billing
from qwenpaw.app.billing.usage import SettleModelCall
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.schema import (
    billing_executions,
    billing_ledger_entries,
    create_all,
)
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def recovery_engine(tmp_path, monkeypatch):
    engine = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "general-recovery.db")},
        ),
    )
    create_all(engine)
    PriceCatalogService(PriceCatalogRepository(engine)).publish(
        PriceCatalogDraft(
            version="recovery-v1",
            effective_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            rules=(
                PriceRule(
                    id="recovery-rule",
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
    monkeypatch.setattr(
        "qwenpaw.app.billing.entrypoint.get_app_engine",
        lambda: engine,
    )
    try:
        yield engine
    finally:
        engine.dispose()


def _prepared(engine, key: str, *, source_type: str = "client"):
    prepared = prepare_user_billing_execution(
        "user-1",
        BillingSource(type=source_type, id=f"source-{key}"),
        key,
        {"request": key},
        lease_seconds=60,
    )
    BillingRepository(engine).grant(
        prepared.session.wallet_id,
        credits=20,
        credit_type="purchased",
        expires_at=None,
        idempotency_key=f"fund-{key}",
    )
    return prepared


def _expire(engine, execution_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(billing_executions)
            .where(billing_executions.c.id == execution_id)
            .values(
                lease_expires_at=func.datetime("now", "-1 minute"),
            ),
        )


def _ledger_count(engine) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                select(func.count()).select_from(billing_ledger_entries),
            ).scalar_one(),
        )


def test_recovery_releases_precontact_hold_once(recovery_engine):
    prepared = _prepared(recovery_engine, "precontact")
    with prepared.activate():
        prepared.meter.before_call(
            provider_id="provider",
            model_key="model",
            messages=[],
            max_output_tokens=100,
        )
    _expire(recovery_engine, prepared.session.execution_id)

    assert recover_general_billing(recovery_engine) == 1
    after_first = _ledger_count(recovery_engine)
    assert recover_general_billing(recovery_engine) == 0
    assert _ledger_count(recovery_engine) == after_first

    items = prepared.usage_service.list_items(prepared.session.usage_order_id)
    assert [item["status"] for item in items] == ["released"]
    assert (
        BillingRepository(recovery_engine)
        .balance(
            prepared.session.wallet_id,
        )
        .held
        == 0
    )


def test_recovery_preserves_contacted_unknown_and_paused_run(recovery_engine):
    contacted = _prepared(recovery_engine, "contacted")
    with contacted.activate():
        call = contacted.meter.before_call(
            provider_id="provider",
            model_key="model",
            messages=[],
            max_output_tokens=100,
        )
        contacted.meter.mark_provider_call_started(call)
    _expire(recovery_engine, contacted.session.execution_id)

    paused = _prepared(recovery_engine, "paused", source_type="expert_team")
    assert paused.pause_insufficient(
        next_member_key="member-2",
        required_credits=3,
    )

    assert recover_general_billing(recovery_engine) == 1
    contacted_row = contacted.execution_repository.get(
        contacted.session.execution_id,
    )
    paused_row = paused.execution_repository.get(paused.session.execution_id)
    assert contacted_row is not None and contacted_row.state == "reconciling"
    assert paused_row is not None
    assert paused_row.state == "paused_insufficient_balance"
    assert paused_row.resume_state_json == (
        '{"next_member_key":"member-2","required_credits":3}'
    )


def test_recovery_repairs_fully_resolved_stale_execution(recovery_engine):
    prepared = _prepared(recovery_engine, "resolved")
    with prepared.activate():
        call = prepared.meter.before_call(
            provider_id="provider",
            model_key="model",
            messages=[],
            max_output_tokens=100,
        )
        prepared.meter.mark_provider_call_started(call)
        prepared.usage_service.settle_model_call(
            SettleModelCall(
                usage_order_id=prepared.session.usage_order_id,
                item_key=call.item_key,
                supplier_reference="supplier-1",
                billability="billable",
                evidence={"response_class": "success"},
                execution_outcome="succeeded",
                actual_input_tokens=10,
                actual_output_tokens=20,
                execution_guard=call.execution_guard,
            ),
        )
    _expire(recovery_engine, prepared.session.execution_id)

    assert recover_general_billing(recovery_engine) == 1
    record = prepared.execution_repository.get(prepared.session.execution_id)
    assert record is not None and record.state == "succeeded"
    assert recover_general_billing(recovery_engine) == 0


def test_recovery_skips_active_owner_and_has_one_expired_winner(
    recovery_engine,
):
    active = _prepared(recovery_engine, "active")
    assert recover_general_billing(recovery_engine) == 0
    assert active.execution_repository.get(
        active.session.execution_id,
    ).state == ("running")

    expired = _prepared(recovery_engine, "concurrent")
    _expire(recovery_engine, expired.session.execution_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _value: recover_general_billing(recovery_engine),
                range(2),
            ),
        )
    assert sorted(results) == [0, 1]
