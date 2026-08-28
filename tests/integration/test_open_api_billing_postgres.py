# -*- coding: utf-8 -*-
"""Live PostgreSQL concurrency coverage for OpenAPI billing sessions."""
# pylint: disable=redefined-outer-name
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.schema import CreateSchema, DropSchema

from qwenpaw.app.billing.open_api import (
    CatalogNotReadyError,
    IdempotencyConflictError,
    OpenApiBillingCommand,
    OpenApiBillingCoordinator,
)
from qwenpaw.app.billing.pricing import (
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
)
from qwenpaw.app.billing.usage import (
    ReserveModelCall,
    SettleModelCall,
    UsageOrderConflictError,
    UsageService,
)
from qwenpaw.app.open_api.runtime import (
    OpenApiBillingRuntime,
    recover_open_api_billing,
)
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.open_api_repo import SqlAlchemyOpenApiRepository
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.schema import (
    billing_wallets,
    billing_usage_orders,
    create_all,
    open_api_invocations,
)
from qwenpaw.app.storage.settings import normalize_postgres_url


@pytest.fixture
def postgres_open_api_engine():
    raw_url = os.environ.get("QWENPAW_TEST_POSTGRES_URL", "").strip()
    if not raw_url:
        pytest.skip(
            "QWENPAW_TEST_POSTGRES_URL is not configured; "
            "live PostgreSQL OpenAPI billing verification was not run",
        )
    database_url = normalize_postgres_url(raw_url)
    schema_name = f"open_api_billing_{uuid4().hex}"
    admin_engine = create_engine(database_url, future=True, pool_pre_ping=True)
    with admin_engine.begin() as conn:
        conn.execute(CreateSchema(schema_name))
    engine = create_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema_name}"},
    )
    create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin_engine.begin() as conn:
            conn.execute(DropSchema(schema_name, cascade=True))
        admin_engine.dispose()


def _coordinator(engine, identity: str, *, publish_catalog: bool = True):
    publication_id = f"pub-{identity}"
    app_id = f"app-{identity}"
    api_key_id = f"key-{identity}"
    open_api = SqlAlchemyOpenApiRepository(engine)
    open_api.upsert_publication(
        {
            "id": publication_id,
            "public_id": f"public-{identity}",
            "target_type": "agent",
            "target_id": "agent-1",
            "owner_user_id": f"publication-owner-{identity}",
            "bound_user_id": f"bound-user-{identity}",
            "name": "Open API agent",
        },
    )
    open_api.create_external_app(
        {
            "id": app_id,
            "owner_user_id": f"app-owner-{identity}",
            "name": "app",
        },
    )
    open_api.create_api_key(
        {
            "id": api_key_id,
            "app_id": app_id,
            "publication_id": publication_id,
            "key_hash": f"hash-{identity}",
            "key_prefix": "qp_live",
            "key_suffix": "test",
            "scopes": ["messages:create"],
        },
    )
    pricing = PriceCatalogService(PriceCatalogRepository(engine))
    if publish_catalog:
        pricing.publish(
            PriceCatalogDraft(
                version="postgres-v1",
                effective_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                rules=(
                    PriceRule(
                        id="postgres-text",
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


def _command(
    identity: str,
    key: str,
    message: str = "first",
    mode: str = "shadow",
) -> OpenApiBillingCommand:
    return OpenApiBillingCommand(
        app_id=f"app-{identity}",
        publication_id=f"pub-{identity}",
        api_key_id=f"key-{identity}",
        target_type="agent",
        target_id="agent-1",
        external_user_id="external-user",
        external_session_id="external-session",
        payload={"message": message},
        idempotency_key=key,
        mode=mode,
    )


def _billing_counts(engine) -> tuple[int, int, int]:
    with engine.connect() as conn:
        return (
            int(
                conn.scalar(select(func.count()).select_from(billing_wallets)),
            ),
            int(
                conn.scalar(
                    select(func.count()).select_from(billing_usage_orders),
                ),
            ),
            int(
                conn.scalar(
                    select(func.count()).select_from(open_api_invocations),
                ),
            ),
        )


@pytest.mark.integration
def test_postgresql_open_api_same_key_and_payload_drift(
    postgres_open_api_engine,
):
    identity = "success"
    coordinator = _coordinator(postgres_open_api_engine, identity)
    same_start = Barrier(2)

    def same_key():
        same_start.wait()
        return coordinator.begin_invocation(
            _command(identity, "postgres-same"),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        same_sessions = list(pool.map(lambda _index: same_key(), range(2)))
    assert same_sessions[0] == same_sessions[1]

    drift_start = Barrier(2)

    def drift(message: str):
        drift_start.wait()
        try:
            return coordinator.begin_invocation(
                _command(identity, "postgres-drift", message),
            )
        except IdempotencyConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        drift_results = list(pool.map(drift, ("first", "changed")))
    assert drift_results.count("conflict") == 1


@pytest.mark.integration
def test_postgresql_open_api_injected_failure_rolls_back_fresh_identity(
    postgres_open_api_engine,
):
    identity = "rollback"
    coordinator = _coordinator(postgres_open_api_engine, identity)
    failing = OpenApiBillingCoordinator(
        coordinator.repository,
        coordinator.pricing,
        after_order_insert=lambda: (_ for _ in ()).throw(
            RuntimeError("injected"),
        ),
    )
    with pytest.raises(RuntimeError, match="injected"):
        failing.begin_invocation(_command(identity, "postgres-rollback"))
    assert _billing_counts(postgres_open_api_engine) == (0, 0, 0)


@pytest.mark.integration
def test_postgresql_open_api_missing_catalog_is_controlled(
    postgres_open_api_engine,
):
    identity = "missing-catalog"
    coordinator = _coordinator(
        postgres_open_api_engine,
        identity,
        publish_catalog=False,
    )

    with pytest.raises(CatalogNotReadyError):
        coordinator.begin_invocation(
            _command(identity, "postgres-missing-catalog"),
        )
    assert _billing_counts(postgres_open_api_engine) == (0, 0, 0)


@pytest.mark.integration
def test_postgresql_capture_and_release_cannot_both_settle_one_item(
    postgres_open_api_engine,
):
    identity = "settlement-race"
    coordinator = _coordinator(postgres_open_api_engine, identity)
    session = coordinator.begin_invocation(
        _command(identity, "settlement", mode="enforced"),
    )
    coordinator.repository.grant(
        session.wallet_id,
        credits=5,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="settlement-funds",
    )
    service = UsageService(coordinator.repository, coordinator.pricing)
    reserve = ReserveModelCall(
        usage_order_id=session.usage_order_id,
        item_key="call-1",
        provider_id="provider",
        model_key="model",
        capability="text",
        parameters={"tier": "standard"},
        input_tokens=1000,
        max_output_tokens=0,
    )
    service.reserve_model_call(reserve)
    start = Barrier(2)

    def settle(billability: str):
        start.wait()
        try:
            return service.settle_model_call(
                SettleModelCall(
                    usage_order_id=session.usage_order_id,
                    item_key="call-1",
                    supplier_reference="supplier-call-1",
                    billability=billability,
                    evidence={"reference": "supplier-call-1"},
                    actual_input_tokens=1000,
                    actual_output_tokens=0,
                ),
            ).status
        except UsageOrderConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(settle, ("billable", "not_billable")))

    assert outcomes.count("conflict") == 1
    assert set(outcomes) in (
        {"conflict", "captured"},
        {"conflict", "released"},
    )
    assert coordinator.repository.balance(session.wallet_id).held == 0


@pytest.mark.integration
def test_postgresql_restart_recovery_is_idempotent_and_preserves_unknown(
    postgres_open_api_engine,
):
    identity = "restart-recovery"
    coordinator = _coordinator(postgres_open_api_engine, identity)
    session = coordinator.begin_invocation(
        _command(identity, "restart", mode="enforced"),
    )
    coordinator.repository.grant(
        session.wallet_id,
        credits=5,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="restart-funds",
    )
    service = UsageService(coordinator.repository, coordinator.pricing)
    service.reserve_model_call(
        ReserveModelCall(
            usage_order_id=session.usage_order_id,
            item_key="precontact",
            provider_id="provider",
            model_key="model",
            capability="text",
            parameters={"tier": "standard"},
            input_tokens=1000,
            max_output_tokens=0,
        ),
    )
    runtime = OpenApiBillingRuntime(
        repository=coordinator.repository,
        pricing=coordinator.pricing,
        coordinator=coordinator,
        usage_service=service,
        open_api_repository=SqlAlchemyOpenApiRepository(
            postgres_open_api_engine,
        ),
        mode="enforced",
        budget_credits=100,
    )

    recover_open_api_billing(runtime)
    first_ledger = coordinator.repository.list_ledger(
        session.wallet_id,
        100,
        None,
    )
    recover_open_api_billing(runtime)

    assert (
        service.list_items(session.usage_order_id)[0]["status"] == "released"
    )
    assert len(
        coordinator.repository.list_ledger(session.wallet_id, 100, None),
    ) == len(first_ledger)
    assert coordinator.repository.balance(session.wallet_id).held == 0
    invocation = runtime.open_api_repository.get_invocation(
        session.invocation_id,
    )
    assert invocation is not None
    assert invocation["status"] == "failed"
    assert invocation["billing_status"] == "settled"
