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
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.open_api_repo import SqlAlchemyOpenApiRepository
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.schema import (
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


def _coordinator(engine, *, publish_catalog: bool = True):
    open_api = SqlAlchemyOpenApiRepository(engine)
    open_api.upsert_publication(
        {
            "id": "pub-1",
            "public_id": "public-pub-1",
            "target_type": "agent",
            "target_id": "agent-1",
            "owner_user_id": "publication-owner",
            "bound_user_id": "bound-user",
            "name": "Open API agent",
        },
    )
    open_api.create_external_app(
        {"id": "app-1", "owner_user_id": "app-owner", "name": "app"},
    )
    open_api.create_api_key(
        {
            "id": "key-1",
            "app_id": "app-1",
            "publication_id": "pub-1",
            "key_hash": "hash-key-1",
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


def _command(key: str, message: str = "first") -> OpenApiBillingCommand:
    return OpenApiBillingCommand(
        app_id="app-1",
        publication_id="pub-1",
        api_key_id="key-1",
        target_type="agent",
        target_id="agent-1",
        external_user_id="external-user",
        external_session_id="external-session",
        payload={"message": message},
        idempotency_key=key,
    )


@pytest.mark.integration
def test_postgresql_open_api_same_key_drift_catalog_and_rollback(
    postgres_open_api_engine,
):
    coordinator = _coordinator(postgres_open_api_engine)
    same_start = Barrier(2)

    def same_key():
        same_start.wait()
        return coordinator.begin_invocation(_command("postgres-same"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        same_sessions = list(pool.map(lambda _index: same_key(), range(2)))
    assert same_sessions[0] == same_sessions[1]

    drift_start = Barrier(2)

    def drift(message: str):
        drift_start.wait()
        try:
            return coordinator.begin_invocation(
                _command("postgres-drift", message)
            )
        except IdempotencyConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        drift_results = list(pool.map(drift, ("first", "changed")))
    assert drift_results.count("conflict") == 1

    with postgres_open_api_engine.connect() as conn:
        order_count = conn.scalar(
            select(func.count()).select_from(billing_usage_orders)
        )
        invocation_count = conn.scalar(
            select(func.count()).select_from(open_api_invocations),
        )
    failing = OpenApiBillingCoordinator(
        coordinator.repository,
        coordinator.pricing,
        after_order_insert=lambda: (_ for _ in ()).throw(
            RuntimeError("injected")
        ),
    )
    with pytest.raises(RuntimeError, match="injected"):
        failing.begin_invocation(_command("postgres-rollback"))
    with postgres_open_api_engine.connect() as conn:
        assert (
            conn.scalar(select(func.count()).select_from(billing_usage_orders))
            == order_count
        )
        assert (
            conn.scalar(select(func.count()).select_from(open_api_invocations))
            == invocation_count
        )


@pytest.mark.integration
def test_postgresql_open_api_missing_catalog_is_controlled(
    postgres_open_api_engine,
):
    coordinator = _coordinator(postgres_open_api_engine, publish_catalog=False)

    with pytest.raises(CatalogNotReadyError):
        coordinator.begin_invocation(_command("postgres-missing-catalog"))
