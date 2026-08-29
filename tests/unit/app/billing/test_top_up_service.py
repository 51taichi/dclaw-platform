# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.app.billing.top_up import (
    ReviewCommand,
    SubmitClaimCommand,
    TopUpConflictError,
    TopUpService,
)
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.top_up_repo import TopUpRepository
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture
def service(tmp_path):
    engine = create_engine_from_settings(
        get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "service.db")}),
    )
    create_all(engine)
    billing = BillingRepository(engine)
    billing.ensure_wallet("user", "user-1")
    top_up = TopUpRepository(engine)
    product = top_up.create_product(
        {
            "name": "1000 + 100 credits",
            "payment_amount_fen": 1000,
            "purchased_credits": 1000,
            "promotional_credits": 100,
            "promotional_expiry_days": 30,
            "status": "active",
            "display_order": 1,
            "created_by": "admin-1",
        },
    )
    instance = TopUpService(top_up, billing)
    try:
        yield instance, top_up, billing, product
    finally:
        engine.dispose()


def _submit(service, product, *, key="claim-1"):
    return service.submit_claim(
        "user-1",
        SubmitClaimCommand(
            product_id=str(product["public_id"]),
            payment_channel="wechat",
            payer_reference="tail-1234",
            customer_note="paid",
            idempotency_key=key,
        ),
    )


def test_approval_uses_snapshot_and_grants_once(service):
    instance, repo, billing, product = service
    claim = _submit(instance, product)
    repo.replace_product(
        str(product["public_id"]),
        {
            "name": "changed",
            "payment_amount_fen": 9000,
            "purchased_credits": 9000,
            "promotional_credits": 0,
            "promotional_expiry_days": None,
            "status": "active",
            "display_order": 1,
            "created_by": "admin-1",
        },
    )
    command = ReviewCommand(
        idempotency_key="approve-1",
        reason="receipt verified",
    )
    first = instance.approve_claim(claim["public_id"], "admin-1", command)
    replay = instance.approve_claim(claim["public_id"], "admin-1", command)

    assert replay == first
    assert billing.balance(first["wallet_id"]).available == 1100
    lots = billing.list_lots(first["wallet_id"])
    purchased = next(row for row in lots if row["credit_type"] == "purchased")
    promotional = next(row for row in lots if row["credit_type"] == "promotional")
    assert purchased["expires_at"] is None
    assert promotional["expires_at"] is not None
    assert len(repo.list_audits(first["id"])) == 2


def test_rejection_has_no_financial_effect_and_requires_exact_replay(service):
    instance, _repo, billing, product = service
    claim = _submit(instance, product)
    command = ReviewCommand(idempotency_key="reject-1", reason="receipt mismatch")
    rejected = instance.reject_claim(claim["public_id"], "admin-2", command)
    replay = instance.reject_claim(claim["public_id"], "admin-2", command)
    assert replay == rejected
    assert billing.balance(rejected["wallet_id"]).available == 0

    with pytest.raises(TopUpConflictError):
        instance.approve_claim(
            claim["public_id"],
            "admin-2",
            ReviewCommand(idempotency_key="approve-late", reason="changed mind"),
        )


def test_review_idempotency_drift_conflicts(service):
    instance, _repo, _billing, product = service
    claim = _submit(instance, product)
    instance.approve_claim(
        claim["public_id"],
        "admin-1",
        ReviewCommand(idempotency_key="review-key", reason="verified"),
    )
    with pytest.raises(TopUpConflictError):
        instance.approve_claim(
            claim["public_id"],
            "admin-1",
            ReviewCommand(idempotency_key="review-key", reason="different"),
        )
