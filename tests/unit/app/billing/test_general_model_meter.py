# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from qwenpaw.app.billing.context import (
    BillingSource,
    billing_context,
    billing_required,
    system_billing_exemption,
)
from qwenpaw.app.billing.coordinator import BillingCommand, BillingCoordinator
from qwenpaw.app.billing.model_meter import BillingModelMeter
from qwenpaw.app.billing.model_meter import MissingBillingContextError
from qwenpaw.app.billing.supplier_reference_sidecar import (
    stash_supplier_reference,
)
from qwenpaw.app.billing.pricing import (
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
)
from qwenpaw.app.billing.usage import (
    BillingExecutionFencedError,
    InsufficientUsageCreditsError,
    UsageService,
)
from qwenpaw.token_usage.model_wrapper import (
    TokenRecordingModelWrapper,
    UnsupportedBillingProviderError,
)
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_execution_repo import (
    BillingExecutionRepository,
)
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.schema import billing_ledger_entries, create_all
from qwenpaw.app.storage.settings import get_storage_settings


class _ProviderResponse:
    def __init__(self) -> None:
        self.usage = SimpleNamespace(input_tokens=10, output_tokens=20)


class _UnknownProviderModel:
    model_name = "model"
    stream = False
    billing_provider_kind = None

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, **_kwargs):
        self.calls += 1
        return _ProviderResponse()


@pytest.fixture
def general_meter(tmp_path):
    engine = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "general-meter.db")},
        ),
    )
    create_all(engine)
    wallet_repo = BillingRepository(engine)
    pricing = PriceCatalogService(PriceCatalogRepository(engine))
    pricing.publish(
        PriceCatalogDraft(
            version="general-meter-v1",
            effective_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            rules=(
                PriceRule(
                    id="general-meter-rule",
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
    session = BillingCoordinator(wallet_repo, pricing).begin_execution(
        BillingCommand(
            payer_user_id="user-1",
            source=BillingSource(type="client", id="chat-1"),
            request_key="message-1",
            payload={"message_sha256": "safe-fingerprint"},
        ),
    )
    execution_repo = BillingExecutionRepository(engine)
    fence = execution_repo.claim(
        session.execution_id,
        "worker-1",
        lease_seconds=300,
    )
    assert fence is not None
    try:
        yield (
            BillingModelMeter(
                UsageService(wallet_repo, pricing, mode="enforced"),
                default_max_output_tokens=100,
            ),
            wallet_repo,
            execution_repo,
            session,
            fence,
        )
    finally:
        engine.dispose()


def test_general_context_reserves_before_provider_contact(general_meter):
    meter, wallet_repo, _execution_repo, session, fence = general_meter
    wallet_repo.grant(
        session.wallet_id,
        credits=10,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="fund-general-meter",
    )

    with billing_context(session, fence, meter):
        call = meter.before_call(
            provider_id="provider",
            model_key="model",
            messages=[{"role": "user", "content": "hello"}],
            item_key="model-call-1",
        )

    assert call is not None
    items = meter.usage_service.list_items(session.usage_order_id)
    assert len(items) == 1
    assert items[0]["item_key"] == "model-call-1"
    assert items[0]["status"] == "held"
    with wallet_repo.engine.connect() as conn:
        ledger = conn.execute(
            select(billing_ledger_entries).where(
                billing_ledger_entries.c.event_type == "usage_hold",
            ),
        ).mappings().one()
    assert str(ledger["idempotency_key"]).startswith("billing:")
    assert json.loads(ledger["metadata_json"])["source_type"] == "client"


def test_general_context_zero_balance_fails_without_usage_item(general_meter):
    meter, _wallet_repo, _execution_repo, session, fence = general_meter

    with billing_context(session, fence, meter):
        with pytest.raises(InsufficientUsageCreditsError):
            meter.before_call(
                provider_id="provider",
                model_key="model",
                messages=[{"role": "user", "content": "hello"}],
                item_key="model-call-1",
            )

    assert meter.usage_service.list_items(session.usage_order_id) == []


def test_general_context_rejects_stale_execution_fence(general_meter):
    meter, wallet_repo, execution_repo, session, old_fence = general_meter
    wallet_repo.grant(
        session.wallet_id,
        credits=10,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="fund-stale-meter",
    )
    assert execution_repo.finalize(
        session.execution_id,
        old_fence,
        state="failed",
        error_code="OWNER_REPLACED",
    )

    with billing_context(session, old_fence, meter):
        with pytest.raises(BillingExecutionFencedError):
            meter.before_call(
                provider_id="provider",
                model_key="model",
                messages=[{"role": "user", "content": "hello"}],
                item_key="model-call-1",
            )


def test_general_context_captures_verified_usage_once(general_meter):
    meter, wallet_repo, _execution_repo, session, fence = general_meter
    wallet_repo.grant(
        session.wallet_id,
        credits=10,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="fund-general-capture",
    )
    response = _ProviderResponse()
    stash_supplier_reference(
        response,
        "supplier-response-1",
        "provider_response",
    )

    with billing_context(session, fence, meter):
        call = meter.before_call(
            provider_id="provider",
            model_key="model",
            messages=[{"role": "user", "content": "hello"}],
            item_key="model-call-1",
        )
        assert call is not None
        meter.mark_provider_call_started(call)
        first = meter.record_response(call, response)
        replay = meter.record_response(call, response)

    assert first is not None
    assert first.status == "captured"
    assert replay is None
    balance = wallet_repo.balance(session.wallet_id)
    assert balance.held == 0
    assert balance.available == 8


@pytest.mark.asyncio
async def test_general_enforced_context_rejects_unknown_provider_before_contact(
    general_meter,
):
    meter, wallet_repo, _execution_repo, session, fence = general_meter
    wallet_repo.grant(
        session.wallet_id,
        credits=10,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="fund-general-unknown-provider",
    )
    model = _UnknownProviderModel()
    wrapper = TokenRecordingModelWrapper("provider", model, meter=meter)

    with billing_context(session, fence, meter):
        with pytest.raises(
            UnsupportedBillingProviderError,
            match="cannot enforce billing",
        ):
            await wrapper(messages=[], max_tokens=10)

    assert model.calls == 0
    assert meter.usage_service.list_items(session.usage_order_id) == []


@pytest.mark.asyncio
async def test_user_originated_call_without_billing_context_fails_closed(
    general_meter,
):
    meter, _wallet_repo, _execution_repo, _session, _fence = general_meter
    model = _UnknownProviderModel()
    model.billing_provider_kind = "openai"
    wrapper = TokenRecordingModelWrapper("provider", model, meter=meter)

    with billing_required():
        with pytest.raises(MissingBillingContextError):
            await wrapper(messages=[], max_tokens=10)

    assert model.calls == 0


@pytest.mark.asyncio
async def test_system_exemption_is_audited_before_model_call(general_meter):
    meter, _wallet_repo, execution_repo, _session, _fence = general_meter
    model = _UnknownProviderModel()
    wrapper = TokenRecordingModelWrapper("provider", model, meter=meter)

    with billing_required():
        with system_billing_exemption(
            execution_repo,
            actor="system:catalog-probe",
            reason="model_catalog_validation",
        ) as exemption:
            await wrapper(messages=[], max_tokens=10)

    record = execution_repo.get(exemption.execution_id)
    assert record is not None
    assert record.source_type == "system_exemption"
    assert record.state == "succeeded"
    assert record.exemption_actor == "system:catalog-probe"
    assert record.exemption_reason == "model_catalog_validation"
    assert record.usage_order_id is None
    assert model.calls == 1
