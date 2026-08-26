# -*- coding: utf-8 -*-
"""Live PostgreSQL concurrency coverage for the billing repository."""
# pylint: disable=redefined-outer-name
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from qwenpaw.app.billing.models import (
    DuplicateLedgerTransactionError,
    InsufficientCreditsError,
    WalletBalance,
)
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import normalize_postgres_url


@pytest.fixture
def postgres_billing_engine():
    raw_url = os.environ.get("QWENPAW_TEST_POSTGRES_URL", "").strip()
    if not raw_url:
        pytest.skip(
            "QWENPAW_TEST_POSTGRES_URL is not configured; "
            "live PostgreSQL billing verification was not run",
        )

    database_url = normalize_postgres_url(raw_url)
    schema_name = f"billing_test_{uuid4().hex}"
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


@pytest.mark.integration
def test_billing_repository_postgresql_row_locks_and_idempotency(
    postgres_billing_engine,
):
    repo = BillingRepository(postgres_billing_engine)

    ensure_barrier = Barrier(2)

    def ensure_wallet():
        ensure_barrier.wait()
        return repo.ensure_wallet("user", "postgres-race")

    with ThreadPoolExecutor(max_workers=2) as pool:
        wallets = list(pool.map(lambda _index: ensure_wallet(), range(2)))
    assert len({wallet["id"] for wallet in wallets}) == 1
    wallet_id = wallets[0]["id"]

    grant_barrier = Barrier(2)

    def duplicate_grant() -> str:
        grant_barrier.wait()
        try:
            repo.grant(
                wallet_id,
                credits=5,
                credit_type="purchased",
                expires_at=None,
                idempotency_key="postgres-duplicate-grant",
            )
            return "committed"
        except DuplicateLedgerTransactionError:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=2) as pool:
        grant_results = list(
            pool.map(lambda _index: duplicate_grant(), range(2)),
        )
    assert sorted(grant_results) == ["committed", "duplicate"]
    assert repo.balance(wallet_id) == WalletBalance(5, 0, 5, 0, 0)

    repo.grant(
        wallet_id,
        credits=5,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="postgres-second-grant",
    )
    hold_barrier = Barrier(2)

    def competing_hold(index: int) -> str:
        hold_barrier.wait()
        try:
            repo.hold(
                wallet_id,
                credits=7,
                business_key=f"postgres-job-{index}",
                idempotency_key=f"postgres-hold-{index}",
            )
            return "committed"
        except InsufficientCreditsError:
            return "insufficient"

    with ThreadPoolExecutor(max_workers=2) as pool:
        hold_results = list(pool.map(competing_hold, range(2)))
    assert sorted(hold_results) == ["committed", "insufficient"]
    assert repo.balance(wallet_id) == WalletBalance(3, 7, 10, 0, 0)
