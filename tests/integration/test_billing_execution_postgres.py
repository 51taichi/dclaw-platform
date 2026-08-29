# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.schema import CreateSchema, DropSchema

from qwenpaw.app.storage.repos.billing_execution_repo import (
    BillingExecutionCommand,
    BillingExecutionRepository,
)
from qwenpaw.app.storage.schema import (
    billing_price_catalogs,
    billing_usage_orders,
    billing_wallets,
    create_all,
)
from qwenpaw.app.storage.settings import normalize_postgres_url


@pytest.fixture
def postgres_execution_repo():
    raw_url = os.environ.get("QWENPAW_TEST_POSTGRES_URL", "").strip()
    if not raw_url:
        pytest.skip("QWENPAW_TEST_POSTGRES_URL is not configured")
    database_url = normalize_postgres_url(raw_url)
    schema_name = f"billing_execution_test_{uuid4().hex}"
    admin_engine = create_engine(database_url, future=True)
    with admin_engine.begin() as conn:
        conn.execute(CreateSchema(schema_name))
    engine = create_engine(
        database_url,
        future=True,
        connect_args={"options": f"-csearch_path={schema_name}"},
    )
    try:
        create_all(engine)
        now = datetime.now(timezone.utc)
        with engine.begin() as conn:
            conn.execute(
                insert(billing_wallets).values(
                    id="wallet-1",
                    owner_type="user",
                    owner_id="user-1",
                ),
            )
            conn.execute(
                insert(billing_price_catalogs).values(
                    id="catalog-1",
                    version="v1",
                    status="published",
                    effective_at=now,
                ),
            )
            conn.execute(
                insert(billing_usage_orders).values(
                    id="order-1",
                    wallet_id="wallet-1",
                    catalog_id="catalog-1",
                    business_key="billing:client:chat-1:request-1",
                    source_type="client",
                    source_id="chat-1",
                    provider_id="request",
                    model_key="request",
                    capability="text",
                ),
            )
        yield BillingExecutionRepository(engine)
    finally:
        engine.dispose()
        with admin_engine.begin() as conn:
            conn.execute(DropSchema(schema_name, cascade=True))
        admin_engine.dispose()


@pytest.mark.integration
def test_postgres_concurrent_claim_has_one_fenced_owner(
    postgres_execution_repo,
):
    postgres_execution_repo.create_or_replay(
        BillingExecutionCommand(
            execution_id="execution-1",
            usage_order_id="order-1",
            payer_user_id="user-1",
            source_type="client",
            source_id="chat-1",
            request_sha256="a" * 64,
        ),
    )

    def claim(index: int):
        return postgres_execution_repo.claim(
            "execution-1",
            f"worker-{index}",
            lease_seconds=30,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(claim, range(8)))

    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert winners[0].generation == 1
