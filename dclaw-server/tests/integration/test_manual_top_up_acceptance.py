# -*- coding: utf-8 -*-
"""End-to-end acceptance for the fixed-QR manual top-up workflow."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from qwenpaw.app import auth as app_auth
from qwenpaw.app.billing.top_up import TopUpService
from qwenpaw.app.guards import require_admin, require_user
from qwenpaw.app.routers import billing
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.top_up_repo import TopUpRepository
from qwenpaw.app.storage.schema import billing_ledger_entries, create_all
from qwenpaw.app.storage.settings import get_storage_settings


def test_manual_top_up_acceptance_is_owner_scoped_and_grants_once(
    tmp_path,
    monkeypatch,
):
    engine = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "acceptance.db")},
        ),
    )
    create_all(engine)
    wallet_repo = BillingRepository(engine)
    alice_wallet = wallet_repo.ensure_wallet("user", "alice")
    wallet_repo.ensure_wallet("user", "bob")
    top_up_repo = TopUpRepository(engine)
    product = top_up_repo.create_product(
        {
            "name": "CNY 10",
            "payment_amount_fen": 1000,
            "purchased_credits": 1000,
            "promotional_credits": 0,
            "promotional_expiry_days": None,
            "status": "active",
            "display_order": 1,
            "created_by": "admin",
        },
    )
    service = TopUpService(top_up_repo, wallet_repo)
    monkeypatch.setattr(app_auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(billing, "get_top_up_service", lambda: service)
    monkeypatch.setattr(
        billing,
        "get_billing_repository",
        lambda: wallet_repo,
    )
    app = FastAPI()

    @app.middleware("http")
    async def auth_context(request, call_next):
        request.state.user_id = request.headers.get("x-test-user")
        request.state.role = request.headers.get("x-test-role", "user")
        return await call_next(request)

    app.include_router(
        billing.user_router,
        prefix="/api/user",
        dependencies=[Depends(require_user)],
    )
    app.include_router(
        billing.admin_router,
        prefix="/api/admin",
        dependencies=[Depends(require_admin)],
    )
    client = TestClient(app)
    user_headers = {"x-test-user": "alice", "Idempotency-Key": "claim-1"}

    submitted = client.post(
        "/api/user/billing/top-up/claims",
        headers=user_headers,
        json={
            "product_id": product["public_id"],
            "payment_channel": "wechat",
            "payer_reference": "tail-1234",
        },
    )
    assert submitted.status_code == 200
    claim_id = submitted.json()["public_id"]
    approval_headers = {
        "x-test-user": "admin-1",
        "x-test-role": "admin",
        "Idempotency-Key": "approve-1",
    }
    first = client.post(
        f"/api/admin/billing/top-up/claims/{claim_id}/approve",
        headers=approval_headers,
        json={"reason": "receipt verified"},
    )
    replay = client.post(
        f"/api/admin/billing/top-up/claims/{claim_id}/approve",
        headers=approval_headers,
        json={"reason": "receipt verified"},
    )
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()

    wallet = client.get(
        "/api/user/billing/wallet",
        headers={"x-test-user": "alice"},
    )
    ledger = client.get(
        "/api/user/billing/ledger",
        headers={"x-test-user": "alice"},
    )
    foreign = client.get(
        "/api/user/billing/top-up/claims",
        headers={"x-test-user": "bob"},
    )
    assert wallet.json()["available"] == 1000
    assert [item["event_type"] for item in ledger.json()["items"]] == [
        "purchase_grant",
    ]
    assert foreign.json()["items"] == []
    with engine.connect() as connection:
        assert (
            connection.scalar(
                select(func.count())
                .select_from(billing_ledger_entries)
                .where(
                    billing_ledger_entries.c.wallet_id == alice_wallet["id"],
                ),
            )
            == 1
        )
    engine.dispose()
