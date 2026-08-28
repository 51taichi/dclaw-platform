# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
"""Financial meter coverage at the model-provider boundary."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select, update
from agentscope.model import ChatResponse
from agentscope.model._model_usage import ChatUsage

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
    SettleModelCall,
    UsageOrderConflictError,
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
    def __init__(
        self,
        *,
        usage=None,
        response_id="synthetic-response-id",
        supplier_billing_reference="supplier-response",
    ):
        from qwenpaw.app.billing.supplier_reference_sidecar import (
            stash_supplier_reference,
        )

        self.usage = usage
        self.id = response_id
        stash_supplier_reference(
            self,
            supplier_billing_reference,
            "provider_response",
        )
        self.metadata = {"api_key": "must-not-be-recorded", "content": "nope"}


class _Model:
    billing_provider_kind = "openai"

    def __init__(self, result=None, error=None, generate_kwargs=None):
        self.model_name = "meter-model"
        self.stream = True
        self.result = result
        self.error = error
        self.generate_kwargs = generate_kwargs or {}
        self.calls = 0
        self.received_kwargs = []

    async def __call__(self, **kwargs):
        self.calls += 1
        self.received_kwargs.append(kwargs)
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
        evidence = dict(command.evidence)
        if evidence["response_class"] == "provider_call_started":
            return self.service.settle_model_call(command)
        self.settle_attempts += 1
        if self.settle_attempts == 1:
            raise OSError("ledger unavailable")
        return self.service.settle_model_call(command)


class _AlwaysFailsSettlement:
    """Model a storage outage for both settlement and reconciliation writes."""

    def __init__(self, service):
        self.service = service
        self.settle_attempts = 0

    def reserve_model_call(self, command):
        return self.service.reserve_model_call(command)

    def settle_model_call(self, command):
        evidence = dict(command.evidence)
        if evidence["response_class"] == "provider_call_started":
            return self.service.settle_model_call(command)
        self.settle_attempts += 1
        raise OSError("ledger unavailable")


class _ProviderError(ValueError):
    def __init__(
        self,
        message,
        *,
        status_code=None,
        phase=None,
        supplier_not_billed=False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.phase = phase
        self.supplier_not_billed = supplier_not_billed


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
        "supplier_reference_source",
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
async def test_generic_provider_validation_after_contact_is_reconciling(
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
    assert item["billability"] == "unknown"
    assert item["status"] == "reconciling"


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
    failing_service = _FailsFirstSettlement(service)
    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(
            _Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2)),
        ),
        meter=BillingModelMeter(failing_service),
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
    assert failing_service.settle_attempts == 2


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


@pytest.mark.asyncio
async def test_concurrent_openapi_calls_allocate_distinct_durable_item_keys(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service
    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(
            _Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2)),
        ),
        meter=BillingModelMeter(service),
    )
    token = _scope(session)
    try:
        await pytest.importorskip("asyncio").gather(
            wrapper(messages=[], max_tokens=1000),
            wrapper(messages=[], max_tokens=1000),
        )
    finally:
        reset_current_billing_context(token)

    items = service.list_items(session.usage_order_id)
    assert len(items) == 2
    assert len({item["item_key"] for item in items}) == 2


@pytest.mark.asyncio
async def test_stream_close_after_partial_output_reconciles_once(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service

    async def stream():
        yield _Response(
            usage=SimpleNamespace(input_tokens=3, output_tokens=1),
        )
        yield _Response(
            usage=SimpleNamespace(input_tokens=3, output_tokens=2),
        )

    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(stream()),
        meter=BillingModelMeter(service),
    )
    token = _scope(session)
    try:
        result = await wrapper(messages=[], max_tokens=1000)
        async for _chunk in result:
            break
        await result.aclose()
    finally:
        reset_current_billing_context(token)

    item = service.list_items(session.usage_order_id)[0]
    assert item["billability"] == "unknown"
    assert item["status"] == "reconciling"


@pytest.mark.asyncio
async def test_provider_task_cancellation_reconciles_and_propagates(
    usage_service,
):
    import asyncio

    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service
    entered_provider = asyncio.Event()

    class _CancellingModel(_Model):
        async def __call__(self, **kwargs):
            self.calls += 1
            self.received_kwargs.append(kwargs)
            entered_provider.set()
            await asyncio.Event().wait()

    wrapper = TokenRecordingModelWrapper(
        "provider",
        _CancellingModel(),
        meter=BillingModelMeter(service),
    )
    token = _scope(session)
    try:
        task = asyncio.create_task(wrapper(messages=[], max_tokens=1000))
        await entered_provider.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        reset_current_billing_context(token)

    item = service.list_items(session.usage_order_id)[0]
    assert item["billability"] == "unknown"
    assert item["status"] == "reconciling"


@pytest.mark.asyncio
async def test_stream_iterator_exception_reconciles_once_and_propagates(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service

    async def stream():
        yield _Response(
            usage=SimpleNamespace(input_tokens=3, output_tokens=1),
        )
        raise RuntimeError("stream transport failed")

    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(stream()),
        meter=BillingModelMeter(service),
    )
    token = _scope(session)
    try:
        with pytest.raises(RuntimeError, match="stream transport failed"):
            await _consume(await wrapper(messages=[], max_tokens=1000))
    finally:
        reset_current_billing_context(token)

    assert len(service.list_items(session.usage_order_id)) == 1
    item = service.list_items(session.usage_order_id)[0]
    assert item["billability"] == "unknown"
    assert item["status"] == "reconciling"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_billability"),
    [
        (_ProviderError("validation"), "unknown"),
        (_ProviderError("bad request", status_code=400), "unknown"),
        (_ProviderError("limited", status_code=429), "unknown"),
        (_ProviderError("local", phase="pre_contact"), "not_billable"),
        (_ProviderError("declined", supplier_not_billed=True), "not_billable"),
    ],
)
async def test_exception_billability_requires_explicit_non_charge_evidence(
    usage_service,
    error,
    expected_billability,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service
    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(error=error),
        meter=BillingModelMeter(service),
    )
    token = _scope(session)
    try:
        with pytest.raises(_ProviderError):
            await wrapper(messages=[], max_tokens=1000)
    finally:
        reset_current_billing_context(token)

    item = service.list_items(session.usage_order_id)[0]
    assert item["billability"] == expected_billability


@pytest.mark.asyncio
async def test_synthetic_chat_response_id_is_not_supplier_billing_evidence(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service
    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(
            _Response(
                usage=SimpleNamespace(input_tokens=3, output_tokens=2),
                response_id="agentscope-generated-id",
                supplier_billing_reference=None,
            ),
        ),
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
async def test_financial_write_fallback_attempts_reconciliation_once(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import (
        BillingModelMeter,
        BillingSettlementError,
    )

    service, session = usage_service
    failing_service = _AlwaysFailsSettlement(service)
    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(
            _Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2)),
        ),
        meter=BillingModelMeter(failing_service),
    )
    token = _scope(session)
    try:
        with pytest.raises(BillingSettlementError):
            await wrapper(messages=[], max_tokens=1000)
    finally:
        reset_current_billing_context(token)

    assert failing_service.settle_attempts == 2
    item = service.list_items(session.usage_order_id)[0]
    assert item["status"] == "reconciling"
    assert service.repository.balance(session.wallet_id).held > 0


@pytest.mark.asyncio
async def test_cjk_reservation_and_provider_limit_share_the_same_frozen_cap(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service
    model = _Model(
        _Response(usage=SimpleNamespace(input_tokens=6, output_tokens=2)),
        generate_kwargs={"max_tokens": 12},
    )
    wrapper = TokenRecordingModelWrapper(
        "provider",
        model,
        meter=BillingModelMeter(service, default_max_output_tokens=32),
    )
    token = _scope(session)
    try:
        await wrapper(
            messages=[{"role": "user", "content": "你好世界"}],
            max_tokens=100,
        )
    finally:
        reset_current_billing_context(token)

    stored = _stored_item(service, session.usage_order_id)
    reservation = json.loads(stored["usage_snapshot_json"])["reservation"]
    assert reservation["input_tokens"] >= len("你好世界".encode("utf-8"))
    assert reservation["max_output_tokens"] == 12
    assert model.received_kwargs[0]["max_tokens"] == 12


def _agentscope_response(*, response_id="agentscope-generated-id", usage=True):
    return ChatResponse(
        content=[],
        id=response_id,
        usage=(
            ChatUsage(input_tokens=3, output_tokens=2, time=0)
            if usage
            else None
        ),
    )


@pytest.mark.asyncio
async def test_real_agentscope_response_without_billing_fields_is_unknown(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service
    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(_agentscope_response()),
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
async def test_uuid_item_key_is_unique_without_process_global_counter(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service
    wrappers = [
        TokenRecordingModelWrapper(
            "provider",
            _Model(
                _Response(
                    usage=SimpleNamespace(input_tokens=3, output_tokens=2),
                ),
            ),
            meter=BillingModelMeter(service),
        )
        for _ in range(2)
    ]
    token = _scope(session)
    try:
        await pytest.importorskip("asyncio").gather(
            *(wrapper(messages=[], max_tokens=1000) for wrapper in wrappers),
        )
    finally:
        reset_current_billing_context(token)

    keys = [
        item["item_key"] for item in service.list_items(session.usage_order_id)
    ]
    assert len(keys) == len(set(keys)) == 2
    for key in keys:
        assert key.startswith("model:")
        UUID(key.removeprefix("model:"))


@pytest.mark.asyncio
async def test_unstarted_stream_aclose_reconciles_contacted_provider_once(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service

    async def stream():
        yield _Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2))

    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(stream()),
        meter=BillingModelMeter(service),
    )
    token = _scope(session)
    try:
        result = await wrapper(messages=[], max_tokens=1000)
        await result.aclose()
    finally:
        reset_current_billing_context(token)

    items = service.list_items(session.usage_order_id)
    assert len(items) == 1
    assert items[0]["status"] == "reconciling"


@pytest.mark.asyncio
async def test_provider_call_started_marker_is_durable_before_network_call(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service
    observed = []

    class _ObservingModel(_Model):
        async def __call__(self, **kwargs):
            observed.extend(service.list_items(session.usage_order_id))
            return await super().__call__(**kwargs)

    wrapper = TokenRecordingModelWrapper(
        "provider",
        _ObservingModel(
            _Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2)),
        ),
        meter=BillingModelMeter(service),
    )
    token = _scope(session)
    try:
        await wrapper(messages=[], max_tokens=1000)
    finally:
        reset_current_billing_context(token)

    assert observed[0]["status"] == "reconciling"
    stored = _stored_item(service, session.usage_order_id)
    evidence = json.loads(stored["supplier_evidence_json"])
    assert evidence["response_class"] == "success"


@pytest.mark.asyncio
async def test_marker_write_failure_stops_before_network_call(usage_service):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service

    class _MarkerWriteFails:
        def reserve_model_call(self, command):
            return service.reserve_model_call(command)

        def settle_model_call(self, _command):
            raise OSError("marker storage unavailable")

    model = _Model(
        _Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2)),
    )
    wrapper = TokenRecordingModelWrapper(
        "provider",
        model,
        meter=BillingModelMeter(_MarkerWriteFails()),
    )
    token = _scope(session)
    try:
        with pytest.raises(
            RuntimeError,
            match="provider call was not started",
        ):
            await wrapper(messages=[], max_tokens=1000)
    finally:
        reset_current_billing_context(token)

    assert model.calls == 0
    assert service.list_items(session.usage_order_id)[0]["status"] == "held"


@pytest.mark.asyncio
async def test_marker_survives_terminal_storage_outage_as_durable_reconciling(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import (
        BillingModelMeter,
        BillingSettlementError,
    )

    service, session = usage_service

    class _FailsAfterMarker:
        def __init__(self):
            self.attempts = 0

        def reserve_model_call(self, command):
            return service.reserve_model_call(command)

        def settle_model_call(self, command):
            self.attempts += 1
            evidence = dict(command.evidence)
            if evidence["response_class"] == "provider_call_started":
                return service.settle_model_call(command)
            raise OSError("terminal storage unavailable")

    failing_service = _FailsAfterMarker()
    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(
            _Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2)),
        ),
        meter=BillingModelMeter(failing_service),
    )
    token = _scope(session)
    try:
        with pytest.raises(BillingSettlementError):
            await wrapper(messages=[], max_tokens=1000)
    finally:
        reset_current_billing_context(token)

    item = service.list_items(session.usage_order_id)[0]
    assert item["status"] == "reconciling"
    assert failing_service.attempts == 3


def test_only_started_marker_permits_one_unknown_evidence_replacement(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service
    meter = BillingModelMeter(service)
    token = _scope(session)
    try:
        call = meter.before_call(
            provider_id="provider",
            model_key="meter-model",
            messages=[],
        )
        assert call is not None
        meter.mark_provider_call_started(call)
        service.settle_model_call(
            SettleModelCall(
                usage_order_id=session.usage_order_id,
                item_key=call.item_key,
                supplier_reference="",
                billability="unknown",
                evidence={"response_class": "supplier_outcome_unknown"},
                actual_input_tokens=0,
                actual_output_tokens=0,
            ),
        )
        with pytest.raises(UsageOrderConflictError):
            service.settle_model_call(
                SettleModelCall(
                    usage_order_id=session.usage_order_id,
                    item_key=call.item_key,
                    supplier_reference="",
                    billability="unknown",
                    evidence={"response_class": "drifted_unknown"},
                    actual_input_tokens=0,
                    actual_output_tokens=0,
                ),
            )
    finally:
        reset_current_billing_context(token)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_kind", "configured", "expected_kwargs"),
    [
        ("openai", {"max_tokens": 11}, {"max_tokens": 11}),
        ("anthropic", {"max_tokens": 12}, {"max_tokens": 12}),
        ("gemini", {"max_output_tokens": 13}, {"max_output_tokens": 13}),
        (
            "ollama",
            {"options": {"num_predict": 14}},
            {"options": {"num_predict": 14}},
        ),
    ],
)
async def test_known_provider_adapter_freezes_and_passes_its_native_limit(
    usage_service,
    provider_kind,
    configured,
    expected_kwargs,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service
    model = _Model(
        _Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2)),
        generate_kwargs=configured,
    )
    model.billing_provider_kind = provider_kind
    wrapper = TokenRecordingModelWrapper(
        "provider",
        model,
        meter=BillingModelMeter(service, default_max_output_tokens=50),
    )
    token = _scope(session)
    try:
        await wrapper(messages=[], max_tokens=100)
    finally:
        reset_current_billing_context(token)

    reservation = json.loads(
        _stored_item(service, session.usage_order_id)["usage_snapshot_json"],
    )["reservation"]
    expected_cap = next(iter(expected_kwargs.values()))
    if isinstance(expected_cap, dict):
        expected_cap = expected_cap["num_predict"]
    assert reservation["max_output_tokens"] == expected_cap
    for key, value in expected_kwargs.items():
        assert model.received_kwargs[0][key] == value


@pytest.mark.asyncio
async def test_unknown_provider_keeps_platform_cap_without_invalid_limit(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    class _UnknownModel(_Model):
        billing_provider_kind = None

    service, session = usage_service
    model = _UnknownModel(
        _Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2)),
        generate_kwargs={"max_tokens": 2},
    )
    wrapper = TokenRecordingModelWrapper(
        "provider",
        model,
        meter=BillingModelMeter(service, default_max_output_tokens=17),
    )
    token = _scope(session)
    try:
        with pytest.raises(RuntimeError, match="cannot enforce billing"):
            await wrapper(messages=[], max_tokens=100)
    finally:
        reset_current_billing_context(token)

    assert model.calls == 0
    assert service.list_items(session.usage_order_id) == []


def test_openai_adapter_emits_dedicated_reference_from_verified_raw_field():
    from qwenpaw.providers.openai_chat_model_compat import (
        attach_openai_supplier_billing_reference,
    )
    from qwenpaw.app.billing.supplier_reference_sidecar import (
        pop_supplier_reference,
    )

    parsed = _agentscope_response(response_id="synthetic-id")
    attach_openai_supplier_billing_reference(
        parsed,
        SimpleNamespace(id="chatcmpl-verified"),
    )

    assert "supplier_billing_reference" not in dict(parsed)
    assert "supplier_billing_reference_source" not in dict(parsed)
    reference = pop_supplier_reference(parsed)
    assert reference.value == "chatcmpl-verified"
    assert reference.source == "openai.chat.completion.id"
    assert not pop_supplier_reference(parsed).value


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["observe", "off"])
async def test_unknown_provider_does_not_mutate_or_block_non_enforced_calls(
    usage_service,
    mode,
):
    from dataclasses import replace

    from qwenpaw.app.billing.model_meter import BillingModelMeter

    class _UnknownModel(_Model):
        billing_provider_kind = None

    service, session = usage_service
    model = _UnknownModel(
        _Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2)),
    )
    wrapper = TokenRecordingModelWrapper(
        "provider",
        model,
        meter=BillingModelMeter(service, default_max_output_tokens=17),
    )
    token = _scope(replace(session, mode=mode))
    try:
        await wrapper(messages=[], max_tokens=7)
    finally:
        reset_current_billing_context(token)

    assert model.calls == 1
    assert model.received_kwargs[0]["max_tokens"] == 7


@pytest.mark.asyncio
async def test_unknown_provider_non_openapi_call_is_not_mutated(usage_service):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    class _UnknownModel(_Model):
        billing_provider_kind = None

    service, _session = usage_service
    model = _UnknownModel(
        _Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2)),
    )
    wrapper = TokenRecordingModelWrapper(
        "provider",
        model,
        meter=BillingModelMeter(service, default_max_output_tokens=17),
    )

    await wrapper(messages=[], max_tokens=7)

    assert model.calls == 1
    assert model.received_kwargs[0]["max_tokens"] == 7


@pytest.mark.asyncio
async def test_ollama_model_options_cap_is_never_expanded(usage_service):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service
    model = _Model(
        _Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2)),
        generate_kwargs={"options": {"num_predict": 50}},
    )
    model.billing_provider_kind = "ollama"
    model.options = {"num_predict": 4, "temperature": 0.2}
    wrapper = TokenRecordingModelWrapper(
        "provider",
        model,
        meter=BillingModelMeter(service, default_max_output_tokens=1024),
    )
    token = _scope(session)
    try:
        await wrapper(messages=[], options={"num_predict": 40})
    finally:
        reset_current_billing_context(token)

    reservation = json.loads(
        _stored_item(service, session.usage_order_id)["usage_snapshot_json"],
    )["reservation"]
    assert reservation["max_output_tokens"] == 4
    assert model.received_kwargs[0]["options"] == {
        "num_predict": 4,
        "temperature": 0.2,
    }


@pytest.mark.asyncio
async def test_sidecar_is_discarded_before_non_openapi_response_is_returned(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter
    from qwenpaw.app.billing.supplier_reference_sidecar import (
        pop_supplier_reference,
        stash_supplier_reference,
    )

    service, _session = usage_service
    response = _agentscope_response()
    stash_supplier_reference(
        response,
        "private-upstream-id",
        "openai.chat.completion.id",
    )
    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(response),
        meter=BillingModelMeter(service),
    )

    returned = await wrapper(messages=[])

    assert returned is response
    assert "supplier_billing_reference" not in dict(returned)
    assert not pop_supplier_reference(returned).value


@pytest.mark.asyncio
async def test_shared_response_sidecar_does_not_cross_supplier_evidence(
    usage_service,
):
    import asyncio

    from qwenpaw.app.billing.model_meter import BillingModelMeter
    from qwenpaw.app.billing.supplier_reference_sidecar import (
        stash_supplier_reference,
    )

    service, session = usage_service
    response = _agentscope_response()
    stash_supplier_reference(
        response,
        "private-upstream-id",
        "openai.chat.completion.id",
    )
    wrapper = TokenRecordingModelWrapper(
        "provider",
        _Model(response),
        meter=BillingModelMeter(service),
    )
    token = _scope(session)
    try:
        await asyncio.gather(wrapper(messages=[]), wrapper(messages=[]))
    finally:
        reset_current_billing_context(token)

    with service.repository.engine.connect() as conn:
        references = (
            conn.execute(
                select(billing_usage_items.c.supplier_reference).where(
                    billing_usage_items.c.usage_order_id
                    == session.usage_order_id,
                ),
            )
            .scalars()
            .all()
        )
    assert references.count("private-upstream-id") == 1
    assert "supplier_billing_reference" not in dict(response)
