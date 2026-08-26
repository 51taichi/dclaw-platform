# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from qwenpaw.app.billing.models import (
    DuplicateLedgerTransactionError,
    InsufficientCreditsError,
    LedgerTransaction,
    WalletBalance,
)
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def engine(tmp_path):
    settings = get_storage_settings(
        {"QWENPAW_SQLITE_PATH": str(tmp_path / "billing.db")},
    )
    engine = create_engine_from_settings(settings)
    create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def repo(engine):
    return BillingRepository(engine)


def _future(days: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def test_ensure_wallet_is_idempotent(repo):
    first = repo.ensure_wallet("user", "18")
    second = repo.ensure_wallet("user", "18")

    assert second == first
    assert repo.balance(first["id"]) == WalletBalance(0, 0, 0, 0, 0)


def test_duplicate_ledger_idempotency_key_is_rejected_without_changing_balance(
    repo,
):
    wallet = repo.ensure_wallet("user", "18")
    repo.grant(
        wallet["id"],
        credits=25,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="purchase-1",
    )

    with pytest.raises(DuplicateLedgerTransactionError):
        repo.grant(
            wallet["id"],
            credits=25,
            credit_type="purchased",
            expires_at=None,
            idempotency_key="purchase-1",
        )

    assert repo.balance(wallet["id"]) == WalletBalance(25, 0, 25, 0, 0)
    assert [
        row["idempotency_key"]
        for row in repo.list_ledger(wallet["id"], 10, None)
    ] == ["purchase-1"]


def test_debit_uses_earliest_expiring_lot_first(repo):
    wallet = repo.ensure_wallet("user", "18")
    repo.grant(
        wallet["id"],
        credits=20,
        credit_type="promotional",
        expires_at=_future(10),
        idempotency_key="later",
    )
    repo.grant(
        wallet["id"],
        credits=10,
        credit_type="promotional",
        expires_at=_future(1),
        idempotency_key="soon",
    )

    repo.hold(
        wallet["id"],
        credits=15,
        business_key="job-1",
        idempotency_key="hold-1",
    )

    assert repo.allocations("job-1") == [("soon", 10), ("later", 5)]


def test_debit_uses_promotional_before_purchased_when_expiry_is_equal(repo):
    wallet = repo.ensure_wallet("user", "18")
    repo.grant(
        wallet["id"],
        credits=100,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="purchased",
    )
    repo.grant(
        wallet["id"],
        credits=30,
        credit_type="promotional",
        expires_at=None,
        idempotency_key="promotional",
    )

    repo.hold(
        wallet["id"],
        credits=40,
        business_key="job-1",
        idempotency_key="hold-1",
    )

    assert repo.allocations("job-1") == [
        ("promotional", 30),
        ("purchased", 10),
    ]


def test_release_restores_the_exact_source_lots(repo):
    wallet = repo.ensure_wallet("user", "18")
    repo.grant(
        wallet["id"],
        credits=12,
        credit_type="promotional",
        expires_at=_future(1),
        idempotency_key="soon",
    )
    repo.grant(
        wallet["id"],
        credits=20,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="purchased",
    )
    original = repo.balance(wallet["id"])
    repo.hold(
        wallet["id"],
        credits=17,
        business_key="job-1",
        idempotency_key="hold-1",
    )

    released = repo.release(
        wallet["id"],
        business_key="job-1",
        idempotency_key="release-1",
    )

    assert released == original
    repo.hold(
        wallet["id"],
        credits=17,
        business_key="job-2",
        idempotency_key="hold-2",
    )
    assert repo.allocations("job-2") == [("soon", 12), ("purchased", 5)]


def test_negative_available_balance_is_rejected_atomically(repo):
    wallet = repo.ensure_wallet("user", "18")
    repo.grant(
        wallet["id"],
        credits=10,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="purchase-1",
    )

    with pytest.raises(InsufficientCreditsError):
        repo.hold(
            wallet["id"],
            credits=11,
            business_key="job-1",
            idempotency_key="hold-1",
        )

    assert repo.balance(wallet["id"]) == WalletBalance(10, 0, 10, 0, 0)
    assert [
        row["idempotency_key"]
        for row in repo.list_ledger(wallet["id"], 10, None)
    ] == ["purchase-1"]


def test_append_transaction_returns_typed_balance(repo):
    wallet = repo.ensure_wallet("user", "18")

    balance = repo.append_transaction(
        LedgerTransaction(
            wallet_id=wallet["id"],
            event_type="promotion_grant",
            credits=7,
            business_type="grant",
            business_key="trial-18",
            idempotency_key="trial-18",
            credit_type="promotional",
            expires_at=_future(7),
        ),
    )

    assert balance == WalletBalance(7, 0, 0, 7, 0)


def test_list_ledger_uses_an_exclusive_cursor(repo):
    wallet = repo.ensure_wallet("user", "18")
    for index in range(3):
        repo.grant(
            wallet["id"],
            credits=index + 1,
            credit_type="purchased",
            expires_at=None,
            idempotency_key=f"purchase-{index}",
        )

    first_page = repo.list_ledger(wallet["id"], 2, None)
    second_page = repo.list_ledger(wallet["id"], 2, first_page[-1]["id"])

    assert len(first_page) == 2
    assert len(second_page) == 1
    assert {row["idempotency_key"] for row in first_page + second_page} == {
        "purchase-0",
        "purchase-1",
        "purchase-2",
    }
