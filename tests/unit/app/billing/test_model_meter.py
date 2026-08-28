# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Financial meter coverage at the model-provider boundary."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from qwenpaw.app.agent_context import (
    reset_current_billing_context,
    set_current_billing_context,
)
from qwenpaw.app.billing.open_api import (
    OpenApiBillingCommand,
    OpenApiBillingCoordinator,
)
from qwenpaw.app.billing.pricing import (
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
)
from qwenpaw.app.billing.usage import (
    InsufficientUsageCreditsError,
    UsageService,
)
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.open_api_repo import SqlAlchemyOpenApiRepository
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.schema import (
    billing_usage_items,
    billing_usage_orders,
    create_all,
)
from qwenpaw.app.storage.settings import get_storage_settings
from qwenpaw.token_usage.model_wrapper import TokenRecordingModelWrapper


@pytest.fixture
def usage_service(tmp_path):
    settings = get_storage_settings(
        {"QWENPAW_SQLITE_PATH": str(tmp_path / "model-meter.db")},
    )
    engine = create_engine_from_settings(settings)
    create_all(engine)
    repository = BillingRepository(engine)
    open_api = SqlAlchemyOpenApiRepository(engine)
    open_api.upsert_publication(
        {
            "id": "publication",
            "public_id": "public-publication",
            "target_type": "agent",
            "target_id": "agent",
            "owner_user_id": "owner",
            "bound_user_id": "wallet-owner",
            "name": "Metered OpenAPI agent",
        },
    )
    open_api.create_external_app(
        {"id": "app", "owner_user_id": "owner", "name": "app"},
    )
    open_api.create_api_key(
        {
            "id": "key",
            "app_id": "app",
            "publication_id": "publication",
            "key_hash": "hash",
            "key_prefix": "qp",
            "key_suffix": "meter",
            "scopes": ["messages:create"],
        },
    )
    pricing = PriceCatalogService(PriceCatalogRepository(engine))
    pricing.publish(
        PriceCatalogDraft(
            version="meter-v1",
            effective_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            rules=(
                PriceRule(
                    id="meter-text",
                    provider_id="provider",
                    model_key="meter-model",
                    capability="text",
                    unit_type="tokens",
                    input_credits_per_1k=1,
                    output_credits_per_1k=1,
                ),
            ),
        ),
    )
    coordinator = OpenApiBillingCoordinator(repository, pricing)
    session = coordinator.begin_invocation(
        OpenApiBillingCommand(
            app_id="app",
            publication_id="publication",
            api_key_id="key",
            target_type="agent",
            target_id="agent",
            external_user_id="caller",
            external_session_id="session",
            payload={"message": "billing test"},
            mode="enforced",
        ),
    )
    repository.grant(
        session.wallet_id,
        credits=20,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="fund-meter-wallet",
    )
    try:
        yield UsageService(repository, pricing), session
    finally:
        engine.dispose()


class _AnalyticsSink:
    def __init__(self, usage_service, usage_order_id):
        self.usage_service = usage_service
        self.usage_order_id = usage_order_id
        self.events = []
        self.financial_at_enqueue = []
        self.reject = False

    def enqueue(self, event):
        if self.reject:
            raise RuntimeError("analytics queue unavailable")
        self.financial_at_enqueue.append(
            self.usage_service.list_items(self.usage_order_id),
        )
        self.events.append(event)


class _Response:
    def __init__(self, *, usage=None, response_id="supplier-response"):
        self.usage = usage
        self.id = response_id
        self.metadata = {"api_key": "must-not-be-recorded", "content": "nope"}


class _Model:
    def __init__(self, result=None, error=None):
        self.model_name = "meter-model"
        self.stream = True
        self.result = result
        self.error = error
        self.calls = 0

    async def __call__(self, **_kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class _FailsFirstSettlement:
    """Inject one synchronous accounting outage after supplier success."""

    def __init__(self, service):
        self.service = service
        self.settle_attempts = 0

    def reserve_model_call(self, command):
        return self.service.reserve_model_call(command)

    def settle_model_call(self, command):
        self.settle_attempts += 1
        if self.settle_attempts == 1:
            raise OSError("ledger unavailable")
        return self.service.settle_model_call(command)


async def _consume(result):
    if hasattr(result, "__aiter__"):
        return [chunk async for chunk in result]
    return result


def _scope(session):
    return set_current_billing_context(session)


def _stored_item(usage_service, usage_order_id):
    with usage_service.repository.engine.connect() as conn:
        return dict(
            conn.execute(
                select(billing_usage_items).where(
                    billing_usage_items.c.usage_order_id == usage_order_id,
                ),
            )
            .mappings()
            .one(),
        )


@pytest.mark.asyncio
async def test_response_is_durable_before_analytics_enqueue(
    usage_service,
    monkeypatch,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter
    import qwenpaw.token_usage.model_wrapper as wrapper_module

    service, session = usage_service
    sink = _AnalyticsSink(service, session.usage_order_id)
    monkeypatch.setattr(
        wrapper_module,
        "get_token_usage_manager",
        lambda: sink,
    )
    model = _Model(
        _Response(usage=SimpleNamespace(input_tokens=12, output_tokens=4)),
    )
    wrapper = TokenRecordingModelWrapper(
        "provider",
        model,
        meter=BillingModelMeter(service),
    )

    token = _scope(session)
    try:
        await _consume(
            await wrapper(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1000,
            ),
        )
    finally:
        reset_current_billing_context(token)

    items = service.list_items(session.usage_order_id)
    stored = _stored_item(service, session.usage_order_id)
    assert len(items) == 1
    assert stored["billability"] == "billable"
    assert stored["supplier_reference"] == "supplier-response"
    assert stored["input_tokens"] == 12
    assert stored["output_tokens"] == 4
    assert sink.events[0].prompt_tokens == 12
    assert sink.events[0].completion_tokens == 4
    evidence = json.loads(stored["supplier_evidence_json"])
    assert set(evidence) == {
        "adapter_version",
        "official_usage",
        "response_class",
        "supplier_reference",
        "timestamp",
    }
    assert "api_key" not in str(evidence)
    assert "content" not in str(evidence)
    assert sink.financial_at_enqueue[0][0]["billability"] == "billable"


@pytest.mark.asyncio
async def test_streaming_response_settles_exactly_once(
    usage_service,
    monkeypatch,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter
    import qwenpaw.token_usage.model_wrapper as wrapper_module

    service, session = usage_service
    sink = _AnalyticsSink(service, session.usage_order_id)
    monkeypatch.setattr(
        wrapper_module,
        "get_token_usage_manager",
        lambda: sink,
    )

    async def stream():
        yield _Response(
            usage=SimpleNamespace(input_tokens=8, output_tokens=1),
            response_id="stream-1",
        )
        yield _Response(
            usage=SimpleNamespace(input_tokens=8, output_tokens=3),
            response_id="stream-1",
        )

    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(stream()),
        meter=BillingModelMeter(service),
    )
    token = _scope(session)
    try:
        chunks = await _consume(
            await wrapper(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1000,
            ),
        )
    finally:
        reset_current_billing_context(token)

    assert len(chunks) == 2
    items = service.list_items(session.usage_order_id)
    assert len(items) == 1
    stored = _stored_item(service, session.usage_order_id)
    assert stored["billability"] == "billable"
    assert stored["output_tokens"] == 3
    assert len(sink.events) == 1


@pytest.mark.asyncio
async def test_timeout_retains_reserved_item_for_reconciliation(usage_service):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service
    model = _Model(error=TimeoutError())
    wrapper = TokenRecordingModelWrapper(
        "provider",
        model,
        meter=BillingModelMeter(service),
    )
    token = _scope(session)
    try:
        with pytest.raises(TimeoutError):
            await wrapper(messages=[], max_tokens=1000)
    finally:
        reset_current_billing_context(token)

    item = service.list_items(session.usage_order_id)[0]
    assert item["billability"] == "unknown"
    assert item["status"] == "reconciling"


@pytest.mark.asyncio
async def test_local_provider_preflight_rejection_releases_as_not_billable(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service
    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(error=ValueError("invalid provider request")),
        meter=BillingModelMeter(service),
    )
    token = _scope(session)
    try:
        with pytest.raises(ValueError, match="invalid provider request"):
            await wrapper(messages=[], max_tokens=1000)
    finally:
        reset_current_billing_context(token)

    item = service.list_items(session.usage_order_id)[0]
    assert item["billability"] == "not_billable"
    assert item["status"] == "released"


@pytest.mark.asyncio
async def test_insufficient_reservation_stops_before_provider_execution(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service
    with service.repository.engine.begin() as conn:
        conn.execute(
            update(billing_usage_orders)
            .where(billing_usage_orders.c.id == session.usage_order_id)
            .values(budget_credits=1),
        )
    model = _Model(
        _Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2)),
    )
    wrapper = TokenRecordingModelWrapper(
        "provider",
        model,
        meter=BillingModelMeter(service),
    )
    token = _scope(session)
    try:
        with pytest.raises(InsufficientUsageCreditsError):
            await wrapper(messages=[], max_tokens=1000)
    finally:
        reset_current_billing_context(token)

    assert model.calls == 0
    assert service.list_items(session.usage_order_id) == []


@pytest.mark.asyncio
async def test_success_without_official_usage_is_reconciling(usage_service):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service
    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(_Response(usage=None)),
        meter=BillingModelMeter(service),
    )
    token = _scope(session)
    try:
        await wrapper(messages=[], max_tokens=1000)
    finally:
        reset_current_billing_context(token)

    item = service.list_items(session.usage_order_id)[0]
    assert item["billability"] == "unknown"
    assert item["status"] == "reconciling"


@pytest.mark.asyncio
async def test_analytics_queue_loss_does_not_lose_durable_billing(
    usage_service,
    monkeypatch,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter
    import qwenpaw.token_usage.model_wrapper as wrapper_module

    service, session = usage_service
    sink = _AnalyticsSink(service, session.usage_order_id)
    sink.reject = True
    monkeypatch.setattr(
        wrapper_module,
        "get_token_usage_manager",
        lambda: sink,
    )
    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(
            _Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2)),
        ),
        meter=BillingModelMeter(service),
    )
    token = _scope(session)
    try:
        await wrapper(messages=[], max_tokens=1000)
    finally:
        reset_current_billing_context(token)

    item = service.list_items(session.usage_order_id)[0]
    assert item["billability"] == "billable"
    assert item["status"] == "captured"


@pytest.mark.asyncio
async def test_contacted_supplier_write_failure_stays_reconciling(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import (
        BillingModelMeter,
        BillingSettlementError,
    )

    service, session = usage_service
    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(
            _Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2)),
        ),
        meter=BillingModelMeter(_FailsFirstSettlement(service)),
    )
    token = _scope(session)
    try:
        with pytest.raises(
            BillingSettlementError,
            match="needs reconciliation",
        ):
            await wrapper(messages=[], max_tokens=1000)
    finally:
        reset_current_billing_context(token)

    item = service.list_items(session.usage_order_id)[0]
    assert item["billability"] == "unknown"
    assert item["status"] == "reconciling"
    assert service.repository.balance(session.wallet_id).held > 0


@pytest.mark.asyncio
async def test_non_openapi_call_stays_analytics_only(
    usage_service,
    monkeypatch,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter
    import qwenpaw.token_usage.model_wrapper as wrapper_module

    service, session = usage_service
    sink = _AnalyticsSink(service, session.usage_order_id)
    monkeypatch.setattr(
        wrapper_module,
        "get_token_usage_manager",
        lambda: sink,
    )
    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(
            _Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2)),
        ),
        meter=BillingModelMeter(service),
    )

    await wrapper(messages=[], max_tokens=1000)

    assert service.list_items(session.usage_order_id) == []
    assert len(sink.events) == 1
