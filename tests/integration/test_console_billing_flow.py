# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from qwenpaw.app.billing.context import BillingSource
from qwenpaw.app.billing.entrypoint import prepare_user_billing_execution
from qwenpaw.app.billing.pricing import (
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
)
from qwenpaw.app.billing.supplier_reference_sidecar import (
    stash_supplier_reference,
)
from qwenpaw.app.billing.usage import InsufficientUsageCreditsError
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings
from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper


class _Response:
    def __init__(self) -> None:
        self.usage = SimpleNamespace(input_tokens=10, output_tokens=20)


class _Provider:
    model_name = "model"
    stream = False
    billing_provider_kind = "openai"

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, **_kwargs):
        self.calls += 1
        response = _Response()
        stash_supplier_reference(response, "response-1", "provider_response")
        return response


@pytest.fixture
def console_billing_engine(tmp_path, monkeypatch):
    engine = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "console-billing.db")},
        ),
    )
    create_all(engine)
    PriceCatalogService(PriceCatalogRepository(engine)).publish(
        PriceCatalogDraft(
            version="console-v1",
            effective_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            rules=(
                PriceRule(
                    id="console-rule",
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


@pytest.mark.asyncio
async def test_zero_credit_console_call_stops_before_provider(
    console_billing_engine,
):
    prepared = prepare_user_billing_execution(
        "user-1",
        BillingSource(type="client", id="chat-1"),
        "message-1",
        {"message_sha256": "safe"},
    )
    provider = _Provider()
    wrapper = TokenRecordingModelWrapper(
        "provider",
        provider,
        meter=prepared.meter,
    )

    with prepared.activate():
        with pytest.raises(InsufficientUsageCreditsError):
            await wrapper(messages=[], max_tokens=100)

    assert provider.calls == 0
    assert prepared.usage_service.list_items(prepared.session.usage_order_id) == []


@pytest.mark.asyncio
async def test_funded_mobile_call_charges_once(console_billing_engine):
    prepared = prepare_user_billing_execution(
        "user-1",
        BillingSource(type="mobile", id="chat-1"),
        "message-2",
        {"message_sha256": "safe-2"},
    )
    repository = BillingRepository(console_billing_engine)
    repository.grant(
        prepared.session.wallet_id,
        credits=10,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="fund-mobile",
    )
    provider = _Provider()
    wrapper = TokenRecordingModelWrapper(
        "provider",
        provider,
        meter=prepared.meter,
    )

    with prepared.activate():
        await wrapper(messages=[], max_tokens=100)
    assert prepared.finalize_completed()

    items = prepared.usage_service.list_items(prepared.session.usage_order_id)
    assert provider.calls == 1
    assert len(items) == 1
    assert items[0]["status"] == "captured"
    assert repository.balance(prepared.session.wallet_id).available == 8
