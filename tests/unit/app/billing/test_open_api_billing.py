# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Lock

import pytest
from sqlalchemy import func, insert, select, update

from qwenpaw.app.billing.open_api import (
    IdempotencyConflictError,
    OpenApiBillingCommand,
    OpenApiBillingCoordinator,
)
from qwenpaw.app.billing.pricing import (
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
    QuoteRequest,
)
from qwenpaw.app.billing.models import LedgerTransaction
from qwenpaw.app.billing.usage import (
    InsufficientUsageCreditsError,
    ReserveModelCall,
    SettleModelCall,
    UsageOrderConflictError,
    UsageService,
)
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.open_api_repo import SqlAlchemyOpenApiRepository
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.schema import (
    billing_credit_lots,
    billing_ledger_entries,
    billing_usage_items,
    billing_usage_orders,
    billing_wallets,
    create_all,
    open_api_invocations,
    open_api_publications,
    users,
)
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def engine(tmp_path):
    settings = get_storage_settings(
        {"QWENPAW_SQLITE_PATH": str(tmp_path / "open-api-billing.db")},
    )
    result = create_engine_from_settings(settings)
    create_all(result)
    try:
        yield result
    finally:
        result.dispose()


@pytest.fixture
def coordinator(engine):
    global _TEST_ENGINE
    _TEST_ENGINE = engine
    open_api = SqlAlchemyOpenApiRepository(engine)
    _create_open_api_identity(open_api)
    pricing = PriceCatalogService(PriceCatalogRepository(engine))
    pricing.publish(
        PriceCatalogDraft(
            version="2026-08-open-api",
            effective_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            rules=(
                PriceRule(
                    id="open-api-text",
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
    return OpenApiBillingCoordinator(BillingRepository(engine), pricing)


_TEST_ENGINE = None
_TEST_FENCES = {}
_TEST_FENCE_LOCK = Lock()


def _execution_fence(session):
    with _TEST_FENCE_LOCK:
        fence = _TEST_FENCES.get(session.invocation_id)
        if fence is not None:
            return fence
        assert _TEST_ENGINE is not None
        fence = SqlAlchemyOpenApiRepository(
            _TEST_ENGINE,
        ).claim_invocation_execution(
            session.invocation_id,
            f"unit-{session.invocation_id}",
            lease_seconds=300,
        )
        assert fence is not None
        _TEST_FENCES[session.invocation_id] = fence
        return fence


def _create_open_api_identity(
    repo: SqlAlchemyOpenApiRepository,
    *,
    app_id: str = "app-1",
    publication_id: str = "pub-1",
    api_key_id: str = "key-1",
    bound_user_id: str = "bound-user-24",
) -> None:
    repo.upsert_publication(
        {
            "id": publication_id,
            "public_id": f"public-{publication_id}",
            "target_type": "agent",
            "target_id": "agent-1",
            "owner_user_id": "publication-owner",
            "bound_user_id": bound_user_id,
            "name": "Open API agent",
        },
    )
    repo.create_external_app(
        {"id": app_id, "owner_user_id": "app-owner", "name": app_id},
    )
    repo.create_api_key(
        {
            "id": api_key_id,
            "app_id": app_id,
            "publication_id": publication_id,
            "key_hash": f"hash-{api_key_id}",
            "key_prefix": "qp_live",
            "key_suffix": "test",
            "scopes": ["messages:create"],
        },
    )


def _command(
    *,
    app_id: str = "app-1",
    publication_id: str = "pub-1",
    api_key_id: str = "key-1",
    key: str | None = "request-1",
    message: str = "first message",
    mode: str = "shadow",
    budget_credits: int = 0,
    payload: dict | None = None,
    sealed_runtime: dict[str, str] | None = None,
) -> OpenApiBillingCommand:
    return OpenApiBillingCommand(
        app_id=app_id,
        publication_id=publication_id,
        api_key_id=api_key_id,
        target_type="agent",
        target_id="agent-1",
        external_user_id="caller-controlled-user",
        external_session_id="caller-session",
        payload=payload or {"message": message, "metadata": {"a": 1}},
        idempotency_key=key,
        mode=mode,
        budget_credits=budget_credits,
        sealed_runtime=sealed_runtime,
    )


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def test_begin_resolves_wallet_only_from_publication_bound_user(
    coordinator,
):
    session = coordinator.begin_invocation(_command())

    assert session.bound_user_id == "bound-user-24"
    assert (
        session.wallet_id
        == coordinator.repository.get_wallet(
            "user",
            "bound-user-24",
        )["id"]
    )
    assert session.bound_user_id != "caller-controlled-user"


def test_zero_balance_blocks_model_call_even_when_overdraft_flag_is_enabled(
    coordinator,
    engine,
):
    with engine.begin() as conn:
        user_id = conn.execute(
            insert(users)
            .values(
                username="szzz_admin",
                password_hash="hash",
                password_salt="salt",
                role="admin",
                billing_overdraft_enabled=True,
            )
            .returning(users.c.id),
        ).scalar_one()
        conn.execute(
            update(open_api_publications)
            .where(open_api_publications.c.id == "pub-1")
            .values(bound_user_id=str(user_id)),
        )

    session = coordinator.begin_invocation(_command(mode="enforced"))
    service = UsageService(coordinator.repository, coordinator.pricing)
    with pytest.raises(InsufficientUsageCreditsError) as raised:
        service.reserve_model_call(_reserve(session, "free-call"))

    assert session.mode == "enforced"
    assert raised.value.required == 1
    assert raised.value.available == 0
    assert coordinator.repository.balance(session.wallet_id).available == 0
    assert coordinator.repository.balance(session.wallet_id).debt == 0
    assert coordinator.repository.balance(session.wallet_id).held == 0
    assert service.list_items(session.usage_order_id) == []


def test_same_key_and_canonical_payload_replays_existing_pair(
    coordinator,
    engine,
):
    first = coordinator.begin_invocation(_command())
    replay = coordinator.begin_invocation(
        _command(payload={"metadata": {"a": 1}, "message": "first message"}),
    )

    assert replay == first
    with engine.connect() as conn:
        assert (
            conn.scalar(select(func.count()).select_from(billing_usage_orders))
            == 1
        )
        assert (
            conn.scalar(select(func.count()).select_from(open_api_invocations))
            == 1
        )
        snapshot = conn.scalar(
            select(billing_usage_orders.c.request_snapshot_json),
        )
    assert "first message" not in snapshot
    assert json.loads(snapshot)["request_sha256"]


def test_sealed_runtime_identity_is_audited_but_not_priced(
    coordinator, engine
):
    identity = {
        "release_id": "release-1",
        "version": "3.7.1",
        "content_digest": f"sha256:{'a' * 64}",
        "adapter": "sealed_harness",
        "contract_version": "1",
    }

    session = coordinator.begin_invocation(
        _command(key="sealed-audit", sealed_runtime=identity),
    )

    with engine.connect() as conn:
        snapshot = json.loads(
            conn.scalar(
                select(billing_usage_orders.c.request_snapshot_json).where(
                    billing_usage_orders.c.id == session.usage_order_id,
                ),
            ),
        )
    assert snapshot["sealed_runtime"] == identity
    assert "credits" not in snapshot["sealed_runtime"]


def test_request_without_client_key_creates_distinct_invocation_pairs(
    coordinator,
    engine,
):
    first = coordinator.begin_invocation(_command(key=None))
    second = coordinator.begin_invocation(_command(key=None))

    assert first.invocation_id != second.invocation_id
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                billing_usage_orders.c.source_type,
                billing_usage_orders.c.source_id,
                open_api_invocations.c.billing_usage_order_id,
            ).join(
                open_api_invocations,
                open_api_invocations.c.billing_usage_order_id
                == billing_usage_orders.c.id,
            ),
        ).all()
    assert {
        (row.source_type, row.source_id, row.billing_usage_order_id)
        for row in rows
    } == {
        ("open_api", first.invocation_id, first.usage_order_id),
        ("open_api", second.invocation_id, second.usage_order_id),
    }


def test_client_key_cannot_collide_with_server_generated_invocation_key(
    coordinator,
    engine,
):
    first = coordinator.begin_invocation(_command(key=None))

    client_key = f"invocation:{first.invocation_id}"
    second = coordinator.begin_invocation(_command(key=client_key))

    assert second.invocation_id != first.invocation_id
    assert second.usage_order_id != first.usage_order_id
    with engine.connect() as conn:
        keys = conn.scalars(select(billing_usage_orders.c.business_key)).all()
    assert set(keys) == {
        f"openapi-invocation:{first.invocation_id}",
        f"openapi:app-1:pub-1:{client_key}",
    }


def test_coordinator_locks_catalog_selected_by_injected_pricing_clock(engine):
    open_api = SqlAlchemyOpenApiRepository(engine)
    _create_open_api_identity(open_api)
    clock = MutableClock(datetime(2030, 1, 1, tzinfo=timezone.utc))
    pricing = PriceCatalogService(PriceCatalogRepository(engine), clock=clock)
    pricing.publish(
        PriceCatalogDraft(
            version="future-v1",
            effective_at=clock.now,
            rules=(
                PriceRule(
                    id="future-text",
                    provider_id="provider",
                    model_key="model",
                    capability="text",
                    unit_type="tokens",
                    input_credits_per_1k=1,
                ),
            ),
        ),
    )
    coordinator = OpenApiBillingCoordinator(BillingRepository(engine), pricing)

    quote = pricing.quote(
        QuoteRequest(
            provider_id="provider",
            model_key="model",
            capability="text",
            parameters={},
        ),
    )
    session = coordinator.begin_invocation(_command())

    assert quote.catalog_version == "future-v1"
    assert session.catalog_version == "future-v1"


def test_sqlite_concurrent_same_key_replays_one_pair(coordinator):
    start = Barrier(2)

    def begin():
        start.wait()
        return coordinator.begin_invocation(_command(key="sqlite-same-key"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _index: begin(), range(2)))

    assert first == second


def test_sqlite_concurrent_same_key_payload_drift_conflicts(coordinator):
    start = Barrier(2)

    def begin(message: str):
        start.wait()
        try:
            return coordinator.begin_invocation(
                _command(key="sqlite-drift", message=message),
            )
        except IdempotencyConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(begin, ("first", "changed")))

    sessions = [result for result in results if result != "conflict"]
    assert len(sessions) == 1
    assert results.count("conflict") == 1


def test_same_key_with_different_canonical_payload_conflicts(coordinator):
    coordinator.begin_invocation(_command(message="first"))

    with pytest.raises(IdempotencyConflictError):
        coordinator.begin_invocation(_command(message="changed"))


def test_idempotency_key_namespace_includes_app_and_publication(
    coordinator,
    engine,
):
    repo = SqlAlchemyOpenApiRepository(engine)
    _create_open_api_identity(
        repo,
        app_id="app-2",
        publication_id="pub-2",
        api_key_id="key-2",
        bound_user_id="bound-user-25",
    )

    first = coordinator.begin_invocation(_command())
    second = coordinator.begin_invocation(
        _command(app_id="app-2", publication_id="pub-2", api_key_id="key-2"),
    )

    assert first.invocation_id != second.invocation_id
    with engine.connect() as conn:
        keys = conn.scalars(select(billing_usage_orders.c.business_key)).all()
    assert set(keys) == {
        "openapi:app-1:pub-1:request-1",
        "openapi:app-2:pub-2:request-1",
    }


def test_failure_between_order_and_invocation_rolls_back_both(engine):
    open_api = SqlAlchemyOpenApiRepository(engine)
    _create_open_api_identity(open_api)
    pricing = PriceCatalogService(PriceCatalogRepository(engine))
    pricing.publish(
        PriceCatalogDraft(
            version="2026-08-open-api",
            effective_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            rules=(
                PriceRule(
                    id="open-api-text",
                    provider_id="provider",
                    model_key="model",
                    capability="text",
                    unit_type="tokens",
                    input_credits_per_1k=1,
                ),
            ),
        ),
    )
    coordinator = OpenApiBillingCoordinator(
        BillingRepository(engine),
        pricing,
        after_order_insert=lambda: (_ for _ in ()).throw(
            RuntimeError("injected"),
        ),
    )

    with pytest.raises(RuntimeError, match="injected"):
        coordinator.begin_invocation(_command())

    with engine.connect() as conn:
        assert (
            conn.scalar(select(func.count()).select_from(billing_usage_orders))
            == 0
        )
        assert (
            conn.scalar(select(func.count()).select_from(open_api_invocations))
            == 0
        )
        assert (
            conn.scalar(select(func.count()).select_from(billing_wallets)) == 0
        )


def test_replay_preserves_persisted_wallet_catalog_and_mode(
    coordinator,
    engine,
):
    first = coordinator.begin_invocation(_command(mode="shadow"))
    with engine.begin() as conn:
        conn.execute(
            update(open_api_publications)
            .where(open_api_publications.c.id == "pub-1")
            .values(bound_user_id="later-bound-user"),
        )

    replay = coordinator.begin_invocation(_command(mode="enforced"))

    assert replay.wallet_id == first.wallet_id
    assert replay.bound_user_id == first.bound_user_id
    assert replay.catalog_version == first.catalog_version
    assert replay.mode == "shadow"


def _reserve(
    session,
    item_key: str,
    *,
    max_output_tokens: int = 1000,
    capability: str = "text",
    tier: str = "standard",
) -> ReserveModelCall:
    return ReserveModelCall(
        usage_order_id=session.usage_order_id,
        item_key=item_key,
        provider_id="provider",
        model_key="model",
        capability=capability,
        parameters={"tier": tier},
        input_tokens=1000,
        max_output_tokens=max_output_tokens,
        invocation_id=session.invocation_id,
        execution_fence=_execution_fence(session),
    )


def _settle(
    session,
    item_key: str,
    billability: str,
    *,
    input_tokens: int = 1000,
    output_tokens: int = 0,
) -> SettleModelCall:
    return SettleModelCall(
        usage_order_id=session.usage_order_id,
        item_key=item_key,
        supplier_reference=f"supplier-{item_key}",
        billability=billability,
        evidence={"usage": {"input_tokens": input_tokens}},
        actual_input_tokens=input_tokens,
        actual_output_tokens=output_tokens,
        invocation_id=session.invocation_id,
        execution_fence=_execution_fence(session),
    )


def _fund(coordinator, session, amount: int) -> None:
    coordinator.repository.grant(
        session.wallet_id,
        credits=amount,
        credit_type="purchased",
        expires_at=None,
        idempotency_key=f"fund-{session.invocation_id}",
    )


def _publish_model_tier(coordinator, tier: str) -> None:
    coordinator.pricing.publish(
        PriceCatalogDraft(
            version=f"tier-{tier}",
            effective_at=datetime.now(timezone.utc),
            rules=(
                PriceRule(
                    id=f"text-{tier}",
                    provider_id="provider",
                    model_key="model",
                    capability="text",
                    unit_type="tokens",
                    input_credits_per_1k=1,
                    output_credits_per_1k=1,
                    metadata={"economic_tier": tier},
                ),
            ),
        ),
    )


def test_model_items_incrementally_hold_then_project_mixed_settlement(
    coordinator,
):
    session = coordinator.begin_invocation(_command(mode="enforced"))
    _fund(coordinator, session, 20)
    service = UsageService(coordinator.repository, coordinator.pricing)

    first = service.reserve_model_call(_reserve(session, "call-1"))
    second = service.reserve_model_call(_reserve(session, "call-2"))
    third = service.reserve_model_call(_reserve(session, "call-3"))

    assert (
        first.usage_order_id == second.usage_order_id == third.usage_order_id
    )
    assert coordinator.repository.balance(session.wallet_id).held == 0
    assert len(service.list_items(session.usage_order_id)) == 3

    captured = service.settle_model_call(
        _settle(session, "call-1", "billable", output_tokens=0),
    )
    released = service.settle_model_call(
        _settle(session, "call-2", "not_billable"),
    )
    reconciling = service.settle_model_call(
        _settle(session, "call-3", "unknown"),
    )

    assert captured.captured_credits == 1
    assert released.released_credits == 2
    assert reconciling.status == "reconciling"
    order = service.get_order(session.usage_order_id)
    assert order["captured_credits"] == 1
    assert order["released_credits"] == 3
    assert order["reconciling_credits"] == 0
    assert coordinator.repository.balance(session.wallet_id).held == 0


def test_actual_charge_can_make_balance_negative_then_blocks_next_call(
    coordinator,
    monkeypatch,
):
    session = coordinator.begin_invocation(_command(mode="enforced"))
    _fund(coordinator, session, 1)
    service = UsageService(coordinator.repository, coordinator.pricing)
    supplier_calls: list[str] = []

    service.reserve_model_call(_reserve(session, "call-1"))
    service.settle_model_call(
        _settle(session, "call-1", "billable", output_tokens=1000),
    )
    balance = coordinator.repository.balance(session.wallet_id)

    def reject_cross_transaction_balance(_wallet_id):
        raise AssertionError("must not open a second wallet transaction")

    monkeypatch.setattr(
        coordinator.repository,
        "balance",
        reject_cross_transaction_balance,
    )
    with pytest.raises(InsufficientUsageCreditsError) as raised:
        service.reserve_model_call(_reserve(session, "call-2"))

    assert raised.value.required == 1
    assert raised.value.available == -1
    assert not supplier_calls
    assert (
        service.list_items(session.usage_order_id)[0]["status"] == "captured"
    )
    assert balance.available == -1
    assert balance.debt == 1
    assert balance.held == 0


def test_model_item_replay_is_idempotent_and_payload_drift_conflicts(
    coordinator,
):
    session = coordinator.begin_invocation(_command(mode="enforced"))
    _fund(coordinator, session, 4)
    service = UsageService(coordinator.repository, coordinator.pricing)

    first = service.reserve_model_call(_reserve(session, "call-1"))
    replay = service.reserve_model_call(_reserve(session, "call-1"))
    assert replay == first
    with pytest.raises(UsageOrderConflictError):
        service.reserve_model_call(
            _reserve(session, "call-1", max_output_tokens=2000),
        )

    settled = service.settle_model_call(_settle(session, "call-1", "billable"))
    assert (
        service.settle_model_call(
            _settle(session, "call-1", "billable"),
        )
        == settled
    )
    with pytest.raises(UsageOrderConflictError):
        service.settle_model_call(
            _settle(session, "call-1", "not_billable"),
        )


def test_invocation_budget_rejects_the_next_model_reservation(
    coordinator,
):
    session = coordinator.begin_invocation(
        _command(mode="enforced", budget_credits=2),
    )
    _fund(coordinator, session, 20)
    service = UsageService(coordinator.repository, coordinator.pricing)

    service.reserve_model_call(_reserve(session, "call-1"))
    service.settle_model_call(
        _settle(session, "call-1", "billable", output_tokens=1000),
    )
    with pytest.raises(InsufficientUsageCreditsError) as raised:
        service.reserve_model_call(_reserve(session, "call-2"))

    assert raised.value.required == 1
    assert raised.value.available == 0


def test_model_call_uses_the_catalog_locked_by_its_invocation(
    coordinator,
):
    session = coordinator.begin_invocation(_command(mode="enforced"))
    _fund(coordinator, session, 20)
    coordinator.pricing.publish(
        PriceCatalogDraft(
            version="later-price",
            effective_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            rules=(
                PriceRule(
                    id="later-text",
                    provider_id="provider",
                    model_key="model",
                    capability="text",
                    unit_type="tokens",
                    input_credits_per_1k=9,
                    output_credits_per_1k=9,
                ),
            ),
        ),
    )

    held = UsageService(
        coordinator.repository,
        coordinator.pricing,
    ).reserve_model_call(_reserve(session, "call-1"))

    assert held.quoted_credits == 2


def test_positive_trial_balance_allows_model_call_without_pre_hold(
    coordinator,
):
    session = coordinator.begin_invocation(_command(mode="enforced"))
    coordinator.repository.append_transaction(
        LedgerTransaction(
            wallet_id=session.wallet_id,
            event_type="promotion_grant",
            credits=10,
            business_type="signup_trial",
            business_key="trial-model-tier",
            idempotency_key="trial-model-tier",
            credit_type="promotional",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            metadata={
                "grant_policy": "signup_trial",
                "allowed_capabilities": ["text"],
                "denied_capabilities": ["high_cost"],
            },
        ),
    )

    service = UsageService(coordinator.repository, coordinator.pricing)
    service.reserve_model_call(_reserve(session, "call-1", tier="high_cost"))
    service.settle_model_call(
        _settle(session, "call-1", "billable", output_tokens=1000),
    )

    assert coordinator.repository.balance(session.wallet_id).available == 8
    assert coordinator.repository.balance(session.wallet_id).held == 0


def test_observe_mode_persists_item_without_mutating_wallet(coordinator):
    session = coordinator.begin_invocation(_command(mode="observe"))
    _fund(coordinator, session, 10)
    service = UsageService(coordinator.repository, coordinator.pricing)

    service.reserve_model_call(_reserve(session, "call-1"))
    service.settle_model_call(_settle(session, "call-1", "billable"))

    assert coordinator.repository.balance(session.wallet_id).available == 10
    assert coordinator.repository.balance(session.wallet_id).held == 0


def test_observe_dry_run_records_pass_without_any_accounting_mutation(
    coordinator,
    engine,
):
    session = coordinator.begin_invocation(_command(mode="observe"))
    _fund(coordinator, session, 10)
    before = coordinator.repository.balance(session.wallet_id)
    with engine.connect() as conn:
        ledger_before = conn.scalar(
            select(func.count()).select_from(billing_ledger_entries),
        )

    UsageService(
        coordinator.repository,
        coordinator.pricing,
    ).reserve_model_call(
        _reserve(session, "observe-pass"),
    )

    with engine.connect() as conn:
        item = (
            conn.execute(
                select(billing_usage_items).where(
                    billing_usage_items.c.item_key == "observe-pass",
                ),
            )
            .mappings()
            .one()
        )
        ledger_after = conn.scalar(
            select(func.count()).select_from(billing_ledger_entries),
        )
    assert item["would_pass"] is True
    assert item["would_block_reason"] is None
    assert ledger_after == ledger_before
    assert coordinator.repository.balance(session.wallet_id) == before


def test_observe_dry_run_uses_positive_net_balance_without_mutation(
    coordinator,
    engine,
):
    _publish_model_tier(coordinator, "high_cost")
    session = coordinator.begin_invocation(_command(mode="observe", key="obs"))
    coordinator.repository.append_transaction(
        LedgerTransaction(
            wallet_id=session.wallet_id,
            event_type="promotion_grant",
            credits=10,
            business_type="signup_trial",
            business_key="observe-trial",
            idempotency_key="observe-trial",
            credit_type="promotional",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            metadata={
                "grant_policy": "signup_trial",
                "allowed_capabilities": ["text"],
                "allowed_tiers": ["standard"],
                "denied_capabilities": ["high_cost"],
            },
        ),
    )
    before = coordinator.repository.balance(session.wallet_id)

    UsageService(
        coordinator.repository,
        coordinator.pricing,
    ).reserve_model_call(
        _reserve(session, "observe-block", tier="standard"),
    )

    with engine.connect() as conn:
        item = (
            conn.execute(
                select(billing_usage_items).where(
                    billing_usage_items.c.item_key == "observe-block",
                ),
            )
            .mappings()
            .one()
        )
        usage_ledger = conn.scalar(
            select(func.count())
            .select_from(billing_ledger_entries)
            .where(billing_ledger_entries.c.event_type == "usage_hold"),
        )
    assert item["would_pass"] is True
    assert item["would_block_reason"] is None
    assert usage_ledger == 0
    assert coordinator.repository.balance(session.wallet_id) == before


def test_observe_dry_run_excludes_expired_lot_without_expiry_writes(
    coordinator,
    engine,
):
    session = coordinator.begin_invocation(
        _command(mode="observe", key="observe-expired"),
    )
    coordinator.repository.append_transaction(
        LedgerTransaction(
            wallet_id=session.wallet_id,
            event_type="promotion_grant",
            credits=10,
            business_type="signup_trial",
            business_key="observe-expired-trial",
            idempotency_key="observe-expired-trial",
            credit_type="promotional",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            metadata={
                "grant_policy": "signup_trial",
                "allowed_capabilities": ["text"],
                "allowed_tiers": ["standard"],
            },
        ),
    )
    with engine.begin() as conn:
        conn.execute(
            update(billing_credit_lots)
            .where(billing_credit_lots.c.wallet_id == session.wallet_id)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(days=1)),
        )
        wallet_before = dict(
            conn.execute(
                select(billing_wallets).where(
                    billing_wallets.c.id == session.wallet_id,
                ),
            )
            .mappings()
            .one(),
        )
        lot_before = dict(
            conn.execute(
                select(billing_credit_lots).where(
                    billing_credit_lots.c.wallet_id == session.wallet_id,
                ),
            )
            .mappings()
            .one(),
        )
        ledger_before = conn.scalar(
            select(func.count()).select_from(billing_ledger_entries),
        )

    UsageService(
        coordinator.repository,
        coordinator.pricing,
    ).reserve_model_call(
        _reserve(session, "observe-expired"),
    )

    with engine.connect() as conn:
        item = (
            conn.execute(
                select(billing_usage_items).where(
                    billing_usage_items.c.item_key == "observe-expired",
                ),
            )
            .mappings()
            .one()
        )
        wallet_after = dict(
            conn.execute(
                select(billing_wallets).where(
                    billing_wallets.c.id == session.wallet_id,
                ),
            )
            .mappings()
            .one(),
        )
        lot_after = dict(
            conn.execute(
                select(billing_credit_lots).where(
                    billing_credit_lots.c.wallet_id == session.wallet_id,
                ),
            )
            .mappings()
            .one(),
        )
        ledger_after = conn.scalar(
            select(func.count()).select_from(billing_ledger_entries),
        )
    assert item["would_pass"] is False
    assert item["would_block_reason"] == "insufficient_credits"
    assert (wallet_after, lot_after, ledger_after) == (
        wallet_before,
        lot_before,
        ledger_before,
    )


def test_enforced_model_call_uses_balance_instead_of_tier_preauthorization(
    coordinator,
):
    _publish_model_tier(coordinator, "high_cost")
    session = coordinator.begin_invocation(
        _command(mode="enforced", key="trusted-tier"),
    )
    coordinator.repository.append_transaction(
        LedgerTransaction(
            wallet_id=session.wallet_id,
            event_type="promotion_grant",
            credits=10,
            business_type="signup_trial",
            business_key="trusted-tier-trial",
            idempotency_key="trusted-tier-trial",
            credit_type="promotional",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            metadata={
                "grant_policy": "signup_trial",
                "allowed_capabilities": ["text"],
                "allowed_tiers": ["standard"],
                "denied_capabilities": ["high_cost"],
            },
        ),
    )

    UsageService(
        coordinator.repository,
        coordinator.pricing,
    ).reserve_model_call(
        _reserve(session, "trusted-tier", tier="standard"),
    )
    assert coordinator.repository.balance(session.wallet_id).available == 10
    assert coordinator.repository.balance(session.wallet_id).held == 0


def test_billable_zero_actual_usage_releases_its_entire_hold(coordinator):
    session = coordinator.begin_invocation(_command(mode="enforced"))
    _fund(coordinator, session, 10)
    service = UsageService(coordinator.repository, coordinator.pricing)
    service.reserve_model_call(_reserve(session, "call-1"))

    settled = service.settle_model_call(
        _settle(
            session,
            "call-1",
            "billable",
            input_tokens=0,
            output_tokens=0,
        ),
    )

    assert settled.status == "captured"
    assert settled.captured_credits == 0
    assert settled.released_credits == 2
    assert coordinator.repository.balance(session.wallet_id).held == 0


def test_reconciling_item_later_settles_when_supplier_evidence_arrives(
    coordinator,
):
    session = coordinator.begin_invocation(_command(mode="enforced"))
    _fund(coordinator, session, 10)
    service = UsageService(coordinator.repository, coordinator.pricing)
    service.reserve_model_call(_reserve(session, "call-1"))
    service.settle_model_call(_settle(session, "call-1", "unknown"))

    resolved = service.settle_model_call(
        _settle(session, "call-1", "billable", output_tokens=0),
    )

    assert resolved.status == "captured"
    assert resolved.captured_credits == 1
    assert coordinator.repository.balance(session.wallet_id).held == 0


def test_positive_trial_balance_does_not_require_pre_call_tier_policy(
    coordinator,
):
    session = coordinator.begin_invocation(_command(mode="enforced"))
    coordinator.repository.append_transaction(
        LedgerTransaction(
            wallet_id=session.wallet_id,
            event_type="promotion_grant",
            credits=10,
            business_type="signup_trial",
            business_key="trial-no-tier-policy",
            idempotency_key="trial-no-tier-policy",
            credit_type="promotional",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            metadata={
                "grant_policy": "signup_trial",
                "allowed_capabilities": ["text"],
            },
        ),
    )

    UsageService(
        coordinator.repository,
        coordinator.pricing,
    ).reserve_model_call(_reserve(session, "call-1", tier="standard"))
    assert coordinator.repository.balance(session.wallet_id).available == 10
    assert coordinator.repository.balance(session.wallet_id).held == 0


def test_sqlite_concurrent_same_model_item_reservation_replays_once(
    coordinator,
):
    session = coordinator.begin_invocation(_command(mode="enforced"))
    _fund(coordinator, session, 10)
    service = UsageService(coordinator.repository, coordinator.pricing)
    start = Barrier(2)

    def reserve_once():
        start.wait()
        return service.reserve_model_call(_reserve(session, "call-1"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _index: reserve_once(), range(2)))

    assert first == second
    assert len(service.list_items(session.usage_order_id)) == 1
    assert coordinator.repository.balance(session.wallet_id).held == 0
