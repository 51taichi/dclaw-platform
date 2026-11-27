# -*- coding: utf-8 -*-
"""Live PostgreSQL coverage for manual top-up persistence."""

# pylint: disable=redefined-outer-name
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.schema import CreateSchema, DropSchema

from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.top_up_repo import TopUpRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import normalize_postgres_url


@pytest.fixture
def postgres_top_up_engine():
    raw_url = os.environ.get("QWENPAW_TEST_POSTGRES_URL", "").strip()
    if not raw_url:
        pytest.skip("QWENPAW_TEST_POSTGRES_URL is not configured")
    database_url = normalize_postgres_url(raw_url)
    schema_name = f"top_up_test_{uuid4().hex}"
    admin = create_engine(database_url, future=True, pool_pre_ping=True)
    with admin.begin() as connection:
        connection.execute(CreateSchema(schema_name))
    engine = create_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema_name}"},
    )
    create_all(engine)
    create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(DropSchema(schema_name, cascade=True))
        admin.dispose()


def _product():
    return {
        "name": "1000 credits",
        "payment_amount_fen": 1000,
        "purchased_credits": 1000,
        "promotional_credits": 0,
        "promotional_expiry_days": None,
        "status": "active",
        "display_order": 1,
        "created_by": "admin-1",
    }


@pytest.mark.integration
def test_postgresql_top_up_claim_replay_and_immutable_audit(
    postgres_top_up_engine,
):
    billing = BillingRepository(postgres_top_up_engine)
    wallet = billing.ensure_wallet("user", "user-1")
    repo = TopUpRepository(postgres_top_up_engine)
    product = repo.create_product(_product())
    barrier = Barrier(2)

    def submit():
        barrier.wait()
        return repo.create_claim(
            owner_id="user-1",
            wallet_id=str(wallet["id"]),
            product_public_id=str(product["public_id"]),
            payment_channel="wechat",
            payer_reference="tail-1234",
            customer_note=None,
            idempotency_key="submit-once",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: submit(), range(2)))
    assert len({claim["public_id"] for claim in claims}) == 1

    claim = claims[0]
    with postgres_top_up_engine.begin() as connection:
        repo.append_audit(
            connection,
            {
                "claim_id": claim["id"],
                "action": "submitted",
                "actor_id": "user-1",
                "reason": "submitted",
                "idempotency_key": "audit-submit-once",
                "request_sha256": "hash",
                "payment_amount_fen": 1000,
                "purchased_credits": 1000,
                "promotional_credits": 0,
            },
        )
    with (
        postgres_top_up_engine.begin() as connection,
        pytest.raises(
            DatabaseError,
        ),
    ):
        connection.execute(
            text("UPDATE billing_top_up_audits SET reason='changed'"),
        )
