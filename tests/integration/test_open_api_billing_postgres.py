# -*- coding: utf-8 -*-
"""Live PostgreSQL concurrency coverage for OpenAPI billing sessions."""
# pylint: disable=redefined-outer-name
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Lock, current_thread
from uuid import uuid4

import pytest
from sqlalchemy import (
    create_engine,
    event,
    func,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.exc import DBAPIError
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
from qwenpaw.app.billing.reporting import (
    BillingReportFilters,
    BillingReportingService,
    ReconciliationResolution,
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
    billing_reconciliation_audits,
    billing_ledger_entries,
    billing_rollout_settings,
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


@pytest.mark.integration
def test_postgresql_reporting_schema_upgrades_existing_database(
    postgres_open_api_engine,
):
    billing_reconciliation_audits.drop(postgres_open_api_engine)
    billing_rollout_settings.drop(postgres_open_api_engine)

    create_all(postgres_open_api_engine)
    create_all(postgres_open_api_engine)

    tables = set(inspect(postgres_open_api_engine).get_table_names())
    assert {
        "billing_reconciliation_audits",
        "billing_rollout_settings",
    } <= tables
    invocation_indexes = {
        index["name"]
        for index in inspect(postgres_open_api_engine).get_indexes(
            "open_api_invocations",
        )
    }
    assert "idx_open_api_invocations_billing_usage_order" in invocation_indexes


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
        timezone.utc,
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
def test_postgresql_stale_empty_finalizer_cannot_change_takeover_winner(
    postgres_open_api_engine,
):
    identity = "stale-empty-finalizer"
    coordinator = _coordinator(postgres_open_api_engine, identity)
    session = coordinator.begin_invocation(
        _command(identity, "postgres-stale-empty", mode="enforced"),
    )
    coordinator.repository.grant(
        session.wallet_id,
        credits=5,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="stale-empty-funds",
    )
    ledger_count = len(
        coordinator.repository.list_ledger(session.wallet_id, 100, None),
    )
    repository = SqlAlchemyOpenApiRepository(postgres_open_api_engine)
    old_fence = repository.claim_invocation_execution(
        session.invocation_id,
        "stale-empty-owner",
        lease_seconds=30,
    )
    assert old_fence is not None
    with postgres_open_api_engine.begin() as conn:
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == session.invocation_id)
            .values(
                execution_lease_expires_at=datetime.now(timezone.utc)
                - timedelta(seconds=1),
            ),
        )
    winner_fence = repository.takeover_invocation_execution(
        session.invocation_id,
        "empty-finalize-winner",
        lease_seconds=30,
    )
    assert winner_fence is not None
    with postgres_open_api_engine.begin() as conn:
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == session.invocation_id)
            .values(billing_status="reconciling"),
        )
    winner_terminal = {
        "type": "billing.interrupted",
        "billing_status": "reconciling",
        "winner": "empty-finalize-winner",
    }
    start = Barrier(2)

    def stale_finalize():
        start.wait()
        return SqlAlchemyOpenApiRepository(
            postgres_open_api_engine,
        ).finalize_empty_invocation_execution(
            session.invocation_id,
            session.usage_order_id,
            old_fence,
            status="failed",
            status_code=500,
            error_summary="stale",
            terminal_event={"type": "billing.completed", "winner": "stale"},
        )

    def winner_finalize():
        start.wait()
        return SqlAlchemyOpenApiRepository(
            postgres_open_api_engine,
        ).finalize_invocation_execution(
            session.invocation_id,
            winner_fence,
            status="failed",
            status_code=500,
            error_summary="recovered",
            billing_status="reconciling",
            terminal_event=winner_terminal,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        stale_result, winner_result = list(
            pool.map(lambda call: call(), (stale_finalize, winner_finalize)),
        )

    assert stale_result is None
    assert winner_result is not None
    invocation = repository.get_invocation(session.invocation_id)
    assert invocation["billing_status"] == "reconciling"
    assert invocation["terminal_event_json"] == winner_terminal
    with postgres_open_api_engine.connect() as conn:
        order_status = conn.scalar(
            select(billing_usage_orders.c.status).where(
                billing_usage_orders.c.id == session.usage_order_id,
            ),
        )
        item_count = conn.scalar(
            select(func.count())
            .select_from(billing_usage_items)
            .where(
                billing_usage_items.c.usage_order_id == session.usage_order_id,
            ),
        )
    assert order_status == "quoted"
    assert item_count == 0
    assert (
        len(coordinator.repository.list_ledger(session.wallet_id, 100, None))
        == ledger_count
    )


@pytest.mark.integration
def test_postgresql_empty_finalize_has_one_current_fence_winner(
    postgres_open_api_engine,
):
    identity = "empty-finalize-race"
    coordinator = _coordinator(postgres_open_api_engine, identity)
    session = coordinator.begin_invocation(
        _command(identity, "postgres-empty-race", mode="enforced"),
    )
    coordinator.repository.grant(
        session.wallet_id,
        credits=5,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="empty-race-funds",
    )
    ledger_count = len(
        coordinator.repository.list_ledger(session.wallet_id, 100, None),
    )
    repository = SqlAlchemyOpenApiRepository(postgres_open_api_engine)
    old_fence = repository.claim_invocation_execution(
        session.invocation_id,
        "empty-race-stale",
        lease_seconds=30,
    )
    assert old_fence is not None
    with postgres_open_api_engine.begin() as conn:
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == session.invocation_id)
            .values(
                execution_lease_expires_at=datetime.now(timezone.utc)
                - timedelta(seconds=1),
            ),
        )
    winner_fence = repository.takeover_invocation_execution(
        session.invocation_id,
        "empty-race-winner",
        lease_seconds=30,
    )
    assert winner_fence is not None
    winner_terminal = {
        "type": "billing.completed",
        "billing_status": "settled",
        "winner": "empty-race-winner",
    }
    start = Barrier(2)

    def finalize(fence, terminal):
        start.wait()
        return SqlAlchemyOpenApiRepository(
            postgres_open_api_engine,
        ).finalize_empty_invocation_execution(
            session.invocation_id,
            session.usage_order_id,
            fence,
            status="failed",
            status_code=500,
            error_summary=str(terminal["winner"]),
            terminal_event=terminal,
        )

    stale_terminal = {
        "type": "billing.completed",
        "billing_status": "settled",
        "winner": "empty-race-stale",
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        stale_result, winner_result = list(
            pool.map(
                lambda pair: finalize(*pair),
                (
                    (old_fence, stale_terminal),
                    (winner_fence, winner_terminal),
                ),
            ),
        )

    assert stale_result is None
    assert winner_result is not None
    invocation = repository.get_invocation(session.invocation_id)
    assert invocation["billing_status"] == "settled"
    assert invocation["terminal_event_json"] == winner_terminal
    with postgres_open_api_engine.connect() as conn:
        assert (
            conn.scalar(
                select(billing_usage_orders.c.status).where(
                    billing_usage_orders.c.id == session.usage_order_id,
                ),
            )
            == "settled"
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(billing_usage_items)
                .where(
                    billing_usage_items.c.usage_order_id
                    == session.usage_order_id,
                ),
            )
            == 0
        )
    assert (
        len(coordinator.repository.list_ledger(session.wallet_id, 100, None))
        == ledger_count
    )


@pytest.mark.integration
def test_postgresql_empty_finalize_does_not_deadlock_late_reserve(
    postgres_open_api_engine,
):  # pylint: disable=too-many-statements
    """Empty finalization and reservation share order -> invocation locks."""
    identity = "empty-finalize-reserve-lock-order"
    coordinator = _coordinator(postgres_open_api_engine, identity)
    session = coordinator.begin_invocation(
        _command(identity, "postgres-empty-finalize-reserve", mode="enforced"),
    )
    coordinator.repository.grant(
        session.wallet_id,
        credits=5,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="empty-finalize-reserve-funds",
    )
    ledger_count = len(
        coordinator.repository.list_ledger(session.wallet_id, 100, None),
    )
    repository = SqlAlchemyOpenApiRepository(postgres_open_api_engine)
    winner_fence = repository.claim_invocation_execution(
        session.invocation_id,
        "current-finalizer",
        lease_seconds=30,
    )
    assert winner_fence is not None
    terminal = {
        "type": "billing.completed",
        "billing_status": "settled",
        "winner": "current-finalizer",
    }
    allow_reserve_order = Event()
    reserve_at_order = Event()
    reserve_locked_order = Event()
    reserve_at_invocation = Event()
    finalizer_locked_invocation = Event()
    reserve_backend_pid: list[int] = []

    def before_lock_statement(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        normalized = " ".join(statement.lower().split())
        if (
            current_thread().name == "late-reserve"
            and normalized.startswith("select")
            and "from billing_usage_orders" in normalized
            and "for update" in normalized
        ):
            reserve_at_order.set()
            if not allow_reserve_order.wait(timeout=5):
                raise RuntimeError("finalizer did not choose its first lock")
        elif current_thread().name == "late-reserve" and normalized.startswith(
            "update open_api_invocations",
        ):
            reserve_backend_pid.append(_cursor.connection.info.backend_pid)
            _cursor.execute("SET LOCAL deadlock_timeout = '5s'")
            reserve_at_invocation.set()
        elif (
            current_thread().name == "current-finalizer"
            and normalized.startswith("select")
            and "from billing_usage_orders" in normalized
            and "for update" in normalized
        ):
            _cursor.execute("SET LOCAL deadlock_timeout = '100ms'")
            if not finalizer_locked_invocation.is_set():
                return
            allow_reserve_order.set()
            if not reserve_locked_order.wait(timeout=5):
                raise RuntimeError("reserve did not acquire the order lock")
            if not reserve_at_invocation.wait(timeout=5):
                raise RuntimeError("reserve did not reach the invocation lock")
            wait_type = None
            for _attempt in range(200):
                with postgres_open_api_engine.connect() as observer:
                    wait_type = observer.scalar(
                        text(
                            "SELECT wait_event_type FROM pg_stat_activity "
                            "WHERE pid = :pid",
                        ),
                        {"pid": reserve_backend_pid[0]},
                    )
                if wait_type == "Lock":
                    break
                reserve_at_invocation.wait(timeout=0.01)
            if wait_type != "Lock":
                raise RuntimeError("reserve did not block on the invocation")

    def after_lock_statement(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        normalized = " ".join(statement.lower().split())
        if (
            current_thread().name == "late-reserve"
            and normalized.startswith("select")
            and "from billing_usage_orders" in normalized
            and "for update" in normalized
        ):
            reserve_locked_order.set()
        elif (
            current_thread().name == "current-finalizer"
            and normalized.startswith("update open_api_invocations")
        ):
            finalizer_locked_invocation.set()
        elif (
            current_thread().name == "current-finalizer"
            and normalized.startswith("select")
            and "from billing_usage_orders" in normalized
            and "for update" in normalized
        ):
            allow_reserve_order.set()

    event.listen(
        postgres_open_api_engine,
        "before_cursor_execute",
        before_lock_statement,
    )
    event.listen(
        postgres_open_api_engine,
        "after_cursor_execute",
        after_lock_statement,
    )

    def late_reserve():
        current_thread().name = "late-reserve"
        try:
            UsageService(
                coordinator.repository,
                coordinator.pricing,
            ).reserve_model_call(
                ReserveModelCall(
                    usage_order_id=session.usage_order_id,
                    item_key="late-reserve",
                    provider_id="provider",
                    model_key="model",
                    capability="text",
                    parameters={"tier": "standard"},
                    input_tokens=1000,
                    max_output_tokens=0,
                    invocation_id=session.invocation_id,
                    execution_fence=winner_fence,
                ),
            )
        except Exception as exc:
            return exc
        return None

    def current_finalize():
        current_thread().name = "current-finalizer"
        try:
            return SqlAlchemyOpenApiRepository(
                postgres_open_api_engine,
            ).finalize_empty_invocation_execution(
                session.invocation_id,
                session.usage_order_id,
                winner_fence,
                status="succeeded",
                status_code=200,
                error_summary="",
                terminal_event=terminal,
            )
        except Exception as exc:  # return both worker outcomes for assertions
            return exc

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            reserve_future = pool.submit(late_reserve)
            assert reserve_at_order.wait(timeout=5)
            finalize_future = pool.submit(current_finalize)
            reserve_result = reserve_future.result(timeout=10)
            finalize_result = finalize_future.result(timeout=10)
    finally:
        event.remove(
            postgres_open_api_engine,
            "before_cursor_execute",
            before_lock_statement,
        )
        event.remove(
            postgres_open_api_engine,
            "after_cursor_execute",
            after_lock_statement,
        )

    assert not isinstance(finalize_result, Exception), (
        finalize_result,
        repository.get_invocation(session.invocation_id)[
            "terminal_event_json"
        ],
    )
    assert finalize_result is not None
    assert isinstance(reserve_result, BillingExecutionFencedError)
    assert finalize_result["terminal_event_json"] == terminal
    invocation = repository.get_invocation(session.invocation_id)
    assert invocation is not None
    assert invocation["terminal_event_json"] == terminal
    with postgres_open_api_engine.connect() as conn:
        assert (
            conn.scalar(
                select(billing_usage_orders.c.status).where(
                    billing_usage_orders.c.id == session.usage_order_id,
                ),
            )
            == "settled"
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(billing_usage_items)
                .where(
                    billing_usage_items.c.usage_order_id
                    == session.usage_order_id,
                ),
            )
            == 0
        )
    assert (
        len(coordinator.repository.list_ledger(session.wallet_id, 100, None))
        == ledger_count
    )


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
        conn.execute(
            text(
                "ALTER TABLE billing_usage_items "
                "DROP COLUMN reconciliation_id",
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
    assert {"execution_outcome", "reconciliation_id"} <= item_columns
    invocation_indexes = {
        index["name"]
        for index in inspect(postgres_open_api_engine).get_indexes(
            "open_api_invocations",
        )
    }
    assert "idx_open_api_invocations_billing_usage_order" in invocation_indexes
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
def test_postgresql_admin_reconciliation_same_key_is_one_audited_capture(
    postgres_open_api_engine,
):
    identity = "admin-reconciliation"
    coordinator = _coordinator(postgres_open_api_engine, identity)
    session = coordinator.begin_invocation(
        _command(identity, "admin-reconciliation", mode="enforced"),
    )
    coordinator.repository.grant(
        session.wallet_id,
        credits=5,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="admin-reconciliation-funds",
    )
    usage = UsageService(coordinator.repository, coordinator.pricing)
    execution_fence = SqlAlchemyOpenApiRepository(
        postgres_open_api_engine,
    ).claim_invocation_execution(
        session.invocation_id,
        "admin-reconciliation-worker",
        lease_seconds=300,
    )
    assert execution_fence is not None
    usage.reserve_model_call(
        ReserveModelCall(
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
        ),
    )
    usage.settle_model_call(
        SettleModelCall(
            usage_order_id=session.usage_order_id,
            item_key="call-1",
            supplier_reference="",
            billability="unknown",
            evidence={"response_class": "ambiguous"},
            execution_outcome="pending",
            invocation_id=session.invocation_id,
            execution_fence=execution_fence,
        ),
    )
    reporting = BillingReportingService(
        coordinator.repository,
        coordinator.pricing,
    )
    reconciliation_id = reporting.list_reconciliation(
        filters=BillingReportFilters(),
        limit=10,
    )["items"][0]["reconciliation_id"]
    resolution = ReconciliationResolution(
        idempotency_key="admin-reconciliation-resolution",
        billability="billable",
        reason="Supplier invoice confirms the usage.",
        actual_input_tokens=1000,
        actual_output_tokens=0,
    )
    start = Barrier(2)

    def resolve():
        start.wait()
        return reporting.resolve_reconciliation(
            reconciliation_id,
            actor_id="admin-postgres",
            resolution=resolution,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _value: resolve(), range(2)))

    assert results[0] == results[1]
    with postgres_open_api_engine.connect() as conn:
        assert (
            conn.scalar(
                select(func.count()).select_from(
                    billing_reconciliation_audits,
                ),
            )
            == 1
        )
        assert (
            conn.scalar(
                select(func.count())
                .select_from(billing_ledger_entries)
                .where(billing_ledger_entries.c.event_type == "usage_capture"),
            )
            == 1
        )
    with pytest.raises(DBAPIError):
        with postgres_open_api_engine.begin() as conn:
            conn.execute(
                update(billing_reconciliation_audits).values(
                    reason="forbidden rewrite",
                ),
            )
    assert coordinator.repository.balance(session.wallet_id).held == 0
    boundary = datetime(2026, 8, 29, 23, 30, tzinfo=timezone.utc)
    with postgres_open_api_engine.begin() as conn:
        conn.execute(text("SET TIME ZONE 'Asia/Shanghai'"))
        conn.execute(
            update(billing_usage_orders)
            .where(billing_usage_orders.c.id == session.usage_order_id)
            .values(created_at=boundary),
        )
    summary = reporting.open_api_summary(
        f"bound-user-{identity}",
        date_from=boundary.date(),
        date_to=boundary.date() + timedelta(days=1),
    )
    assert summary["totals"]["orders"] == 1
    assert summary["totals"]["model_calls"] == 1
    assert summary["totals"]["actual_debited_credits"] == 1
    assert summary["by_day"][0]["date"] == "2026-08-29"


@pytest.mark.integration
def test_postgresql_first_enforced_rollout_activation_is_one_cutover_cas(
    postgres_open_api_engine,
):
    repository = BillingRepository(postgres_open_api_engine)
    pricing = PriceCatalogService(
        PriceCatalogRepository(postgres_open_api_engine),
    )
    reporting = BillingReportingService(repository, pricing)
    reads = Barrier(2)
    read_lock = Lock()
    synchronized = 0

    def synchronize_empty_reads(
        _conn,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        nonlocal synchronized
        if (
            statement.lstrip().upper().startswith("SELECT")
            and "FROM billing_rollout_settings" in statement
        ):
            with read_lock:
                if synchronized >= 2:
                    return
                synchronized += 1
            reads.wait(timeout=5)

    event.listen(
        postgres_open_api_engine,
        "before_cursor_execute",
        synchronize_empty_reads,
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda actor: reporting.activate_rollout(
                        "enforced",
                        actor_id=actor,
                    ),
                    ("admin-a", "admin-b"),
                ),
            )
    finally:
        event.remove(
            postgres_open_api_engine,
            "before_cursor_execute",
            synchronize_empty_reads,
        )

    assert results[0]["billing_cutover_at"] == results[1]["billing_cutover_at"]
    assert {result["cutover_actor_id"] for result in results} in (
        {"admin-a"},
        {"admin-b"},
    )


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
