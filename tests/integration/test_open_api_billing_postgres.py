# -*- coding: utf-8 -*-
"""Live PostgreSQL concurrency coverage for OpenAPI billing sessions."""
# pylint: disable=redefined-outer-name
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, inspect, select, text, update
from sqlalchemy.schema import CreateSchema, DropSchema

import qwenpaw.app.storage.schema as schema_module
from qwenpaw.app.billing.open_api import (
    CatalogNotReadyError,
    IdempotencyConflictError,
    OpenApiBillingCommand,
    OpenApiBillingCoordinator,
)
from qwenpaw.app.billing.pricing import (
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
)
from qwenpaw.app.billing.usage import (
    BillingExecutionFencedError,
    ReserveModelCall,
    SettleModelCall,
    UsageOrderConflictError,
    UsageService,
)
from qwenpaw.app.open_api.runtime import (
    OpenApiBillingRuntime,
    recover_open_api_billing,
)
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.open_api_repo import SqlAlchemyOpenApiRepository
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.schema import (
    billing_usage_items,
    billing_wallets,
    billing_usage_orders,
    create_all,
    open_api_invocations,
)
from qwenpaw.app.storage.settings import normalize_postgres_url


@pytest.fixture
def postgres_open_api_engine():
    raw_url = os.environ.get("QWENPAW_TEST_POSTGRES_URL", "").strip()
    if not raw_url:
        pytest.skip(
            "QWENPAW_TEST_POSTGRES_URL is not configured; "
            "live PostgreSQL OpenAPI billing verification was not run",
        )
    database_url = normalize_postgres_url(raw_url)
    schema_name = f"open_api_billing_{uuid4().hex}"
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


def _coordinator(engine, identity: str, *, publish_catalog: bool = True):
    publication_id = f"pub-{identity}"
    app_id = f"app-{identity}"
    api_key_id = f"key-{identity}"
    open_api = SqlAlchemyOpenApiRepository(engine)
    open_api.upsert_publication(
        {
            "id": publication_id,
            "public_id": f"public-{identity}",
            "target_type": "agent",
            "target_id": "agent-1",
            "owner_user_id": f"publication-owner-{identity}",
            "bound_user_id": f"bound-user-{identity}",
            "name": "Open API agent",
        },
    )
    open_api.create_external_app(
        {
            "id": app_id,
            "owner_user_id": f"app-owner-{identity}",
            "name": "app",
        },
    )
    open_api.create_api_key(
        {
            "id": api_key_id,
            "app_id": app_id,
            "publication_id": publication_id,
            "key_hash": f"hash-{identity}",
            "key_prefix": "qp_live",
            "key_suffix": "test",
            "scopes": ["messages:create"],
        },
    )
    pricing = PriceCatalogService(PriceCatalogRepository(engine))
    if publish_catalog:
        pricing.publish(
            PriceCatalogDraft(
                version="postgres-v1",
                effective_at=datetime.now(timezone.utc) - timedelta(minutes=1),
                rules=(
                    PriceRule(
                        id="postgres-text",
                        provider_id="provider",
                        model_key="model",
                        capability="text",
                        unit_type="tokens",
                        input_credits_per_1k=1,
                    ),
                ),
            ),
        )
    return OpenApiBillingCoordinator(BillingRepository(engine), pricing)


def _command(
    identity: str,
    key: str,
    message: str = "first",
    mode: str = "shadow",
) -> OpenApiBillingCommand:
    return OpenApiBillingCommand(
        app_id=f"app-{identity}",
        publication_id=f"pub-{identity}",
        api_key_id=f"key-{identity}",
        target_type="agent",
        target_id="agent-1",
        external_user_id="external-user",
        external_session_id="external-session",
        payload={"message": message},
        idempotency_key=key,
        mode=mode,
    )


def _billing_counts(engine) -> tuple[int, int, int]:
    with engine.connect() as conn:
        return (
            int(
                conn.scalar(select(func.count()).select_from(billing_wallets)),
            ),
            int(
                conn.scalar(
                    select(func.count()).select_from(billing_usage_orders),
                ),
            ),
            int(
                conn.scalar(
                    select(func.count()).select_from(open_api_invocations),
                ),
            ),
        )


@pytest.mark.integration
def test_postgresql_open_api_same_key_and_payload_drift(
    postgres_open_api_engine,
):
    identity = "success"
    coordinator = _coordinator(postgres_open_api_engine, identity)
    same_start = Barrier(2)

    def same_key():
        same_start.wait()
        return coordinator.begin_invocation(
            _command(identity, "postgres-same"),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        same_sessions = list(pool.map(lambda _index: same_key(), range(2)))
    assert same_sessions[0] == same_sessions[1]

    drift_start = Barrier(2)

    def drift(message: str):
        drift_start.wait()
        try:
            return coordinator.begin_invocation(
                _command(identity, "postgres-drift", message),
            )
        except IdempotencyConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        drift_results = list(pool.map(drift, ("first", "changed")))
    assert drift_results.count("conflict") == 1


@pytest.mark.integration
def test_postgresql_invocation_execution_claim_has_one_winner(
    postgres_open_api_engine,
):
    identity = "execution-claim"
    coordinator = _coordinator(postgres_open_api_engine, identity)
    session = coordinator.begin_invocation(
        _command(identity, "postgres-execution-claim"),
    )
    repository = SqlAlchemyOpenApiRepository(postgres_open_api_engine)
    start = Barrier(8)

    def claim(index: int):
        start.wait()
        return repository.claim_invocation_execution(
            session.invocation_id,
            f"worker-{index}",
            lease_seconds=30,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, range(8)))

    fences = [fence for fence in results if fence is not None]
    assert len(fences) == 1
    assert fences[0].generation == 1
    invocation = repository.get_invocation(session.invocation_id)
    assert invocation is not None
    assert invocation["status"] == "running"
    assert invocation["execution_owner_token"].startswith("worker-")
    assert invocation["execution_claimed_at"] is not None
    assert invocation["execution_lease_expires_at"] > datetime.now(
        timezone.utc
    )


@pytest.mark.integration
def test_postgresql_expired_execution_lease_has_one_takeover_winner(
    postgres_open_api_engine,
):
    identity = "execution-takeover"
    coordinator = _coordinator(postgres_open_api_engine, identity)
    session = coordinator.begin_invocation(
        _command(identity, "postgres-execution-takeover"),
    )
    repository = SqlAlchemyOpenApiRepository(postgres_open_api_engine)
    original_fence = repository.claim_invocation_execution(
        session.invocation_id,
        "original-worker",
        lease_seconds=30,
    )
    assert original_fence is not None
    assert (
        repository.takeover_invocation_execution(
            session.invocation_id,
            "premature-worker",
            lease_seconds=60,
        )
        is None
    )
    now = datetime.now(timezone.utc)
    with postgres_open_api_engine.begin() as conn:
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == session.invocation_id)
            .values(execution_lease_expires_at=now - timedelta(seconds=1)),
        )
    start = Barrier(8)

    def takeover(index: int):
        start.wait()
        return SqlAlchemyOpenApiRepository(
            postgres_open_api_engine,
        ).takeover_invocation_execution(
            session.invocation_id,
            f"replacement-{index}",
            lease_seconds=30,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(takeover, range(8)))
    fences = [fence for fence in results if fence is not None]
    assert len(fences) == 1
    winner_fence = fences[0]
    assert winner_fence.generation == 2
    invocation = repository.get_invocation(session.invocation_id)
    winner = str(invocation["execution_owner_token"])
    assert (
        repository.finalize_invocation_execution(
            session.invocation_id,
            original_fence,
            status="failed",
            status_code=500,
            error_summary="stale",
            terminal_event={"type": "billing.completed", "winner": "stale"},
        )
        is None
    )
    sealed = repository.finalize_invocation_execution(
        session.invocation_id,
        winner_fence,
        status="succeeded",
        status_code=200,
        error_summary="",
        terminal_event={"type": "billing.completed", "winner": winner},
    )
    assert sealed is not None
    assert sealed["terminal_event_json"]["winner"] == winner
    assert sealed["execution_owner_token"] is None


@pytest.mark.integration
def test_postgresql_db_clock_and_fence_reject_late_provider_capture(
    postgres_open_api_engine,
    monkeypatch,
):
    identity = "late-provider-fence"
    coordinator = _coordinator(postgres_open_api_engine, identity)
    session = coordinator.begin_invocation(
        _command(identity, "postgres-late-provider", mode="enforced"),
    )
    coordinator.repository.grant(
        session.wallet_id,
        credits=5,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="late-provider-funds",
    )
    repository = SqlAlchemyOpenApiRepository(postgres_open_api_engine)
    old_fence = repository.claim_invocation_execution(
        session.invocation_id,
        "clock-skewed-worker",
        lease_seconds=30,
    )
    assert old_fence is not None
    import qwenpaw.app.storage.repos.open_api_repo as repo_module

    monkeypatch.setattr(
        repo_module,
        "_now",
        lambda: datetime.now(timezone.utc) + timedelta(days=365),
    )
    assert (
        repository.takeover_invocation_execution(
            session.invocation_id,
            "premature",
            lease_seconds=30,
        )
        is None
    )

    service = UsageService(coordinator.repository, coordinator.pricing)
    fields = {
        "invocation_id": session.invocation_id,
        "execution_fence": old_fence,
    }
    service.reserve_model_call(
        ReserveModelCall(
            usage_order_id=session.usage_order_id,
            item_key="late-call",
            provider_id="provider",
            model_key="model",
            capability="text",
            parameters={"tier": "standard"},
            input_tokens=1000,
            max_output_tokens=0,
            **fields,
        ),
    )
    service.settle_model_call(
        SettleModelCall(
            usage_order_id=session.usage_order_id,
            item_key="late-call",
            supplier_reference="",
            billability="unknown",
            execution_outcome="pending",
            evidence={"response_class": "provider_call_started"},
            **fields,
        ),
    )
    with postgres_open_api_engine.begin() as conn:
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == session.invocation_id)
            .values(
                execution_lease_expires_at=datetime.now(timezone.utc)
                - timedelta(seconds=1),
            ),
        )
    winner = repository.takeover_invocation_execution(
        session.invocation_id,
        "winner",
        lease_seconds=30,
    )
    assert winner is not None and winner.generation == 2
    terminal = {"type": "billing.interrupted", "winner": "winner"}
    assert repository.finalize_invocation_execution(
        session.invocation_id,
        winner,
        status="failed",
        status_code=500,
        error_summary="recovered",
        terminal_event=terminal,
    )
    with pytest.raises(BillingExecutionFencedError):
        service.settle_model_call(
            SettleModelCall(
                usage_order_id=session.usage_order_id,
                item_key="late-call",
                supplier_reference="supplier-late",
                billability="billable",
                evidence={"response_class": "success"},
                actual_input_tokens=1000,
                actual_output_tokens=0,
                **fields,
            ),
        )
    assert service.list_items(session.usage_order_id)[0]["status"] == (
        "reconciling"
    )
    assert (
        repository.get_invocation(session.invocation_id)["terminal_event_json"]
        == terminal
    )


@pytest.mark.integration
def test_postgresql_legacy_bridge_schema_adds_execution_state(
    postgres_open_api_engine,
):
    identity = "legacy-execution-outcome"
    session = _coordinator(
        postgres_open_api_engine,
        identity,
    ).begin_invocation(
        _command(identity, "legacy-execution-outcome"),
    )
    with postgres_open_api_engine.begin() as conn:
        conn.execute(
            billing_usage_items.insert(),
            [
                {
                    "id": "legacy-captured",
                    "usage_order_id": session.usage_order_id,
                    "item_key": "captured",
                    "status": "captured",
                    "provider_id": "provider",
                    "model_key": "model",
                    "capability": "chat",
                    "supplier_evidence_json": "{}",
                    "execution_outcome": "pending",
                },
                {
                    "id": "legacy-released",
                    "usage_order_id": session.usage_order_id,
                    "item_key": "released",
                    "status": "released",
                    "provider_id": "provider",
                    "model_key": "model",
                    "capability": "chat",
                    "supplier_evidence_json": "{}",
                    "execution_outcome": "pending",
                },
                {
                    "id": "legacy-recon-success",
                    "usage_order_id": session.usage_order_id,
                    "item_key": "recon-success",
                    "status": "reconciling",
                    "provider_id": "provider",
                    "model_key": "model",
                    "capability": "chat",
                    "supplier_evidence_json": '{"response_class":"success"}',
                    "execution_outcome": "pending",
                },
                {
                    "id": "legacy-recon-pending",
                    "usage_order_id": session.usage_order_id,
                    "item_key": "recon-pending",
                    "status": "reconciling",
                    "provider_id": "provider",
                    "model_key": "model",
                    "capability": "chat",
                    "supplier_evidence_json": (
                        '{"response_class":"provider_call_started"}'
                    ),
                    "execution_outcome": "pending",
                },
            ],
        )
        conn.execute(
            text(
                "ALTER TABLE billing_usage_items DROP CONSTRAINT "
                "ck_billing_usage_items_execution_outcome",
            ),
        )
        conn.execute(
            text(
                "ALTER TABLE billing_usage_items "
                "DROP COLUMN execution_outcome",
            ),
        )
        for column in (
            "execution_owner_token",
            "execution_claimed_at",
            "execution_lease_expires_at",
            "execution_fence_generation",
            "expert_team_run_id",
            "terminal_event_json",
        ):
            conn.execute(
                text(
                    "ALTER TABLE open_api_invocations DROP COLUMN "
                    f"IF EXISTS {column}",
                ),
            )

    ensure_columns = getattr(
        schema_module,
        "_ensure_open_api_billing_columns",
    )
    ensure_columns(postgres_open_api_engine)
    ensure_columns(postgres_open_api_engine)

    inspector = inspect(postgres_open_api_engine)
    invocation_columns = {
        column["name"]
        for column in inspector.get_columns("open_api_invocations")
    }
    assert {
        "execution_owner_token",
        "execution_claimed_at",
        "execution_lease_expires_at",
        "execution_fence_generation",
        "expert_team_run_id",
        "terminal_event_json",
    } <= invocation_columns
    item_columns = {
        column["name"]
        for column in inspector.get_columns("billing_usage_items")
    }
    assert "execution_outcome" in item_columns
    with postgres_open_api_engine.connect() as conn:
        assert (
            conn.scalar(
                text(
                    "SELECT execution_fence_generation FROM "
                    "open_api_invocations WHERE id = :invocation_id",
                ),
                {"invocation_id": session.invocation_id},
            )
            == 0
        )
        outcomes = dict(
            conn.execute(
                text(
                    "SELECT id, execution_outcome FROM billing_usage_items "
                    "WHERE id LIKE 'legacy-%'",
                ),
            ).all(),
        )
    assert outcomes == {
        "legacy-captured": "succeeded",
        "legacy-recon-pending": "pending",
        "legacy-recon-success": "succeeded",
        "legacy-released": "failed",
    }


@pytest.mark.integration
def test_postgresql_open_api_injected_failure_rolls_back_fresh_identity(
    postgres_open_api_engine,
):
    identity = "rollback"
    coordinator = _coordinator(postgres_open_api_engine, identity)
    failing = OpenApiBillingCoordinator(
        coordinator.repository,
        coordinator.pricing,
        after_order_insert=lambda: (_ for _ in ()).throw(
            RuntimeError("injected"),
        ),
    )
    with pytest.raises(RuntimeError, match="injected"):
        failing.begin_invocation(_command(identity, "postgres-rollback"))
    assert _billing_counts(postgres_open_api_engine) == (0, 0, 0)


@pytest.mark.integration
def test_postgresql_open_api_missing_catalog_is_controlled(
    postgres_open_api_engine,
):
    identity = "missing-catalog"
    coordinator = _coordinator(
        postgres_open_api_engine,
        identity,
        publish_catalog=False,
    )

    with pytest.raises(CatalogNotReadyError):
        coordinator.begin_invocation(
            _command(identity, "postgres-missing-catalog"),
        )
    assert _billing_counts(postgres_open_api_engine) == (0, 0, 0)


@pytest.mark.integration
def test_postgresql_capture_and_release_cannot_both_settle_one_item(
    postgres_open_api_engine,
):
    identity = "settlement-race"
    coordinator = _coordinator(postgres_open_api_engine, identity)
    session = coordinator.begin_invocation(
        _command(identity, "settlement", mode="enforced"),
    )
    coordinator.repository.grant(
        session.wallet_id,
        credits=5,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="settlement-funds",
    )
    service = UsageService(coordinator.repository, coordinator.pricing)
    execution_fence = SqlAlchemyOpenApiRepository(
        postgres_open_api_engine,
    ).claim_invocation_execution(
        session.invocation_id,
        "settlement-worker",
        lease_seconds=300,
    )
    assert execution_fence is not None
    reserve = ReserveModelCall(
        usage_order_id=session.usage_order_id,
        item_key="call-1",
        provider_id="provider",
        model_key="model",
        capability="text",
        parameters={"tier": "standard"},
        input_tokens=1000,
        max_output_tokens=0,
        invocation_id=session.invocation_id,
        execution_fence=execution_fence,
    )
    service.reserve_model_call(reserve)
    start = Barrier(2)

    def settle(billability: str):
        start.wait()
        try:
            return service.settle_model_call(
                SettleModelCall(
                    usage_order_id=session.usage_order_id,
                    item_key="call-1",
                    supplier_reference="supplier-call-1",
                    billability=billability,
                    evidence={"reference": "supplier-call-1"},
                    actual_input_tokens=1000,
                    actual_output_tokens=0,
                    invocation_id=session.invocation_id,
                    execution_fence=execution_fence,
                ),
            ).status
        except UsageOrderConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(settle, ("billable", "not_billable")))

    assert outcomes.count("conflict") == 1
    assert set(outcomes) in (
        {"conflict", "captured"},
        {"conflict", "released"},
    )
    assert coordinator.repository.balance(session.wallet_id).held == 0


@pytest.mark.integration
def test_postgresql_restart_recovery_is_idempotent_and_preserves_unknown(
    postgres_open_api_engine,
):
    identity = "restart-recovery"
    coordinator = _coordinator(postgres_open_api_engine, identity)
    session = coordinator.begin_invocation(
        _command(identity, "restart", mode="enforced"),
    )
    coordinator.repository.grant(
        session.wallet_id,
        credits=5,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="restart-funds",
    )
    service = UsageService(coordinator.repository, coordinator.pricing)
    execution_fence = SqlAlchemyOpenApiRepository(
        postgres_open_api_engine,
    ).claim_invocation_execution(
        session.invocation_id,
        "restart-worker",
        lease_seconds=300,
    )
    assert execution_fence is not None
    service.reserve_model_call(
        ReserveModelCall(
            usage_order_id=session.usage_order_id,
            item_key="precontact",
            provider_id="provider",
            model_key="model",
            capability="text",
            parameters={"tier": "standard"},
            input_tokens=1000,
            max_output_tokens=0,
            invocation_id=session.invocation_id,
            execution_fence=execution_fence,
        ),
    )
    with postgres_open_api_engine.begin() as conn:
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == session.invocation_id)
            .values(
                execution_lease_expires_at=datetime.now(timezone.utc)
                - timedelta(seconds=1),
            ),
        )
    runtime = OpenApiBillingRuntime(
        repository=coordinator.repository,
        pricing=coordinator.pricing,
        coordinator=coordinator,
        usage_service=service,
        open_api_repository=SqlAlchemyOpenApiRepository(
            postgres_open_api_engine,
        ),
        mode="enforced",
        budget_credits=100,
    )

    recover_open_api_billing(runtime)
    first_ledger = coordinator.repository.list_ledger(
        session.wallet_id,
        100,
        None,
    )
    recover_open_api_billing(runtime)

    assert (
        service.list_items(session.usage_order_id)[0]["status"] == "released"
    )
    assert len(
        coordinator.repository.list_ledger(session.wallet_id, 100, None),
    ) == len(first_ledger)
    assert coordinator.repository.balance(session.wallet_id).held == 0
    invocation = runtime.open_api_repository.get_invocation(
        session.invocation_id,
    )
    assert invocation is not None
    assert invocation["status"] == "failed"
    assert invocation["billing_status"] == "settled"
