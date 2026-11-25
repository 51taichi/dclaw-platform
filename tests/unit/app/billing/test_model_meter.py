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
from qwenpaw.app.billing.execution import OpenApiBillingExecutionContext
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
                    capability="chat",
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
    fence = open_api.claim_invocation_execution(
        session.invocation_id,
        "model-meter-test",
        lease_seconds=300,
    )
    assert fence is not None
    _TEST_FENCES[session.invocation_id] = fence
    try:
        yield UsageService(repository, pricing), session
    finally:
        _TEST_FENCES.pop(session.invocation_id, None)
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


class _ReasoningThenJsonModel(_Model):
    """Simulate DeepSeek needing reasoning budget before final JSON."""

    def __init__(self):
        super().__init__(generate_kwargs={"max_tokens": 8192})

    async def __call__(self, **kwargs):
        self.calls += 1
        self.received_kwargs.append(kwargs)
        response = _Response(
            usage=SimpleNamespace(input_tokens=3, output_tokens=1502),
        )
        response.reasoning_content = "r" * 1500
        response.content = (
            [{"type": "text", "text": '{"answer":"ok"}'}]
            if kwargs["max_tokens"] > 1024
            else []
        )
        return response


class _SequenceModel(_Model):
    """Return one provider result for each retry attempt."""

    def __init__(self, results):
        super().__init__()
        self._results = iter(results)

    async def __call__(self, **kwargs):
        self.calls += 1
        self.received_kwargs.append(kwargs)
        return next(self._results)


class _RawProviderIterator:
    """SDK-like iterator kept distinct from its iterable response shell."""

    def __init__(self, values=(), *, error=None, close_error=None):
        self._values = iter(values)
        self._error = error
        self._raised = False
        self._close_error = close_error
        self.close_calls = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._values)
        except StopIteration as exc:
            if self._error is not None and not self._raised:
                self._raised = True
                raise self._error from exc
            raise StopAsyncIteration from exc

    async def aclose(self):
        self.close_calls += 1
        if self._close_error is not None:
            raise self._close_error


class _RawProviderIterable:
    def __init__(self, iterator, *, close_error=None):
        self.iterator = iterator
        self._close_error = close_error
        self.close_calls = 0

    def __aiter__(self):
        return self.iterator

    async def aclose(self):
        self.close_calls += 1
        if self._close_error is not None:
            raise self._close_error


class _CountingBillingMeter:
    def __init__(self, service):
        from qwenpaw.app.billing.model_meter import BillingModelMeter

        self._inner = BillingModelMeter(service)
        self.response_calls = 0
        self.exception_calls = 0

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def record_response(self, call, response):
        self.response_calls += 1
        return self._inner.record_response(call, response)

    def record_exception(self, call, error, *, supplier_contacted=True):
        self.exception_calls += 1
        return self._inner.record_exception(
            call,
            error,
            supplier_contacted=supplier_contacted,
        )


def _retry_wrapper(provider, *, meter, retries=0):
    from qwenpaw.providers.retry_chat_model import (
        RateLimitConfig,
        RetryChatModel,
        RetryConfig,
    )

    return RetryChatModel(
        TokenRecordingModelWrapper("provider", provider, meter=meter),
        retry_config=RetryConfig(
            enabled=retries > 0,
            max_retries=max(1, retries),
            backoff_base=0.1,
            backoff_cap=0.5,
        ),
        rate_limit_config=RateLimitConfig(max_concurrent=1, max_qpm=0),
    )


def _reset_test_rate_limiter():
    from qwenpaw.providers.rate_limiter import reset_rate_limiter

    reset_rate_limiter()


async def _test_rate_limiter_in_flight():
    from qwenpaw.providers.rate_limiter import get_rate_limiter

    limiter = await get_rate_limiter()
    return limiter.stats()["current_in_flight"]


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


_TEST_FENCES = {}


def _scope(session):
    return set_current_billing_context(
        OpenApiBillingExecutionContext(
            session=session,
            fence=_TEST_FENCES[session.invocation_id],
        ),
    )


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


def _open_api_request_meter(usage_service, *, platform_cap=8192):
    from qwenpaw.app.open_api.runtime import (
        OpenApiBillingRuntime,
        _RequestBillingMeter,
    )

    runtime = OpenApiBillingRuntime(
        repository=usage_service.repository,
        pricing=usage_service.pricing,
        coordinator=SimpleNamespace(),
        usage_service=usage_service,
        open_api_repository=SimpleNamespace(),
        mode="enforced",
        budget_credits=100_000,
        platform_max_output_tokens=platform_cap,
    )
    execution = SimpleNamespace(
        renew_lease=lambda: None,
        note_first_reservation=lambda: None,
        note_insufficient=lambda _exc: None,
    )
    return _RequestBillingMeter(runtime, execution)


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
    reservation = json.loads(stored["usage_snapshot_json"])["reservation"]
    assert "tier" not in reservation["parameters"]
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
async def test_zero_balance_stops_before_provider_execution(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service
    service.repository.hold(
        session.wallet_id,
        credits=20,
        business_key="exhaust-wallet",
        idempotency_key="exhaust-wallet:hold",
    )
    service.repository.capture(
        session.wallet_id,
        credits=20,
        business_key="exhaust-wallet",
        idempotency_key="exhaust-wallet:capture",
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
    assert service.repository.balance(session.wallet_id).held == 0
    evidence = json.loads(
        _stored_item(service, session.usage_order_id)["supplier_evidence_json"],
    )
    assert evidence["settlement_error_type"] == "OSError"
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
    assert service.repository.balance(session.wallet_id).held == 0


@pytest.mark.asyncio
async def test_tools_and_structured_schema_are_included_in_preauthorization(
    usage_service,
):
    """Provider-counted prompt metadata must not exceed the maximum quote."""
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    class _StructuredReply:
        @staticmethod
        def model_json_schema():
            return {
                "type": "object",
                "properties": {
                    "answer": {"type": "string", "description": "回答" * 80},
                },
                "required": ["answer"],
            }

    service, session = usage_service
    model = _Model(
        _Response(
            usage=SimpleNamespace(input_tokens=1200, output_tokens=2),
        ),
    )
    wrapper = TokenRecordingModelWrapper(
        "provider",
        model,
        meter=BillingModelMeter(service),
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "x" * 1200,
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
    token = _scope(session)
    try:
        await wrapper(
            messages=[],
            tools=tools,
            structured_model=_StructuredReply,
            max_tokens=1000,
        )
    finally:
        reset_current_billing_context(token)

    stored = _stored_item(service, session.usage_order_id)
    reservation = json.loads(stored["usage_snapshot_json"])["reservation"]
    assert reservation["input_tokens"] > len(json.dumps(tools))
    assert stored["status"] == "captured"
    assert stored["quoted_credits"] >= stored["charged_credits"]


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
        is_last=True,
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
async def test_retry_outer_unstarted_close_finalizes_billing_and_slot_once(
    usage_service,
):
    import asyncio

    from qwenpaw.app.billing.model_meter import BillingModelMeter
    from qwenpaw.providers.rate_limiter import (
        get_rate_limiter,
        reset_rate_limiter,
    )
    from qwenpaw.providers.retry_chat_model import (
        RateLimitConfig,
        RetryChatModel,
        RetryConfig,
    )

    class _ProviderStream:
        def __init__(self):
            self.close_calls = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

        async def aclose(self):
            self.close_calls += 1

    class _CountingMeter(BillingModelMeter):
        def __init__(self, service):
            super().__init__(service)
            self.exception_calls = 0

        def record_exception(self, call, error, *, supplier_contacted=True):
            self.exception_calls += 1
            return super().record_exception(
                call,
                error,
                supplier_contacted=supplier_contacted,
            )

    service, session = usage_service
    provider_stream = _ProviderStream()
    provider = _Model(provider_stream)
    meter = _CountingMeter(service)
    wrapper = RetryChatModel(
        TokenRecordingModelWrapper("provider", provider, meter=meter),
        retry_config=RetryConfig(enabled=False),
        rate_limit_config=RateLimitConfig(max_concurrent=1, max_qpm=0),
    )
    reset_rate_limiter()
    token = _scope(session)
    try:
        result = await wrapper(messages=[], max_tokens=1000)
        await result.aclose()

        limiter = await get_rate_limiter()
        assert provider_stream.close_calls == 1
        assert meter.exception_calls == 1
        assert limiter.stats()["current_in_flight"] == 0
        items = service.list_items(session.usage_order_id)
        assert len(items) == 1
        assert items[0]["status"] == "reconciling"

        provider.result = _Response(
            usage=SimpleNamespace(input_tokens=3, output_tokens=2),
        )
        await asyncio.wait_for(
            wrapper(messages=[], max_tokens=1000),
            timeout=0.2,
        )
        assert limiter.stats()["current_in_flight"] == 0
    finally:
        reset_current_billing_context(token)
        reset_rate_limiter()


@pytest.mark.asyncio
async def test_retry_metered_normal_exhaustion_closes_raw_owners_once(
    usage_service,
):
    service, session = usage_service
    raw_iterator = _RawProviderIterator(
        [_Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2))],
    )
    raw_iterable = _RawProviderIterable(raw_iterator)
    meter = _CountingBillingMeter(service)
    wrapper = _retry_wrapper(_Model(raw_iterable), meter=meter)
    _reset_test_rate_limiter()
    token = _scope(session)
    try:
        result = await wrapper(messages=[], max_tokens=1000)
        assert len([chunk async for chunk in result]) == 1
        await result.aclose()
        await result.aclose()

        assert raw_iterator.close_calls == 1
        assert raw_iterable.close_calls == 1
        assert meter.response_calls == 1
        assert meter.exception_calls == 0
        assert await _test_rate_limiter_in_flight() == 0
    finally:
        reset_current_billing_context(token)
        _reset_test_rate_limiter()


@pytest.mark.asyncio
async def test_retry_metered_iterator_error_preserves_business_error(
    usage_service,
):
    service, session = usage_service
    business_error = ValueError("provider iterator failed")
    raw_iterator = _RawProviderIterator(
        error=business_error,
        close_error=RuntimeError("iterator close failed"),
    )
    raw_iterable = _RawProviderIterable(
        raw_iterator,
        close_error=RuntimeError("iterable close failed"),
    )
    meter = _CountingBillingMeter(service)
    wrapper = _retry_wrapper(_Model(raw_iterable), meter=meter)
    _reset_test_rate_limiter()
    token = _scope(session)
    try:
        result = await wrapper(messages=[], max_tokens=1000)
        with pytest.raises(ValueError) as raised:
            await result.__anext__()
        await result.aclose()

        assert raised.value is business_error
        assert raw_iterator.close_calls == 1
        assert raw_iterable.close_calls == 1
        assert meter.response_calls == 0
        assert meter.exception_calls == 1
        assert await _test_rate_limiter_in_flight() == 0
    finally:
        reset_current_billing_context(token)
        _reset_test_rate_limiter()


@pytest.mark.asyncio
async def test_retry_metered_transient_failure_closes_both_raw_attempts(
    usage_service,
    monkeypatch,
):
    import asyncio

    class _TransientStreamError(RuntimeError):
        status_code = 500

    service, session = usage_service
    transient_error = _TransientStreamError("retry this stream")
    first_iterator = _RawProviderIterator(
        error=transient_error,
        close_error=RuntimeError("first iterator close failed"),
    )
    first_iterable = _RawProviderIterable(first_iterator)
    second_iterator = _RawProviderIterator(
        [_Response(usage=SimpleNamespace(input_tokens=4, output_tokens=1))],
    )
    second_iterable = _RawProviderIterable(second_iterator)
    provider = _SequenceModel([first_iterable, second_iterable])
    meter = _CountingBillingMeter(service)
    wrapper = _retry_wrapper(provider, meter=meter, retries=1)

    async def _no_sleep(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    _reset_test_rate_limiter()
    token = _scope(session)
    try:
        result = await wrapper(messages=[], max_tokens=1000)
        assert len([chunk async for chunk in result]) == 1
        await result.aclose()

        assert provider.calls == 2
        assert first_iterator.close_calls == 1
        assert first_iterable.close_calls == 1
        assert second_iterator.close_calls == 1
        assert second_iterable.close_calls == 1
        assert meter.response_calls == 1
        assert meter.exception_calls == 1
        assert await _test_rate_limiter_in_flight() == 0
    finally:
        reset_current_billing_context(token)
        _reset_test_rate_limiter()


@pytest.mark.asyncio
async def test_retry_metered_started_cancellation_closes_raw_owners_once(
    usage_service,
):
    import asyncio

    entered = asyncio.Event()

    class _BlockingRawProviderIterator(_RawProviderIterator):
        async def __anext__(self):
            entered.set()
            await asyncio.Event().wait()

    service, session = usage_service
    raw_iterator = _BlockingRawProviderIterator(
        close_error=RuntimeError("iterator close failed"),
    )
    raw_iterable = _RawProviderIterable(
        raw_iterator,
        close_error=RuntimeError("iterable close failed"),
    )
    meter = _CountingBillingMeter(service)
    wrapper = _retry_wrapper(_Model(raw_iterable), meter=meter)
    _reset_test_rate_limiter()
    token = _scope(session)
    try:
        result = await wrapper(messages=[], max_tokens=1000)
        task = asyncio.create_task(result.__anext__())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await result.aclose()

        assert raw_iterator.close_calls == 1
        assert raw_iterable.close_calls == 1
        assert meter.response_calls == 0
        assert meter.exception_calls == 1
        assert await _test_rate_limiter_in_flight() == 0
    finally:
        reset_current_billing_context(token)
        _reset_test_rate_limiter()


@pytest.mark.asyncio
async def test_retry_metered_unstarted_close_closes_distinct_raw_owners_once(
    usage_service,
):
    service, session = usage_service
    raw_iterator = _RawProviderIterator(
        [_Response(usage=SimpleNamespace(input_tokens=3, output_tokens=2))],
        close_error=RuntimeError("iterator close failed"),
    )
    raw_iterable = _RawProviderIterable(raw_iterator)
    meter = _CountingBillingMeter(service)
    wrapper = _retry_wrapper(_Model(raw_iterable), meter=meter)
    _reset_test_rate_limiter()
    token = _scope(session)
    try:
        result = await wrapper(messages=[], max_tokens=1000)
        await result.aclose()
        await result.aclose()

        assert raw_iterator.close_calls == 1
        assert raw_iterable.close_calls == 1
        assert meter.response_calls == 0
        assert meter.exception_calls == 1
        assert await _test_rate_limiter_in_flight() == 0
    finally:
        reset_current_billing_context(token)
        _reset_test_rate_limiter()


@pytest.mark.asyncio
async def test_retry_unmetered_normal_exhaustion_closes_raw_owners_once():
    raw_iterator = _RawProviderIterator([_Response()])
    raw_iterable = _RawProviderIterable(raw_iterator)
    wrapper = _retry_wrapper(_Model(raw_iterable), meter=None)
    _reset_test_rate_limiter()
    try:
        result = await wrapper(messages=[])
        assert len([chunk async for chunk in result]) == 1
        await result.aclose()
        await result.aclose()

        assert raw_iterator.close_calls == 1
        assert raw_iterable.close_calls == 1
        assert await _test_rate_limiter_in_flight() == 0
    finally:
        _reset_test_rate_limiter()


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
                invocation_id=session.invocation_id,
                execution_fence=call.execution_fence,
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
                    invocation_id=session.invocation_id,
                    execution_fence=call.execution_fence,
                ),
            )
    finally:
        reset_current_billing_context(token)


def test_model_meter_persists_authoritative_provider_pricing_region(
    usage_service,
):
    from qwenpaw.app.billing.model_meter import BillingModelMeter

    service, session = usage_service
    meter = BillingModelMeter(
        service,
        pricing_region_resolver=lambda provider_id: (
            "cn-beijing" if provider_id == "provider" else None
        ),
    )
    token = _scope(session)
    try:
        call = meter.before_call(
            provider_id="provider",
            model_key="meter-model",
            messages=[],
        )
        assert call is not None
    finally:
        reset_current_billing_context(token)

    stored = _stored_item(service, session.usage_order_id)
    reservation = json.loads(stored["usage_snapshot_json"])["reservation"]
    assert stored["capability"] == "chat"
    assert reservation["parameters"] == {"pricing_region": "cn-beijing"}


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
async def test_open_api_8192_cap_reaches_provider_and_billing_reservation(
    usage_service,
):
    service, session = usage_service
    model = _ReasoningThenJsonModel()
    wrapper = TokenRecordingModelWrapper(
        "provider",
        model,
        meter=_open_api_request_meter(service),
    )
    token = _scope(session)
    try:
        response = await wrapper(messages=[], max_tokens=8192)
    finally:
        reset_current_billing_context(token)

    reservation = json.loads(
        _stored_item(service, session.usage_order_id)["usage_snapshot_json"],
    )["reservation"]
    assert reservation["max_output_tokens"] == 8192
    assert model.received_kwargs[0]["max_tokens"] == 8192
    assert len(response.reasoning_content) > 1024
    assert response.content == [
        {"type": "text", "text": '{"answer":"ok"}'},
    ]


@pytest.mark.asyncio
async def test_open_api_positive_balance_ignores_estimated_budget(
    usage_service,
):
    service, session = usage_service
    with service.repository.engine.begin() as conn:
        conn.execute(
            update(billing_usage_orders)
            .where(billing_usage_orders.c.id == session.usage_order_id)
            .values(budget_credits=1),
        )
    model = _ReasoningThenJsonModel()
    wrapper = TokenRecordingModelWrapper(
        "provider",
        model,
        meter=_open_api_request_meter(service),
    )
    token = _scope(session)
    try:
        await wrapper(messages=[], max_tokens=8192)
    finally:
        reset_current_billing_context(token)

    assert model.calls == 1
    assert len(service.list_items(session.usage_order_id)) == 1


def test_open_api_output_cap_is_configurable_and_clamps_fallback(
    usage_service,
    monkeypatch,
):
    from qwenpaw.app.open_api import runtime as runtime_module

    service, _session = usage_service
    monkeypatch.setenv("DCLAW_OPEN_API_DEFAULT_OUTPUT_TOKENS", "8192")
    monkeypatch.setenv("DCLAW_OPEN_API_MAX_OUTPUT_TOKENS", "4096")
    monkeypatch.setattr(
        runtime_module,
        "get_app_engine",
        lambda: service.repository.engine,
    )

    runtime = runtime_module.create_open_api_billing_runtime()

    assert runtime.platform_max_output_tokens == 4096
    assert runtime.default_max_output_tokens == 4096


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
