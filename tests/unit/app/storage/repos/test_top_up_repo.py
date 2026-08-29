# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.top_up_repo import (
    TopUpIdempotencyConflict,
    TopUpRepository,
)


@pytest.fixture
def repo(tmp_path):
    engine = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "top-up.db")},
        ),
    )
    create_all(engine)
    BillingRepository(engine).ensure_wallet("user", "user-1")
    BillingRepository(engine).ensure_wallet("user", "user-2")
    try:
        yield TopUpRepository(engine)
    finally:
        engine.dispose()


def _product(**overrides):
    values = {
        "name": "1000 credits",
        "description": "permanent purchased credits",
        "payment_amount_fen": 1000,
        "purchased_credits": 1000,
        "promotional_credits": 100,
        "promotional_expiry_days": 30,
        "status": "active",
        "display_order": 10,
        "created_by": "admin-1",
    }
    values.update(overrides)
    return values


def _claim(repo, product, *, owner_id="user-1", key="submit-1"):
    wallet = BillingRepository(repo.engine).get_wallet("user", owner_id)
    assert wallet is not None
    return repo.create_claim(
        owner_id=owner_id,
        wallet_id=str(wallet["id"]),
        product_public_id=str(product["public_id"]),
        payment_channel="wechat",
        payer_reference="tail-1234",
        customer_note="paid",
        idempotency_key=key,
    )


def test_claim_keeps_product_snapshot_after_product_replacement(repo):
    product = repo.create_product(_product())
    claim = _claim(repo, product)

    replacement = repo.replace_product(
        str(product["public_id"]),
        _product(payment_amount_fen=5000, purchased_credits=6000),
    )
    stored = repo.get_claim_by_public_id(str(claim["public_id"]))

    assert replacement["public_id"] == product["public_id"]
    assert stored is not None
    assert stored["product_snapshot"]["payment_amount_fen"] == 1000
    assert stored["product_snapshot"]["purchased_credits"] == 1000


def test_claim_replay_is_exact_and_drift_conflicts(repo):
    product = repo.create_product(_product())
    first = _claim(repo, product)
    replay = _claim(repo, product)
    assert replay == first

    with pytest.raises(TopUpIdempotencyConflict):
        _claim(repo, product, key="submit-1", owner_id="user-2")


def test_customer_claim_lookup_is_owner_scoped(repo):
    product = repo.create_product(_product())
    claim = _claim(repo, product)

    assert (
        repo.get_claim_by_public_id(
            str(claim["public_id"]),
            owner_id="user-1",
        )
        is not None
    )
    assert (
        repo.get_claim_by_public_id(
            str(claim["public_id"]),
            owner_id="user-2",
        )
        is None
    )
    assert [row["public_id"] for row in repo.list_claims(owner_id="user-1")] == [
        claim["public_id"],
    ]
    assert repo.list_claims(owner_id="user-2") == []


def test_products_use_opaque_public_ids_and_filter_disabled(repo):
    active = repo.create_product(_product())
    disabled = repo.create_product(_product(name="disabled", status="disabled"))

    assert active["public_id"] != active["id"]
    assert disabled["public_id"] != disabled["id"]
    assert [row["public_id"] for row in repo.list_products(active_only=True)] == [
        active["public_id"],
    ]
