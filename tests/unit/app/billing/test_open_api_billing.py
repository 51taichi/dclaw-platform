# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from sqlalchemy import func, select, update

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
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.open_api_repo import SqlAlchemyOpenApiRepository
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.schema import (
    billing_usage_orders,
    billing_wallets,
    create_all,
    open_api_invocations,
    open_api_publications,
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
    return OpenApiBillingCoordinator(BillingRepository(engine), pricing)


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
    payload: dict | None = None,
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


def test_same_key_and_canonical_payload_replays_existing_pair(
    coordinator, engine
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


def test_request_without_client_key_creates_distinct_invocation_pairs(
    coordinator, engine
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
    coordinator, engine
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
            RuntimeError("injected")
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
    coordinator, engine
):
    first = coordinator.begin_invocation(_command(mode="shadow"))
    with engine.begin() as conn:
        conn.execute(
            update(open_api_publications)
            .where(open_api_publications.c.id == "pub-1")
            .values(bound_user_id="later-bound-user")
        )

    replay = coordinator.begin_invocation(_command(mode="enforced"))

    assert replay.wallet_id == first.wallet_id
    assert replay.bound_user_id == first.bound_user_id
    assert replay.catalog_version == first.catalog_version
    assert replay.mode == "shadow"
