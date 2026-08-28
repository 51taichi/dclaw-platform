# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Lock

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
from qwenpaw.app.billing.usage import UsageOrderStateError, UsageService
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
    assert body["status"] == "quoted"
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
    assert order["status"] == "quoted"
    assert order["quoted_credits"] == 100
    assert order["held_credits"] == 0
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


def test_enforced_quote_records_price_without_holding_an_empty_wallet(
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

    assert response.status_code == 200
    assert response.json()["status"] == "quoted"
    assert response.json()["quoted_credits"] == 100
    assert response.json()["held_credits"] == 0
    with engine.connect() as conn:
        order = conn.execute(select(billing_usage_orders)).mappings().one()
    assert order["status"] == "quoted"
    assert order["held_credits"] == 0


def test_quote_rejects_usage_above_the_product_limit_with_422(
    monkeypatch,
    wallet_repo,
    pricing,
):
    _publish_catalog(pricing)
    usage = UsageService(wallet_repo, pricing, mode="shadow")
    client = TestClient(_app(monkeypatch, usage, wallet_repo, pricing))

    response = client.post(
        "/api/user/billing/quotes",
        json=_quote_payload("oversized") | {"input_tokens": 100_000_001},
        headers=_headers("alice"),
    )

    assert response.status_code == 422

    legacy_duration = client.post(
        "/api/user/billing/quotes",
        json=_quote_payload("oversized-duration")
        | {"parameters": {"duration": 10**100}},
        headers=_headers("alice"),
    )
    assert legacy_duration.status_code == 422


def test_same_client_business_key_is_namespaced_per_authenticated_user(
    monkeypatch,
    engine,
    wallet_repo,
    pricing,
):
    _publish_catalog(pricing)
    usage = UsageService(wallet_repo, pricing, mode="shadow")
    client = TestClient(_app(monkeypatch, usage, wallet_repo, pricing))

    alice = client.post(
        "/api/user/billing/quotes",
        json=_quote_payload("shared-key"),
        headers=_headers("alice"),
    )
    bob = client.post(
        "/api/user/billing/quotes",
        json=_quote_payload("shared-key"),
        headers=_headers("bob"),
    )

    assert alice.status_code == 200
    assert bob.status_code == 200
    assert alice.json()["id"] != bob.json()["id"]
    assert alice.json()["business_key"] == "shared-key"
    assert bob.json()["business_key"] == "shared-key"
    with engine.connect() as conn:
        stored_keys = conn.scalars(
            select(billing_usage_orders.c.business_key),
        ).all()
    assert len(set(stored_keys)) == 2
    assert "shared-key" not in stored_keys


@pytest.mark.parametrize(
    "payload_update",
    [
        {"provider_id": "other-provider"},
        {"model_key": "other-model"},
        {"capability": "text_to_video"},
        {"parameters": {"count": 3}},
        {"input_tokens": 1},
        {"output_tokens": 1},
    ],
)
def test_same_owner_key_with_changed_quote_request_returns_409_conflict(
    monkeypatch,
    wallet_repo,
    pricing,
    payload_update,
):
    _publish_catalog(pricing)
    usage = UsageService(wallet_repo, pricing, mode="shadow")
    client = TestClient(_app(monkeypatch, usage, wallet_repo, pricing))
    first = client.post(
        "/api/user/billing/quotes",
        json=_quote_payload("stable-key"),
        headers=_headers("alice"),
    )

    changed = client.post(
        "/api/user/billing/quotes",
        json=_quote_payload("stable-key") | payload_update,
        headers=_headers("alice"),
    )

    assert first.status_code == 200
    assert changed.status_code == 409
    assert changed.json()["code"] == "idempotency_conflict"


@pytest.mark.parametrize("terminal_state", ["captured", "released"])
def test_terminal_quote_replay_returns_the_existing_order_without_reholding(
    monkeypatch,
    wallet_repo,
    pricing,
    terminal_state,
):
    _publish_catalog(pricing)
    usage = UsageService(wallet_repo, pricing, mode="shadow")
    order = usage.create_quote(
        "alice",
        QuoteRequest(
            "aliyun",
            "wan-2.7",
            "text_to_image",
            {"count": 2},
        ),
        business_key=f"terminal-{terminal_state}",
    )
    usage.hold(order["id"])
    if terminal_state == "captured":
        usage.settle_supplier(
            order["id"],
            supplier_reference="dashscope:terminal-capture",
            evidence={"charged": True},
            billability="billable",
            actual_credits=100,
        )
    else:
        usage.settle_supplier(
            order["id"],
            supplier_reference="dashscope:terminal-release",
            evidence={"charged": False},
            billability="not_billable",
        )
    client = TestClient(_app(monkeypatch, usage, wallet_repo, pricing))

    replay = client.post(
        "/api/user/billing/quotes",
        json=_quote_payload(f"terminal-{terminal_state}"),
        headers=_headers("alice"),
    )

    assert replay.status_code == 200
    assert replay.json()["id"] == order["id"]
    assert replay.json()["status"] == terminal_state


def test_quote_replay_returns_a_reconciling_order_without_settling_it(
    monkeypatch,
    wallet_repo,
    pricing,
):
    _publish_catalog(pricing)
    usage = UsageService(wallet_repo, pricing, mode="shadow")
    order = usage.create_quote(
        "alice",
        QuoteRequest(
            "aliyun",
            "wan-2.7",
            "text_to_image",
            {"count": 2},
        ),
        business_key="reconciling-replay",
    )
    usage.hold(order["id"])
    usage.settle_supplier(
        order["id"],
        supplier_reference="dashscope:reconciling",
        evidence={"task_status": "UNKNOWN"},
        billability="unknown",
    )
    client = TestClient(
        _app(monkeypatch, usage, wallet_repo, pricing),
        raise_server_exceptions=False,
    )

    replay = client.post(
        "/api/user/billing/quotes",
        json=_quote_payload("reconciling-replay"),
        headers=_headers("alice"),
    )

    assert replay.status_code == 200
    assert replay.json()["status"] == "reconciling"


def test_quote_without_published_catalog_returns_catalog_not_ready(
    monkeypatch,
    wallet_repo,
    pricing,
):
    usage = UsageService(wallet_repo, pricing, mode="shadow")
    client = TestClient(
        _app(monkeypatch, usage, wallet_repo, pricing),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/api/user/billing/quotes",
        json=_quote_payload("no-catalog"),
        headers=_headers("alice"),
    )

    assert response.status_code == 503
    assert response.json()["code"] == "catalog_not_ready"


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
    reconciling = usage.settle_supplier(
        capture_order["id"],
        supplier_reference="dashscope:capture",
        evidence={"task_status": "UNKNOWN"},
        billability="unknown",
    )
    captured = usage.settle_supplier(
        capture_order["id"],
        supplier_reference="dashscope:capture",
        evidence={"task_status": "SUCCEEDED"},
        billability="billable",
        actual_credits=100,
    )

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
    released = usage.settle_supplier(
        release_order["id"],
        supplier_reference="dashscope:release",
        evidence={"task_status": "FAILED", "charged": False},
        billability="not_billable",
    )

    assert released["status"] == "released"
    assert wallet_repo.balance(release_wallet["id"]) == WalletBalance(
        150,
        0,
        150,
        0,
        0,
    )


def test_supplier_evidence_drives_unknown_then_partial_billable_settlement(
    wallet_repo,
    pricing,
):
    _publish_catalog(pricing)
    wallet = wallet_repo.ensure_wallet("user", "evidence-user")
    wallet_repo.grant(
        wallet["id"],
        credits=150,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="evidence-purchase",
    )
    usage = UsageService(wallet_repo, pricing, mode="enforced")
    order = usage.create_quote(
        "evidence-user",
        QuoteRequest(
            "aliyun",
            "wan-2.7",
            "text_to_image",
            {"count": 2, "tier": "standard"},
        ),
        business_key="evidence-job",
    )
    usage.hold(order["id"])

    unknown = usage.settle_supplier(
        order["id"],
        supplier_reference="dashscope:req-1",
        evidence={"task_status": "UNKNOWN", "attempt": 1},
        billability="unknown",
    )
    captured = usage.settle_supplier(
        order["id"],
        supplier_reference="dashscope:req-1",
        evidence={"task_status": "SUCCEEDED", "images": 1},
        billability="billable",
        actual_credits=50,
    )
    replay = usage.settle_supplier(
        order["id"],
        supplier_reference="dashscope:req-1",
        evidence={"task_status": "SUCCEEDED", "images": 1},
        billability="billable",
        actual_credits=50,
    )

    assert unknown["status"] == "reconciling"
    assert captured == replay
    assert captured["status"] == "captured"
    assert captured["billability"] == "billable"
    assert captured["supplier_reference"] == "dashscope:req-1"
    assert captured["supplier_evidence"] == {
        "images": 1,
        "task_status": "SUCCEEDED",
    }
    assert captured["captured_credits"] == 50
    assert wallet_repo.balance(wallet["id"]) == WalletBalance(
        100,
        0,
        100,
        0,
        0,
    )


def test_not_billable_supplier_evidence_releases_the_complete_hold(
    wallet_repo,
    pricing,
):
    _publish_catalog(pricing)
    wallet = wallet_repo.ensure_wallet("user", "not-billable-user")
    wallet_repo.grant(
        wallet["id"],
        credits=100,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="not-billable-purchase",
    )
    usage = UsageService(wallet_repo, pricing, mode="enforced")
    order = usage.create_quote(
        "not-billable-user",
        QuoteRequest(
            "aliyun",
            "wan-2.7",
            "text_to_image",
            {"count": 2},
        ),
        business_key="not-billable-job",
    )
    usage.hold(order["id"])

    released = usage.settle_supplier(
        order["id"],
        supplier_reference="dashscope:req-2",
        evidence={"task_status": "FAILED", "charged": False},
        billability="not_billable",
    )

    assert released["status"] == "released"
    assert released["billability"] == "not_billable"
    assert wallet_repo.balance(wallet["id"]) == WalletBalance(
        100,
        0,
        100,
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
    captured = usage.settle_supplier(
        order["id"],
        supplier_reference="dashscope:shadow",
        evidence={"task_status": "SUCCEEDED"},
        billability="billable",
        actual_credits=100,
    )

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
    assert "/user/billing/usage-orders" in paths
    assert "/user/billing/usage-orders/{order_id}" in paths
    assert "/user/billing/open-api-summary" in paths
    assert "/admin/billing/catalogs" in paths
    assert "/admin/billing/wallets/{owner_id}" in paths
    assert "/admin/billing/usage-orders" in paths
    assert "/admin/billing/reconciliation" in paths
    assert "/admin/billing/reconciliation/{item_id}/resolve" in paths
    assert "/admin/billing/rollout/activate" in paths


def _synchronize_first_order_reads(order_id: str):
    barrier = Barrier(2)
    lock = Lock()
    synchronized = 0

    def synchronize(
        _conn,
        _cursor,
        statement,
        parameters,
        _context,
        _executemany,
    ):
        nonlocal synchronized
        if (
            not statement.lstrip().upper().startswith("SELECT")
            or "FROM billing_usage_orders" not in statement
            or order_id not in parameters
        ):
            return
        with lock:
            if synchronized >= 2:
                return
            synchronized += 1
        barrier.wait(timeout=5)

    return synchronize


def test_concurrent_hold_replay_returns_one_consistent_held_order(
    engine,
    wallet_repo,
    pricing,
):
    _publish_catalog(pricing)
    wallet = wallet_repo.ensure_wallet("user", "concurrent-hold")
    wallet_repo.grant(
        wallet["id"],
        credits=100,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="concurrent-hold-purchase",
    )
    usage = UsageService(wallet_repo, pricing, mode="enforced")
    order = usage.create_quote(
        "concurrent-hold",
        QuoteRequest(
            "aliyun",
            "wan-2.7",
            "text_to_image",
            {"count": 2},
        ),
        business_key="concurrent-hold-job",
    )
    synchronize = _synchronize_first_order_reads(order["id"])
    event.listen(engine, "after_cursor_execute", synchronize)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(lambda _index: usage.hold(order["id"]), range(2)),
            )
    finally:
        event.remove(engine, "after_cursor_execute", synchronize)

    assert [result["status"] for result in results] == ["held", "held"]
    assert wallet_repo.balance(wallet["id"]) == WalletBalance(
        0,
        100,
        100,
        0,
        0,
    )
    entries = wallet_repo.list_ledger(wallet["id"], 10, None)
    assert sum(row["event_type"] == "usage_hold" for row in entries) == 1


def test_concurrent_capture_and_release_has_one_controlled_winner(
    engine,
    wallet_repo,
    pricing,
):
    _publish_catalog(pricing)
    wallet = wallet_repo.ensure_wallet("user", "concurrent-settlement")
    wallet_repo.grant(
        wallet["id"],
        credits=150,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="concurrent-settlement-purchase",
    )
    usage = UsageService(wallet_repo, pricing, mode="enforced")
    order = usage.create_quote(
        "concurrent-settlement",
        QuoteRequest(
            "aliyun",
            "wan-2.7",
            "text_to_image",
            {"count": 2},
        ),
        business_key="concurrent-settlement-job",
    )
    usage.hold(order["id"])
    synchronize = _synchronize_first_order_reads(order["id"])
    event.listen(engine, "after_cursor_execute", synchronize)

    def settle(billability):
        try:
            return usage.settle_supplier(
                order["id"],
                supplier_reference="dashscope:race",
                evidence={"billability": billability},
                billability=billability,
                actual_credits=70 if billability == "billable" else None,
            )
        except UsageOrderStateError as exc:
            return exc

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(
                executor.map(settle, ("billable", "not_billable")),
            )
    finally:
        event.remove(engine, "after_cursor_execute", synchronize)

    assert (
        sum(isinstance(item, UsageOrderStateError) for item in outcomes) == 1
    )
    terminal = usage.get_order(order["id"])
    assert terminal["status"] in {"captured", "released"}
    expected_available = 80 if terminal["status"] == "captured" else 150
    assert wallet_repo.balance(wallet["id"]).available == expected_available
    assert wallet_repo.balance(wallet["id"]).held == 0
