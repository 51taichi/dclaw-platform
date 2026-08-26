# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, func, insert, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from qwenpaw.app.billing.models import (
    BillingInvariantError,
    DuplicateLedgerTransactionError,
    InsufficientCreditsError,
    LedgerTransaction,
    WalletBalance,
)
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.schema import (
    billing_credit_lots,
    billing_ledger_allocations,
    billing_ledger_entries,
    billing_wallets,
    create_all,
)
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


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


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


def test_expired_lot_is_removed_from_available_projection(engine):
    clock = MutableClock(datetime(2026, 8, 26, tzinfo=timezone.utc))
    repo = BillingRepository(engine, clock=clock)
    wallet = repo.ensure_wallet("user", "expiry")
    repo.grant(
        wallet["id"],
        credits=10,
        credit_type="promotional",
        expires_at=clock.now + timedelta(days=1),
        idempotency_key="trial",
    )

    clock.now += timedelta(days=2)

    assert repo.balance(wallet["id"]) == WalletBalance(0, 0, 0, 0, 0)
    entries = repo.list_ledger(wallet["id"], 10, None)
    assert [(row["event_type"], row["credit_delta"]) for row in entries] == [
        ("credit_expiry", -10),
        ("promotion_grant", 10),
    ]
    with engine.connect() as conn:
        lot = conn.execute(select(billing_credit_lots)).mappings().one()
    assert (lot["status"], lot["available_credits"], lot["held_credits"]) == (
        "expired",
        0,
        0,
    )


def test_release_after_expiry_does_not_restore_expired_credits(engine):
    clock = MutableClock(datetime(2026, 8, 26, tzinfo=timezone.utc))
    repo = BillingRepository(engine, clock=clock)
    wallet = repo.ensure_wallet("user", "release-expiry")
    repo.grant(
        wallet["id"],
        credits=10,
        credit_type="promotional",
        expires_at=clock.now + timedelta(days=1),
        idempotency_key="trial",
    )
    repo.hold(
        wallet["id"],
        credits=10,
        business_key="job-expired",
        idempotency_key="hold-expired",
    )
    hold = next(
        row
        for row in repo.list_ledger(wallet["id"], 10, None)
        if row["event_type"] == "usage_hold"
    )

    clock.now += timedelta(days=2)
    balance = repo.release(
        wallet["id"],
        business_key="job-expired",
        idempotency_key="release-expired",
    )

    assert balance == WalletBalance(0, 0, 0, 0, 0)
    release = next(
        row
        for row in repo.list_ledger(wallet["id"], 10, None)
        if row["event_type"] == "usage_release"
    )
    assert release["metadata"]["source_ledger_entry_id"] == hold["id"]
    with engine.connect() as conn:
        lot = conn.execute(select(billing_credit_lots)).mappings().one()
    assert (lot["status"], lot["available_credits"], lot["held_credits"]) == (
        "expired",
        0,
        0,
    )


def test_duplicate_hold_business_key_is_rejected_before_allocation(repo):
    wallet = repo.ensure_wallet("user", "duplicate-business")
    repo.grant(
        wallet["id"],
        credits=20,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="purchase",
    )
    repo.hold(
        wallet["id"],
        credits=5,
        business_key="job-1",
        idempotency_key="hold-1",
    )

    with pytest.raises(BillingInvariantError, match="hold already exists"):
        repo.hold(
            wallet["id"],
            credits=5,
            business_key="job-1",
            idempotency_key="hold-2",
        )

    assert repo.balance(wallet["id"]) == WalletBalance(15, 5, 20, 0, 0)
    repo.release(
        wallet["id"],
        business_key="job-1",
        idempotency_key="release-1",
    )
    assert repo.balance(wallet["id"]) == WalletBalance(20, 0, 20, 0, 0)


def test_equal_expiry_prefers_promotional_then_package_then_permanent(repo):
    wallet = repo.ensure_wallet("user", "priority")
    same_expiry = _future(10)
    repo.grant(
        wallet["id"],
        credits=5,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="permanent",
    )
    repo.grant(
        wallet["id"],
        credits=5,
        credit_type="package",
        expires_at=same_expiry,
        idempotency_key="package",
    )
    repo.grant(
        wallet["id"],
        credits=5,
        credit_type="promotional",
        expires_at=same_expiry,
        idempotency_key="promotional",
    )

    repo.hold(
        wallet["id"],
        credits=12,
        business_key="job-priority",
        idempotency_key="hold-priority",
    )

    assert repo.allocations("job-priority") == [
        ("promotional", 5),
        ("package", 5),
        ("permanent", 2),
    ]


def test_projection_invariant_compares_cached_wallet_with_lots(engine, repo):
    wallet = repo.ensure_wallet("user", "projection-drift")
    repo.grant(
        wallet["id"],
        credits=10,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="purchase",
    )
    with engine.begin() as conn:
        conn.execute(
            update(billing_wallets)
            .where(billing_wallets.c.id == wallet["id"])
            .values(available_credits=11, purchased_credits=11),
        )

    with pytest.raises(BillingInvariantError, match="credit lot projections"):
        repo.hold(
            wallet["id"],
            credits=1,
            business_key="job-drift",
            idempotency_key="hold-drift",
        )

    assert all(
        row["idempotency_key"] != "hold-drift"
        for row in repo.list_ledger(wallet["id"], 10, None)
    )


def test_zero_row_guarded_wallet_update_rolls_back(engine, repo):
    wallet = repo.ensure_wallet("user", "rowcount")
    repo.grant(
        wallet["id"],
        credits=10,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="purchase",
    )
    changed = False

    def empty_wallet_after_lot_update(
        _conn,
        cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        nonlocal changed
        normalized = statement.lstrip().upper()
        if not changed and normalized.startswith("UPDATE BILLING_CREDIT_LOTS"):
            changed = True
            cursor.execute(
                "UPDATE billing_wallets "
                "SET available_credits = 0 WHERE id = ?",
                (wallet["id"],),
            )

    event.listen(engine, "after_cursor_execute", empty_wallet_after_lot_update)
    try:
        with pytest.raises(
            BillingInvariantError,
            match="wallet changed during hold",
        ):
            repo.hold(
                wallet["id"],
                credits=5,
                business_key="job-rowcount",
                idempotency_key="hold-rowcount",
            )
    finally:
        event.remove(
            engine,
            "after_cursor_execute",
            empty_wallet_after_lot_update,
        )

    assert changed is True
    assert repo.balance(wallet["id"]) == WalletBalance(10, 0, 10, 0, 0)


def test_failure_after_ledger_allocation_and_lot_writes_rolls_back(
    engine,
    repo,
):
    wallet = repo.ensure_wallet("user", "rollback")
    repo.grant(
        wallet["id"],
        credits=10,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="purchase",
    )

    def fail_wallet_update(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        if statement.lstrip().upper().startswith("UPDATE BILLING_WALLETS"):
            raise RuntimeError("injected failure after lot writes")

    event.listen(engine, "before_cursor_execute", fail_wallet_update)
    try:
        with pytest.raises(RuntimeError, match="injected failure"):
            repo.hold(
                wallet["id"],
                credits=5,
                business_key="job-rollback",
                idempotency_key="hold-rollback",
            )
    finally:
        event.remove(engine, "before_cursor_execute", fail_wallet_update)

    with engine.connect() as conn:
        lot = conn.execute(select(billing_credit_lots)).mappings().one()
        ledger_count = conn.scalar(
            select(func.count()).select_from(billing_ledger_entries),
        )
        allocation_count = conn.scalar(
            select(func.count()).select_from(billing_ledger_allocations),
        )
    assert (lot["available_credits"], lot["held_credits"]) == (10, 0)
    assert (ledger_count, allocation_count) == (1, 0)
    assert repo.balance(wallet["id"]) == WalletBalance(10, 0, 10, 0, 0)


def test_postgresql_lock_statements_compile_with_for_update():
    wallet_sql = str(
        BillingRepository._wallet_for_update_statement("wallet-1").compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        ),
    )
    lots_sql = str(
        BillingRepository._available_lots_for_update_statement(
            "wallet-1",
            10,
            datetime(2026, 8, 26, tzinfo=timezone.utc),
        ).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        ),
    )

    assert wallet_sql.rstrip().endswith("FOR UPDATE")
    assert lots_sql.rstrip().endswith("FOR UPDATE")


def test_partial_capture_consumes_original_lots_and_releases_remainder(
    engine,
):
    clock = MutableClock(datetime(2026, 8, 26, tzinfo=timezone.utc))
    repo = BillingRepository(engine, clock=clock)
    wallet = repo.ensure_wallet("user", "partial")
    repo.grant(
        wallet["id"],
        credits=40,
        credit_type="promotional",
        expires_at=clock.now + timedelta(days=1),
        idempotency_key="promo-soon",
    )
    repo.grant(
        wallet["id"],
        credits=30,
        credit_type="package",
        expires_at=clock.now + timedelta(days=2),
        idempotency_key="package-later",
    )
    repo.grant(
        wallet["id"],
        credits=50,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="purchased",
    )
    repo.hold(
        wallet["id"],
        credits=100,
        business_key="partial-job",
        idempotency_key="partial-hold",
        capability="text_to_image",
        tier="standard",
    )

    clock.now += timedelta(hours=36)
    balance = repo.capture(
        wallet["id"],
        credits=60,
        business_key="partial-job",
        idempotency_key="partial-capture",
    )

    assert balance == WalletBalance(60, 0, 50, 0, 10)
    entries = repo.list_ledger(wallet["id"], 20, None)
    capture = next(
        row for row in entries if row["event_type"] == "usage_capture"
    )
    release = next(
        row for row in entries if row["event_type"] == "usage_release"
    )
    with engine.connect() as conn:
        source_by_lot = {
            row.id: row.idempotency_key
            for row in conn.execute(
                select(
                    billing_credit_lots.c.id,
                    billing_ledger_entries.c.idempotency_key,
                ).select_from(
                    billing_credit_lots.join(
                        billing_ledger_entries,
                        billing_credit_lots.c.source_ledger_entry_id
                        == billing_ledger_entries.c.id,
                    ),
                ),
            )
        }
    with engine.connect() as conn:
        captured_allocations = {
            source_by_lot[row.credit_lot_id]: int(row.credits)
            for row in conn.execute(
                select(
                    billing_ledger_allocations.c.credit_lot_id,
                    billing_ledger_allocations.c.credits,
                ).where(
                    billing_ledger_allocations.c.ledger_entry_id
                    == capture["id"],
                ),
            )
        }
        released_allocations = {
            source_by_lot[row.credit_lot_id]: int(row.credits)
            for row in conn.execute(
                select(
                    billing_ledger_allocations.c.credit_lot_id,
                    billing_ledger_allocations.c.credits,
                ).where(
                    billing_ledger_allocations.c.ledger_entry_id
                    == release["id"],
                ),
            )
        }
    assert captured_allocations == {"promo-soon": 40, "package-later": 20}
    assert released_allocations == {"package-later": 10, "purchased": 30}


@pytest.mark.parametrize(
    ("capability", "tier"),
    [
        ("text_to_video", "standard"),
        ("text_to_image", "high_cost"),
        ("fixed_workflow", "standard"),
    ],
)
def test_restricted_trial_lot_is_skipped_for_ineligible_usage(
    repo,
    capability,
    tier,
):
    wallet = repo.ensure_wallet("user", f"trial-{capability}-{tier}")
    repo.append_transaction(
        LedgerTransaction(
            wallet_id=wallet["id"],
            event_type="promotion_grant",
            credits=100,
            business_type="signup_trial",
            business_key=f"trial-{capability}-{tier}",
            idempotency_key=f"trial-{capability}-{tier}",
            credit_type="promotional",
            expires_at=_future(7),
            metadata={
                "grant_policy": "signup_trial",
                "allowed_capabilities": ["text", "image"],
                "denied_capabilities": [
                    "video",
                    "high_cost",
                    "fixed_workflow",
                ],
                "allowed_tiers": ["standard"],
            },
        ),
    )
    repo.grant(
        wallet["id"],
        credits=60,
        credit_type="purchased",
        expires_at=None,
        idempotency_key=f"purchase-{capability}-{tier}",
    )

    repo.hold(
        wallet["id"],
        credits=50,
        business_key=f"job-{capability}-{tier}",
        idempotency_key=f"hold-{capability}-{tier}",
        capability=capability,
        tier=tier,
    )

    assert repo.allocations(f"job-{capability}-{tier}") == [
        (f"purchase-{capability}-{tier}", 50),
    ]


def test_standard_image_usage_can_consume_the_signup_trial_lot(repo):
    wallet = repo.ensure_wallet("user", "trial-standard-image")
    repo.append_transaction(
        LedgerTransaction(
            wallet_id=wallet["id"],
            event_type="promotion_grant",
            credits=100,
            business_type="signup_trial",
            business_key="trial-standard-image",
            idempotency_key="trial-standard-image",
            credit_type="promotional",
            expires_at=_future(7),
            metadata={
                "grant_policy": "signup_trial",
                "allowed_capabilities": ["text", "image"],
                "denied_capabilities": [
                    "video",
                    "high_cost",
                    "fixed_workflow",
                ],
                "allowed_tiers": ["standard"],
            },
        ),
    )

    repo.hold(
        wallet["id"],
        credits=50,
        business_key="standard-image-job",
        idempotency_key="standard-image-hold",
        capability="text_to_image",
        tier="standard",
    )

    assert repo.allocations("standard-image-job") == [
        ("trial-standard-image", 50),
    ]


def test_restricted_trial_lot_fails_closed_without_usage_classification(repo):
    wallet = repo.ensure_wallet("user", "trial-missing-classification")
    repo.append_transaction(
        LedgerTransaction(
            wallet_id=wallet["id"],
            event_type="promotion_grant",
            credits=100,
            business_type="signup_trial",
            business_key="trial-missing-classification",
            idempotency_key="trial-missing-classification",
            credit_type="promotional",
            expires_at=_future(7),
            metadata={
                "grant_policy": "signup_trial",
                "allowed_capabilities": ["text", "image"],
                "allowed_tiers": ["standard"],
            },
        ),
    )

    with pytest.raises(InsufficientCreditsError):
        repo.hold(
            wallet["id"],
            credits=10,
            business_key="unclassified-job",
            idempotency_key="unclassified-hold",
        )


def test_purchased_grant_rejects_expiry_in_repository_and_database(
    repo,
    engine,
):
    wallet = repo.ensure_wallet("user", "purchased-expiry")

    with pytest.raises(ValueError, match="purchased credits cannot expire"):
        repo.grant(
            wallet["id"],
            credits=10,
            credit_type="purchased",
            expires_at=_future(1),
            idempotency_key="invalid-purchase",
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                insert(billing_credit_lots).values(
                    id="invalid-purchased-lot",
                    wallet_id=wallet["id"],
                    credit_type="purchased",
                    status="active",
                    granted_credits=10,
                    available_credits=10,
                    held_credits=0,
                    expires_at=_future(1),
                    metadata_json="{}",
                ),
            )
