# -*- coding: utf-8 -*-
"""Financial reporting and operator reconciliation contracts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, insert, inspect, select, update
from sqlalchemy.exc import DBAPIError

from qwenpaw.app.billing.models import LedgerTransaction
from qwenpaw.app.billing.pricing import (
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
)
from qwenpaw.app.billing.reporting import (
    BillingReportFilters,
    BillingReportingService,
    ReconciliationConflictError,
    ReconciliationNotFoundError,
    ReconciliationResolution,
)
from qwenpaw.app import auth as app_auth
from qwenpaw.app.guards import require_admin, require_user
from qwenpaw.app.routers import billing
from qwenpaw.app.open_api import runtime as open_api_runtime
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.schema import (
    billing_ledger_entries,
    billing_reconciliation_audits,
    billing_rollout_settings,
    billing_usage_items,
    billing_usage_orders,
    create_all,
    open_api_external_apps,
    open_api_invocations,
    open_api_keys,
    open_api_publications,
)
from qwenpaw.app.storage.settings import get_storage_settings


NOW = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)


@pytest.fixture(name="reporting")
def _reporting(tmp_path):
    settings = get_storage_settings(
        {"QWENPAW_SQLITE_PATH": str(tmp_path / "billing-reporting.db")},
    )
    engine = create_engine_from_settings(settings)
    create_all(engine)
    repository = BillingRepository(engine, clock=lambda: NOW)
    pricing = PriceCatalogService(
        PriceCatalogRepository(engine),
        clock=lambda: NOW,
    )
    catalog_id = pricing.publish(
        PriceCatalogDraft(
            version="retail-report-v1",
            effective_at=NOW - timedelta(days=1),
            created_by="admin:seed",
            rules=(
                PriceRule(
                    id="report-text",
                    provider_id="provider-a",
                    model_key="model-a",
                    capability="text",
                    unit_type="tokens",
                    input_credits_per_1k=2,
                    output_credits_per_1k=3,
                ),
                PriceRule(
                    id="report-text-b",
                    provider_id="provider-b",
                    model_key="model-b",
                    capability="text",
                    unit_type="tokens",
                    input_credits_per_1k=4,
                    output_credits_per_1k=5,
                ),
            ),
        ),
    )
    _seed_identity(engine)
    wallets = {
        owner: repository.ensure_wallet("user", owner)
        for owner in ("alice", "bob")
    }
    for owner, wallet in wallets.items():
        repository.append_transaction(
            LedgerTransaction(
                wallet_id=str(wallet["id"]),
                event_type="purchase_grant",
                credits=100,
                business_type="grant",
                business_key=f"seed-{owner}",
                idempotency_key=f"seed-{owner}",
                credit_type="purchased",
            ),
        )
    _seed_orders(engine, repository, wallets, catalog_id)
    service = BillingReportingService(
        repository,
        pricing,
        clock=lambda: NOW,
    )
    try:
        yield service, repository, engine
    finally:
        engine.dispose()


def _seed_identity(engine) -> None:
    with engine.begin() as conn:
        for owner in ("alice", "bob"):
            conn.execute(
                insert(open_api_publications).values(
                    id=f"pub-{owner}",
                    public_id=f"public-{owner}",
                    target_type="agent",
                    target_id=f"agent-{owner}",
                    owner_user_id=f"publisher-{owner}",
                    bound_user_id=owner,
                    knowledge_base_id=f"kb-{owner}",
                    name=f"Publication {owner.title()}",
                    allowed_scopes="[]",
                ),
            )
            conn.execute(
                insert(open_api_external_apps).values(
                    id=f"app-{owner}",
                    owner_user_id=f"app-owner-{owner}",
                    name=f"Application {owner.title()}",
                    ip_allowlist="[]",
                    quota_policy="{}",
                ),
            )
            conn.execute(
                insert(open_api_keys).values(
                    id=f"key-{owner}",
                    app_id=f"app-{owner}",
                    publication_id=f"pub-{owner}",
                    key_hash=f"hash-{owner}",
                    key_prefix="dc",
                    key_suffix=owner,
                    scopes="[]",
                ),
            )


def _seed_orders(engine, repository, wallets, catalog_id: str) -> None:
    values = (
        ("alice-new", "alice", "enforced", "settled", NOW, "model-a"),
        (
            "alice-shadow",
            "alice",
            "shadow",
            "settled",
            NOW - timedelta(hours=1),
            "model-b",
        ),
        (
            "alice-reconciling",
            "alice",
            "enforced",
            "reconciling",
            NOW - timedelta(hours=2),
            "model-a",
        ),
        (
            "alice-historical",
            "alice",
            "shadow",
            "unbilled",
            NOW - timedelta(days=30),
            "model-a",
        ),
        ("bob-new", "bob", "enforced", "settled", NOW, "model-a"),
    )
    with engine.begin() as conn:
        for key, owner, mode, status, created_at, model in values:
            order_id = f"order-{key}"
            invocation_id = f"inv-{key}"
            item_status = (
                "reconciling" if status == "reconciling" else "captured"
            )
            billability = (
                "unknown"
                if status in {"reconciling", "unbilled"}
                else "billable"
            )
            charged = 0 if item_status == "reconciling" else 5
            conn.execute(
                insert(billing_usage_orders).values(
                    id=order_id,
                    wallet_id=str(wallets[owner]["id"]),
                    catalog_id=catalog_id,
                    business_key=f"business-{key}",
                    source_type="open_api" if status != "unbilled" else None,
                    source_id=invocation_id if status != "unbilled" else None,
                    status="reconciling"
                    if status == "reconciling"
                    else "settled",
                    provider_id="open_api",
                    model_key="invocation",
                    capability="text",
                    quoted_credits=6,
                    budget_credits=100,
                    held_credits=6 if item_status == "reconciling" else 0,
                    captured_credits=charged,
                    released_credits=1 if charged else 0,
                    reconciling_credits=6
                    if item_status == "reconciling"
                    else 0,
                    request_snapshot_json=json.dumps({"billing_mode": mode}),
                    price_snapshot_json=json.dumps(
                        {"catalog_version": "retail-report-v1"},
                    ),
                    billability=billability,
                    created_at=created_at,
                    updated_at=created_at,
                ),
            )
            conn.execute(
                insert(open_api_invocations).values(
                    id=invocation_id,
                    app_id=f"app-{owner}",
                    publication_id=f"pub-{owner}",
                    api_key_id=f"key-{owner}",
                    target_type="agent",
                    target_id=f"agent-{owner}",
                    status="succeeded",
                    status_code=200,
                    token_summary="{}",
                    billing_usage_order_id=order_id,
                    billing_status=status,
                    quoted_credits=6,
                    captured_credits=charged,
                    released_credits=1 if charged else 0,
                    created_at=created_at,
                ),
            )
            conn.execute(
                insert(billing_usage_items).values(
                    id=f"item-{key}",
                    usage_order_id=order_id,
                    price_rule_id=(
                        "report-text"
                        if model == "model-a"
                        else "report-text-b"
                    ),
                    item_key=f"call-{key}",
                    status=item_status,
                    provider_id=(
                        "provider-a" if model == "model-a" else "provider-b"
                    ),
                    model_key=model,
                    capability="text",
                    supplier_reference=f"supplier-secret-{key}",
                    input_tokens=1000,
                    output_tokens=1000,
                    quoted_credits=6,
                    charged_credits=charged,
                    supplier_cost_fen=987654,
                    usage_snapshot_json=json.dumps(
                        {
                            "reservation": {
                                "parameters": {},
                                "prompt": "must never leave storage",
                            },
                        },
                    ),
                    price_snapshot_json=json.dumps(
                        {
                            "catalog_version": "retail-report-v1",
                            "rule_id": (
                                "report-text"
                                if model == "model-a"
                                else "report-text-b"
                            ),
                            "credits": 6,
                            "unit_breakdown": {
                                "input_tokens": 2,
                                "output_tokens": 3,
                            },
                            "snapshot": {
                                "rule": {"unit_type": "tokens"},
                                "owner_secret": "never expose",
                            },
                            "request": {
                                "parameters": {"secret": "never expose"},
                            },
                        },
                    ),
                    supplier_evidence_json=json.dumps(
                        {"raw": "never expose", "api_key": "secret"},
                    ),
                    billability=billability,
                    execution_outcome="succeeded",
                    started_at=created_at,
                    finished_at=created_at,
                    created_at=created_at,
                    updated_at=created_at,
                ),
            )
    # Only the enforced captured item is an actual wallet debit. Shadow's
    # durable retail result is an estimate and must not be counted as debit.
    business_key = "open-api-item:order-alice-new:call-alice-new"
    repository.append_transaction(
        LedgerTransaction(
            wallet_id=str(wallets["alice"]["id"]),
            event_type="usage_hold",
            credits=6,
            business_type="usage_item",
            business_key=business_key,
            idempotency_key="alice-new-hold",
        ),
    )
    repository.append_transaction(
        LedgerTransaction(
            wallet_id=str(wallets["alice"]["id"]),
            event_type="usage_capture",
            credits=5,
            business_type="usage_item",
            business_key=business_key,
            idempotency_key="alice-new-capture",
        ),
    )


def test_fresh_and_upgrade_create_reporting_state_tables(tmp_path):
    path = tmp_path / "legacy.db"
    settings = get_storage_settings({"QWENPAW_SQLITE_PATH": str(path)})
    engine = create_engine_from_settings(settings)
    try:
        create_all(engine)
        billing_reconciliation_audits.drop(engine)
        billing_rollout_settings.drop(engine)
        assert {
            "billing_reconciliation_audits",
            "billing_rollout_settings",
        }.isdisjoint(inspect(engine).get_table_names())
        create_all(engine)
        # Re-running the upgrade must also remain idempotent.
        create_all(engine)
        names = set(inspect(engine).get_table_names())
        assert {
            "billing_reconciliation_audits",
            "billing_rollout_settings",
        } <= names
    finally:
        engine.dispose()


def test_user_list_filters_and_detail_are_owner_scoped_and_redacted(reporting):
    service, _repository, engine = reporting
    page = service.list_usage_orders(
        owner_user_id="alice",
        filters=BillingReportFilters(
            started_at=NOW - timedelta(minutes=1),
            ended_at=NOW + timedelta(minutes=1),
            model="model-a",
            publication_id="pub-alice",
            app_id="app-alice",
            status="settled",
        ),
        limit=10,
    )
    assert [item["id"] for item in page["items"]] == ["order-alice-new"]
    with engine.begin() as conn:
        second_item = dict(
            conn.execute(
                select(billing_usage_items).where(
                    billing_usage_items.c.id == "item-alice-new",
                ),
            )
            .mappings()
            .one(),
        )
        second_item.update(
            id="item-alice-new-2",
            item_key="call-alice-new-2",
            supplier_reference="supplier-secret-alice-new-2",
        )
        conn.execute(insert(billing_usage_items).values(**second_item))
    detail = service.get_usage_order(
        "order-alice-new",
        owner_user_id="alice",
    )
    assert detail is not None
    assert len(detail["items"]) == 2
    item = detail["items"][0]
    assert item["price"] == {
        "catalog_version": "retail-report-v1",
        "rule_id": "report-text",
        "quoted_credits": 6,
        "unit_breakdown": {"input_tokens": 2, "output_tokens": 3},
    }
    serialized = json.dumps(detail)
    for forbidden in (
        "supplier-secret",
        "supplier_cost",
        "supplier_evidence",
        "never expose",
        "prompt",
        '"api_key": "secret"',
        "api_key_id",
        "owner_user_id",
    ):
        assert forbidden not in serialized
    assert (
        service.get_usage_order("order-bob-new", owner_user_id="alice") is None
    )


def test_admin_list_can_filter_by_internal_identity_without_raw_evidence(
    reporting,
):
    service, _repository, _engine = reporting
    page = service.list_usage_orders(
        owner_user_id=None,
        filters=BillingReportFilters(
            owner_user_id="bob",
            api_key_id="key-bob",
            provider="provider-a",
            model="model-a",
        ),
        limit=10,
    )

    assert [order["id"] for order in page["items"]] == ["order-bob-new"]
    assert page["items"][0]["owner_user_id"] == "bob"
    assert page["items"][0]["api_key_id"] == "key-bob"
    serialized = json.dumps(page)
    assert "supplier-secret" not in serialized
    assert "never expose" not in serialized


def test_cursor_is_stable_scoped_and_rejects_timezone_naive_filters(reporting):
    service, _repository, _engine = reporting
    first = service.list_usage_orders(
        owner_user_id="alice",
        filters=BillingReportFilters(),
        limit=1,
    )
    assert len(first["items"]) == 1
    assert first["next_cursor"]
    second = service.list_usage_orders(
        owner_user_id="alice",
        filters=BillingReportFilters(),
        limit=1,
        cursor=first["next_cursor"],
    )
    assert second["items"][0]["id"] != first["items"][0]["id"]
    with pytest.raises(ValueError, match="cursor"):
        service.list_usage_orders(
            owner_user_id="bob",
            filters=BillingReportFilters(),
            limit=1,
            cursor=first["next_cursor"],
        )
    with pytest.raises(ValueError, match="timezone"):
        BillingReportFilters(started_at=datetime(2026, 8, 29, 8, 0))


def test_summary_uses_durable_items_and_ledger_and_excludes_history(reporting):
    service, repository, engine = reporting
    summary = service.open_api_summary("alice", timezone_name="Asia/Shanghai")
    assert summary["totals"] == {
        "orders": 3,
        "model_calls": 3,
        "input_tokens": 3000,
        "output_tokens": 3000,
        "retail_credits": 10,
        "actual_debited_credits": 5,
        "shadow_estimated_credits": 5,
        "reconciling_credits": 6,
    }
    assert summary["eras"]["financial_cutover_at"] is None
    assert summary["eras"]["historical_statistics_included"] is False
    assert summary["top_up"]["collects_payment"] is False
    with engine.connect() as conn:
        analytics_count = conn.scalar(
            select(func.count()).select_from(billing_usage_items),
        )
    assert analytics_count == 5
    # No summary read changes wallet or ledger state.
    wallet = repository.get_wallet("user", "alice")
    assert wallet is not None
    before = repository.balance(str(wallet["id"]))
    service.open_api_summary("alice")
    assert repository.balance(str(wallet["id"])) == before


def test_manual_resolution_is_atomic_audited_idempotent_and_conflicting(
    reporting,
):
    service, repository, engine = reporting
    wallet = repository.get_wallet("user", "alice")
    assert wallet is not None
    business_key = (
        "open-api-item:order-alice-reconciling:call-alice-reconciling"
    )
    repository.append_transaction(
        LedgerTransaction(
            wallet_id=str(wallet["id"]),
            event_type="usage_hold",
            credits=6,
            business_type="usage_item",
            business_key=business_key,
            idempotency_key="alice-reconciling-hold",
        ),
    )
    request = ReconciliationResolution(
        idempotency_key="resolve-alice-1",
        billability="billable",
        reason="Supplier invoice confirms this model call.",
        actual_input_tokens=1000,
        actual_output_tokens=1000,
    )
    first = service.resolve_reconciliation(
        "item-alice-reconciling",
        actor_id="admin-7",
        resolution=request,
    )
    replay = service.resolve_reconciliation(
        "item-alice-reconciling",
        actor_id="admin-7",
        resolution=request,
    )
    assert replay == first
    assert first["status"] == "captured"
    assert first["charged_credits"] == 5
    assert repository.balance(str(wallet["id"])).held == 0
    with engine.connect() as conn:
        audits = (
            conn.execute(select(billing_reconciliation_audits))
            .mappings()
            .all()
        )
        ledger = (
            conn.execute(
                select(billing_ledger_entries).where(
                    billing_ledger_entries.c.business_key == business_key,
                    billing_ledger_entries.c.event_type == "usage_capture",
                ),
            )
            .mappings()
            .all()
        )
    assert len(audits) == len(ledger) == 1
    assert audits[0]["actor_id"] == "admin-7"
    assert audits[0]["reason"] == request.reason
    assert ledger[0]["actor_id"] == "admin-7"
    assert ledger[0]["reason"] == request.reason
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.execute(
                update(billing_reconciliation_audits)
                .where(billing_reconciliation_audits.c.id == audits[0]["id"])
                .values(reason="rewrite"),
            )
    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.execute(
                delete(billing_reconciliation_audits).where(
                    billing_reconciliation_audits.c.id == audits[0]["id"],
                ),
            )
    with pytest.raises(ReconciliationConflictError):
        service.resolve_reconciliation(
            "item-alice-reconciling",
            actor_id="admin-7",
            resolution=ReconciliationResolution(
                idempotency_key="resolve-alice-1",
                billability="not_billable",
                reason="Changed answer",
            ),
        )
    with pytest.raises(ReconciliationNotFoundError):
        service.resolve_reconciliation(
            "item-alice-new",
            actor_id="admin-7",
            resolution=ReconciliationResolution(
                idempotency_key="resolved-item-new",
                billability="not_billable",
                reason="Must not rewrite settled items",
            ),
        )


def test_rollout_cutover_is_written_once_only_by_explicit_enforced_activation(
    reporting,
):
    service, _repository, engine = reporting
    off = service.activate_rollout("off", actor_id="admin-1")
    observe = service.activate_rollout("observe", actor_id="admin-1")
    assert off["billing_cutover_at"] is None
    assert observe["billing_cutover_at"] is None
    enforced = service.activate_rollout("enforced", actor_id="admin-2")
    repeated = service.activate_rollout("enforced", actor_id="admin-3")
    assert enforced["billing_cutover_at"] == NOW.isoformat()
    assert repeated["billing_cutover_at"] == enforced["billing_cutover_at"]
    with engine.connect() as conn:
        rows = conn.execute(select(billing_rollout_settings)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["cutover_actor_id"] == "admin-2"


def test_open_api_runtime_prefers_persisted_rollout_over_environment(
    monkeypatch,
    reporting,
):
    service, _repository, engine = reporting
    service.activate_rollout("observe", actor_id="admin-1")
    monkeypatch.setenv("DCLAW_BILLING_MODE", "enforced")
    monkeypatch.setattr(open_api_runtime, "get_app_engine", lambda: engine)

    runtime = open_api_runtime.create_open_api_billing_runtime()

    assert runtime.mode == "observe"
    assert runtime.usage_service.mode == "observe"


def test_environment_cannot_bypass_explicit_enforced_activation(
    monkeypatch,
    reporting,
):
    _service, _repository, engine = reporting
    monkeypatch.setenv("DCLAW_BILLING_MODE", "enforced")
    monkeypatch.setattr(open_api_runtime, "get_app_engine", lambda: engine)

    runtime = open_api_runtime.create_open_api_billing_runtime()

    assert runtime.mode == "shadow"
    assert runtime.usage_service.mode == "shadow"


def _reporting_client(monkeypatch, service, repository) -> TestClient:
    monkeypatch.setattr(app_auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(
        billing,
        "get_billing_reporting_service",
        lambda: service,
    )
    monkeypatch.setattr(billing, "get_billing_repository", lambda: repository)
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
    return TestClient(app)


def _headers(user_id: str, role: str = "user") -> dict[str, str]:
    return {"x-test-user": user_id, "x-test-role": role}


def test_user_reporting_routes_return_404_for_another_wallet_and_redact(
    monkeypatch,
    reporting,
):
    service, repository, _engine = reporting
    client = _reporting_client(monkeypatch, service, repository)
    own = client.get(
        "/api/user/billing/usage-orders/order-alice-new",
        headers=_headers("alice"),
    )
    other = client.get(
        "/api/user/billing/usage-orders/order-bob-new",
        headers=_headers("alice"),
    )
    summary = client.get(
        "/api/user/billing/open-api-summary?timezone=Asia%2FShanghai",
        headers=_headers("alice"),
    )
    assert own.status_code == 200
    assert len(own.json()["items"]) == 1
    assert other.status_code == 404
    assert summary.status_code == 200
    assert summary.json()["totals"]["actual_debited_credits"] == 5
    serialized = json.dumps(own.json())
    assert "supplier-secret" not in serialized
    assert "never expose" not in serialized


def test_admin_resolution_actor_comes_only_from_auth_and_rollout_is_explicit(
    monkeypatch,
    reporting,
):
    service, repository, _engine = reporting
    wallet = repository.get_wallet("user", "alice")
    assert wallet is not None
    repository.append_transaction(
        LedgerTransaction(
            wallet_id=str(wallet["id"]),
            event_type="usage_hold",
            credits=6,
            business_type="usage_item",
            business_key=(
                "open-api-item:order-alice-reconciling:"
                "call-alice-reconciling"
            ),
            idempotency_key="route-reconciliation-hold",
        ),
    )
    client = _reporting_client(monkeypatch, service, repository)
    denied = client.get(
        "/api/admin/billing/reconciliation",
        headers=_headers("alice"),
    )
    spoofed = client.post(
        "/api/admin/billing/reconciliation/item-alice-reconciling/resolve",
        headers={
            **_headers("admin-real", "admin"),
            "Idempotency-Key": "route-resolution-1",
        },
        json={
            "actor_id": "client-spoof",
            "billability": "not_billable",
            "reason": "Supplier portal confirms no charge.",
            "actual_input_tokens": 0,
            "actual_output_tokens": 0,
        },
    )
    exceeds_reservation = client.post(
        "/api/admin/billing/reconciliation/item-alice-reconciling/resolve",
        headers={
            **_headers("admin-real", "admin"),
            "Idempotency-Key": "route-resolution-too-high",
        },
        json={
            "billability": "billable",
            "reason": "Supplier usage exceeds the reserved retail quote.",
            "actual_input_tokens": 100_000_000,
            "actual_output_tokens": 100_000_000,
        },
    )
    resolved = client.post(
        "/api/admin/billing/reconciliation/item-alice-reconciling/resolve",
        headers={
            **_headers("admin-real", "admin"),
            "Idempotency-Key": "route-resolution-1",
        },
        json={
            "billability": "not_billable",
            "reason": "Supplier portal confirms no charge.",
            "actual_input_tokens": 0,
            "actual_output_tokens": 0,
        },
    )
    observed = client.post(
        "/api/admin/billing/rollout/activate",
        headers=_headers("admin-real", "admin"),
        json={"mode": "observe"},
    )
    enforced = client.post(
        "/api/admin/billing/rollout/activate",
        headers=_headers("admin-real", "admin"),
        json={"mode": "enforced"},
    )
    assert denied.status_code == 403
    assert spoofed.status_code == 422
    assert exceeds_reservation.status_code == 409
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "released"
    assert observed.json()["billing_cutover_at"] is None
    assert enforced.json()["billing_cutover_at"] == NOW.isoformat()
