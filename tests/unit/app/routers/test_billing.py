# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from qwenpaw.app.billing.models import WalletBalance
from qwenpaw.app.billing.pricing import (
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
    QuoteRequest,
)
from qwenpaw.app.billing.usage import UsageService
from qwenpaw.app import auth as app_auth
from qwenpaw.app.guards import require_admin, require_user
from qwenpaw.app.routers import billing
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.schema import (
    billing_usage_orders,
    create_all,
)
from qwenpaw.app.storage.settings import get_storage_settings


NOW = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def engine(tmp_path):
    settings = get_storage_settings(
        {"QWENPAW_SQLITE_PATH": str(tmp_path / "billing-api.db")},
    )
    engine = create_engine_from_settings(settings)
    create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def wallet_repo(engine):
    return BillingRepository(engine, clock=lambda: NOW)


@pytest.fixture
def catalog_repo(engine):
    return PriceCatalogRepository(engine)


@pytest.fixture
def pricing(catalog_repo):
    return PriceCatalogService(catalog_repo, clock=lambda: NOW)


def _publish_catalog(pricing: PriceCatalogService, version: str = "retail-v1"):
    pricing.publish(
        PriceCatalogDraft(
            version=version,
            effective_at=NOW,
            created_by="admin:1",
            rules=(
                PriceRule(
                    id=f"{version}-image",
                    provider_id="aliyun",
                    model_key="wan-2.7",
                    capability="text_to_image",
                    unit_type="image_count",
                    credits_per_unit=50,
                ),
            ),
        ),
    )


def _app(
    monkeypatch,
    usage: UsageService,
    wallet_repo: BillingRepository,
    pricing: PriceCatalogService,
) -> FastAPI:
    monkeypatch.setattr(app_auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(billing, "get_usage_service", lambda: usage)
    monkeypatch.setattr(billing, "get_billing_repository", lambda: wallet_repo)
    monkeypatch.setattr(billing, "get_price_catalog_service", lambda: pricing)

    app = FastAPI()

    @app.middleware("http")
    async def trusted_auth_context(request, call_next):
        user_id = request.headers.get("x-test-user")
        if user_id:
            request.state.user_id = user_id
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
    return app


def _quote_payload(business_key: str = "job-1") -> dict:
    return {
        "business_key": business_key,
        "provider_id": "aliyun",
        "model_key": "wan-2.7",
        "capability": "text_to_image",
        "parameters": {"count": 2},
    }


def _headers(user_id: str, role: str = "user") -> dict[str, str]:
    return {"x-test-user": user_id, "x-test-role": role}


def test_billing_mode_defaults_to_shadow(monkeypatch, wallet_repo, pricing):
    monkeypatch.delenv("DCLAW_BILLING_MODE", raising=False)

    service = UsageService(wallet_repo, pricing)

    assert service.mode == "shadow"


def test_user_wallet_and_ledger_are_resolved_only_from_auth_context(
    monkeypatch,
    engine,
    wallet_repo,
    pricing,
):
    alice = wallet_repo.ensure_wallet("user", "alice")
    bob = wallet_repo.ensure_wallet("user", "bob")
    wallet_repo.grant(
        alice["id"],
        credits=80,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="alice-purchase",
    )
    wallet_repo.grant(
        bob["id"],
        credits=25,
        credit_type="promotional",
        expires_at=None,
        idempotency_key="bob-grant",
    )
    usage = UsageService(wallet_repo, pricing, mode="shadow")
    client = TestClient(_app(monkeypatch, usage, wallet_repo, pricing))

    wallet = client.get(
        "/api/user/billing/wallet",
        headers=_headers("alice"),
    )
    ledger = client.get(
        "/api/user/billing/ledger",
        headers=_headers("alice"),
    )

    assert wallet.status_code == 200
    assert wallet.json() == {
        "available": 80,
        "held": 0,
        "purchased": 80,
        "promotional": 0,
        "package": 0,
    }
    assert [item["idempotency_key"] for item in ledger.json()["items"]] == [
        "alice-purchase",
    ]
    assert "alice" not in wallet.text
    assert bob["id"] not in wallet.text

    injected = _quote_payload("job-injected") | {
        "wallet_id": bob["id"],
        "credits": 1,
        "price": 1,
    }
    rejected = client.post(
        "/api/user/billing/quotes",
        json=injected,
        headers=_headers("alice"),
    )
    assert rejected.status_code == 422
    with engine.connect() as conn:
        assert (
            conn.scalar(select(func.count()).select_from(billing_usage_orders))
            == 0
        )


def test_shadow_quote_uses_published_snapshot_and_never_moves_balance(
    monkeypatch,
    engine,
    wallet_repo,
    pricing,
):
    _publish_catalog(pricing)
    wallet = wallet_repo.ensure_wallet("user", "alice")
    wallet_repo.grant(
        wallet["id"],
        credits=10,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="purchase",
    )
    before = wallet_repo.balance(wallet["id"])
    usage = UsageService(wallet_repo, pricing, mode="shadow")
    client = TestClient(_app(monkeypatch, usage, wallet_repo, pricing))

    response = client.post(
        "/api/user/billing/quotes",
        json=_quote_payload(),
        headers=_headers("alice"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["billing_mode"] == "shadow"
    assert body["status"] == "held"
    assert body["quote"]["credits"] == 100
    assert body["quote"]["catalog_version"] == "retail-v1"
    assert body["quote"]["snapshot"]["rule"] == {
        "id": "retail-v1-image",
        "provider_id": "aliyun",
        "model_key": "wan-2.7",
        "capability": "text_to_image",
        "unit_type": "image_count",
        "priority": 0,
        "unit_size": 1,
        "credits_per_unit": 50,
        "input_credits_per_1k": 0,
        "output_credits_per_1k": 0,
        "parameter_match": {},
    }
    assert wallet_repo.balance(wallet["id"]) == before
    assert [
        row["event_type"]
        for row in wallet_repo.list_ledger(wallet["id"], 10, None)
    ] == ["purchase_grant"]
    with engine.connect() as conn:
        order = conn.execute(select(billing_usage_orders)).mappings().one()
    assert order["wallet_id"] == wallet["id"]
    assert order["status"] == "held"
    assert order["quoted_credits"] == 100
    assert order["held_credits"] == 100
    assert '"credits":100' in order["price_snapshot_json"]


def test_off_mode_quotes_without_recording_an_order(
    monkeypatch,
    engine,
    wallet_repo,
    pricing,
):
    _publish_catalog(pricing)
    usage = UsageService(wallet_repo, pricing, mode="off")
    client = TestClient(_app(monkeypatch, usage, wallet_repo, pricing))

    response = client.post(
        "/api/user/billing/quotes",
        json=_quote_payload(),
        headers=_headers("alice"),
    )

    assert response.status_code == 200
    assert response.json()["billing_mode"] == "off"
    assert response.json()["id"] is None
    assert response.json()["status"] == "off"
    with engine.connect() as conn:
        assert (
            conn.scalar(select(func.count()).select_from(billing_usage_orders))
            == 0
        )


def test_enforced_quote_returns_409_code_when_wallet_is_insufficient(
    monkeypatch,
    engine,
    wallet_repo,
    pricing,
):
    _publish_catalog(pricing)
    usage = UsageService(wallet_repo, pricing, mode="enforced")
    client = TestClient(_app(monkeypatch, usage, wallet_repo, pricing))

    response = client.post(
        "/api/user/billing/quotes",
        json=_quote_payload(),
        headers=_headers("alice"),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "insufficient_credits"
    assert response.json()["required_credits"] == 100
    assert response.json()["available_credits"] == 0
    with engine.connect() as conn:
        order = conn.execute(select(billing_usage_orders)).mappings().one()
    assert order["status"] == "quoted"
    assert order["held_credits"] == 0


def test_enforced_usage_state_machine_holds_captures_and_releases(
    wallet_repo,
    pricing,
):
    _publish_catalog(pricing)
    capture_wallet = wallet_repo.ensure_wallet("user", "capture-user")
    release_wallet = wallet_repo.ensure_wallet("user", "release-user")
    for label, wallet in (
        ("capture", capture_wallet),
        ("release", release_wallet),
    ):
        wallet_repo.grant(
            wallet["id"],
            credits=150,
            credit_type="purchased",
            expires_at=None,
            idempotency_key=f"{label}-purchase",
        )
    usage = UsageService(wallet_repo, pricing, mode="enforced")

    capture_order = usage.create_quote(
        "capture-user",
        QuoteRequest(
            "aliyun",
            "wan-2.7",
            "text_to_image",
            {"count": 2},
        ),
        business_key="capture-job",
    )
    held = usage.hold(capture_order["id"])
    reconciling = usage.mark_reconciling(capture_order["id"])
    captured = usage.capture(capture_order["id"])

    assert held["status"] == "held"
    assert reconciling["status"] == "reconciling"
    assert captured["status"] == "captured"
    assert wallet_repo.balance(capture_wallet["id"]) == WalletBalance(
        50,
        0,
        50,
        0,
        0,
    )
    entries = wallet_repo.list_ledger(capture_wallet["id"], 10, None)
    assert {row["event_type"] for row in entries} == {
        "purchase_grant",
        "usage_hold",
        "usage_capture",
    }
    hold_entry = next(
        row for row in entries if row["event_type"] == "usage_hold"
    )
    capture_entry = next(
        row for row in entries if row["event_type"] == "usage_capture"
    )
    assert (
        capture_entry["metadata"]["source_ledger_entry_id"] == hold_entry["id"]
    )

    release_order = usage.create_quote(
        "release-user",
        QuoteRequest(
            "aliyun",
            "wan-2.7",
            "text_to_image",
            {"count": 2},
        ),
        business_key="release-job",
    )
    usage.hold(release_order["id"])
    released = usage.release(release_order["id"])

    assert released["status"] == "released"
    assert wallet_repo.balance(release_wallet["id"]) == WalletBalance(
        150,
        0,
        150,
        0,
        0,
    )


def test_shadow_capture_records_theoretical_charge_without_wallet_ledger(
    wallet_repo,
    pricing,
):
    _publish_catalog(pricing)
    wallet = wallet_repo.ensure_wallet("user", "shadow-user")
    usage = UsageService(wallet_repo, pricing, mode="shadow")
    order = usage.create_quote(
        "shadow-user",
        QuoteRequest(
            "aliyun",
            "wan-2.7",
            "text_to_image",
            {"count": 2},
        ),
        business_key="shadow-job",
    )

    usage.hold(order["id"])
    captured = usage.capture(order["id"])

    assert captured["status"] == "captured"
    assert captured["captured_credits"] == 100
    assert wallet_repo.balance(wallet["id"]) == WalletBalance(0, 0, 0, 0, 0)
    assert wallet_repo.list_ledger(wallet["id"], 10, None) == []


def test_enforced_hold_rolls_back_wallet_when_order_transition_fails(
    engine,
    wallet_repo,
    pricing,
):
    _publish_catalog(pricing)
    wallet = wallet_repo.ensure_wallet("user", "atomic-user")
    wallet_repo.grant(
        wallet["id"],
        credits=150,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="atomic-purchase",
    )
    usage = UsageService(wallet_repo, pricing, mode="enforced")
    order = usage.create_quote(
        "atomic-user",
        QuoteRequest(
            "aliyun",
            "wan-2.7",
            "text_to_image",
            {"count": 2},
        ),
        business_key="atomic-job",
    )

    def fail_order_update(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        if (
            statement.lstrip()
            .upper()
            .startswith(
                "UPDATE BILLING_USAGE_ORDERS",
            )
        ):
            raise RuntimeError("injected order transition failure")

    event.listen(engine, "before_cursor_execute", fail_order_update)
    try:
        with pytest.raises(RuntimeError, match="injected order transition"):
            usage.hold(order["id"])
    finally:
        event.remove(engine, "before_cursor_execute", fail_order_update)

    assert wallet_repo.balance(wallet["id"]) == WalletBalance(
        150,
        0,
        150,
        0,
        0,
    )
    assert [
        row["event_type"]
        for row in wallet_repo.list_ledger(wallet["id"], 10, None)
    ] == ["purchase_grant"]
    assert usage.get_order(order["id"])["status"] == "quoted"


def test_admin_can_manage_catalogs_and_inspect_any_user_wallet(
    monkeypatch,
    wallet_repo,
    pricing,
):
    wallet = wallet_repo.ensure_wallet("user", "alice")
    wallet_repo.grant(
        wallet["id"],
        credits=30,
        credit_type="promotional",
        expires_at=None,
        idempotency_key="admin-visible-grant",
    )
    usage = UsageService(wallet_repo, pricing, mode="shadow")
    client = TestClient(_app(monkeypatch, usage, wallet_repo, pricing))

    denied = client.get(
        "/api/admin/billing/wallets/alice",
        headers=_headers("alice", "user"),
    )
    assert denied.status_code == 403

    created = client.post(
        "/api/admin/billing/catalogs/drafts",
        headers=_headers("admin-1", "admin"),
        json={
            "version": "admin-v1",
            "effective_at": NOW.isoformat(),
            "rules": [
                {
                    "id": "admin-v1-image",
                    "provider_id": "aliyun",
                    "model_key": "wan-2.7",
                    "capability": "text_to_image",
                    "unit_type": "image_count",
                    "credits_per_unit": 60,
                },
            ],
        },
    )
    assert created.status_code == 201
    catalog_id = created.json()["id"]
    published = client.post(
        f"/api/admin/billing/catalogs/{catalog_id}/publish",
        headers=_headers("admin-1", "admin"),
    )
    assert published.status_code == 200
    catalogs = client.get(
        "/api/admin/billing/catalogs",
        headers=_headers("admin-1", "admin"),
    )
    assert [(item["version"], item["status"]) for item in catalogs.json()] == [
        ("admin-v1", "published"),
    ]

    inspected = client.get(
        "/api/admin/billing/wallets/alice",
        headers=_headers("admin-1", "admin"),
    )
    ledger = client.get(
        "/api/admin/billing/wallets/alice/ledger",
        headers=_headers("admin-1", "admin"),
    )
    assert inspected.status_code == 200
    assert inspected.json()["owner"] == {"type": "user", "id": "alice"}
    assert inspected.json()["balance"]["promotional"] == 30
    assert [item["idempotency_key"] for item in ledger.json()["items"]] == [
        "admin-visible-grant",
    ]


def test_billing_routers_are_mounted_on_trusted_user_and_admin_prefixes():
    from qwenpaw.app.routers import router as api_router

    def route_paths(route) -> set[str]:
        if hasattr(route, "path"):
            return {route.path}
        paths: set[str] = set()
        for candidate in route.effective_candidates():
            paths.update(route_paths(candidate))
        return paths

    paths = set().union(*(route_paths(route) for route in api_router.routes))

    assert "/user/billing/wallet" in paths
    assert "/user/billing/ledger" in paths
    assert "/user/billing/quotes" in paths
    assert "/admin/billing/catalogs" in paths
    assert "/admin/billing/wallets/{owner_id}" in paths
