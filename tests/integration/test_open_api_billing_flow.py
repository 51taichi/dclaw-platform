"""Router-level OpenAPI billing flow integration coverage."""
from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from agentscope.model._model_usage import ChatUsage
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, insert, select, update

from qwenpaw.app.billing.open_api import (
    OpenApiBillingCommand,
    OpenApiBillingCoordinator,
)
from qwenpaw.app.billing.pricing import (
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
)
from qwenpaw.app.billing.supplier_reference_sidecar import (
    stash_supplier_reference,
)
from qwenpaw.app.billing.usage import (
    BillingExecutionFencedError,
    ReserveModelCall,
    SettleModelCall,
    UsageService,
)
from qwenpaw.app.open_api.runtime import (
    OpenApiBillingRuntime,
    get_current_billing_meter,
    recover_open_api_billing,
)
from qwenpaw.app.routers import open_api
from qwenpaw.app.runner.task_tracker import TaskTracker
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.billing_repo import BillingRepository
from qwenpaw.app.storage.repos.open_api_repo import SqlAlchemyOpenApiRepository
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository
from qwenpaw.app.storage.schema import (
    billing_price_catalogs,
    billing_price_rules,
    billing_usage_items,
    billing_usage_orders,
    create_all,
    open_api_invocations,
    open_api_publications,
    users,
)
from qwenpaw.app.storage.settings import get_storage_settings
from qwenpaw.app.task_limits import TaskConcurrencyLimiter


class _Response:
    def __init__(
        self,
        reference: str,
        input_tokens: int = 1,
        output_tokens: int = 1,
    ):
        self.usage = ChatUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            time=0.01,
        )
        stash_supplier_reference(self, reference, "provider_response")


class _SupplierConsole:
    def __init__(
        self,
        *,
        calls_per_run: int = 1,
        block_after_first: asyncio.Event | None = None,
        omit_reference: bool = False,
    ):
        self.calls_per_run = calls_per_run
        self.calls = 0
        self.block_after_first = block_after_first
        self.omit_reference = omit_reference

    async def stream_one(self, payload):
        del payload
        meter = get_current_billing_meter()
        assert meter is not None
        for index in range(self.calls_per_run):
            call = meter.before_call(
                provider_id="provider",
                model_key="model",
                messages=[{"role": "user", "content": "hello"}],
                max_output_tokens=1,
            )
            meter.mark_provider_call_started(call)
            self.calls += 1
            response = _Response(
                "" if self.omit_reference else f"supplier-{self.calls}",
            )
            meter.record_response(call, response)
            yield f"data: {json.dumps({'step': index + 1})}\n\n"
            if index == 0 and self.block_after_first is not None:
                await self.block_after_first.wait()


class _Channels:
    def __init__(self, console):
        self.console = console

    async def get_channel(self, name):
        return self.console if name == "console" else None


class _CancelResistantLateResponseConsole:
    def __init__(self):
        self.started = asyncio.Event()
        self.calls = 0

    async def stream_one(self, payload):
        del payload
        meter = get_current_billing_meter()
        assert meter is not None
        call = meter.before_call(
            provider_id="provider",
            model_key="model",
            messages=[{"role": "user", "content": "late"}],
            max_output_tokens=1,
        )
        meter.mark_provider_call_started(call)
        self.calls += 1
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        meter.record_response(call, _Response("supplier-late"))
        yield "data: {}\n\n"


class _Chats:
    async def get_or_create_chat(self, *_args, **_kwargs):
        return SimpleNamespace(id="chat-1")


class _Manager:
    def __init__(self, workspace):
        self.workspace = workspace

    async def get_agent(self, *_args, **_kwargs):
        return self.workspace


def _events(response) -> list[dict]:
    result = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            value = json.loads(line[6:])
            if isinstance(value, dict):
                result.append(value)
    return result


async def _consume_streaming_response(response) -> str:
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        chunks.append(
            chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk,
        )
    return "".join(chunks)


@pytest.fixture(name="billing_flow")
def _billing_flow(tmp_path, monkeypatch):
    settings = get_storage_settings(
        {"QWENPAW_SQLITE_PATH": str(tmp_path / "billing-flow.db")},
    )
    engine = create_engine_from_settings(settings)
    create_all(engine)
    open_repo = SqlAlchemyOpenApiRepository(engine)
    open_repo.upsert_publication(
        {
            "id": "publication",
            "public_id": "public-agent",
            "target_type": "agent",
            "target_id": "agent",
            "owner_user_id": "publication-owner",
            "bound_user_id": "wallet-owner",
            "name": "Agent",
        },
    )
    open_repo.create_external_app(
        {"id": "app", "owner_user_id": "app-owner", "name": "App"},
    )
    open_repo.create_api_key(
        {
            "id": "key",
            "app_id": "app",
            "publication_id": "publication",
            "key_hash": "hash",
            "key_prefix": "qp",
            "key_suffix": "test",
            "scopes": ["messages:create"],
        },
    )
    pricing = PriceCatalogService(PriceCatalogRepository(engine))
    pricing.publish(
        PriceCatalogDraft(
            version="router-v1",
            effective_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            rules=(
                PriceRule(
                    id="router-rule",
                    provider_id="provider",
                    model_key="model",
                    capability="chat",
                    unit_type="tokens",
                    input_credits_per_1k=1,
                    output_credits_per_1k=1,
                ),
            ),
        ),
    )
    billing_repo = BillingRepository(engine)
    runtime = OpenApiBillingRuntime(
        repository=billing_repo,
        pricing=pricing,
        coordinator=OpenApiBillingCoordinator(billing_repo, pricing),
        usage_service=UsageService(billing_repo, pricing, mode="enforced"),
        open_api_repository=open_repo,
        mode="enforced",
        budget_credits=100,
    )
    console = _SupplierConsole()
    workspace = SimpleNamespace(
        channel_manager=_Channels(console),
        chat_manager=_Chats(),
        task_tracker=TaskTracker(),
    )
    app = FastAPI()

    @app.middleware("http")
    async def bind_authenticated_publication(request: Request, call_next):
        request.state.user_id = "wallet-owner"
        request.state.open_app_id = "app"
        request.state.open_publication_id = "publication"
        request.state.open_api_key_id = "key"
        return await call_next(request)

    app.state.multi_agent_manager = _Manager(workspace)
    app.state.task_limiter = TaskConcurrencyLimiter(
        max_global=10,
        max_per_agent=10,
        max_per_user=10,
    )
    app.include_router(open_api.router)
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: open_repo)
    monkeypatch.setattr(
        open_api,
        "create_open_api_billing_runtime",
        lambda: runtime,
    )
    try:
        yield SimpleNamespace(
            client=TestClient(app),
            engine=engine,
            runtime=runtime,
            repository=billing_repo,
            open_repo=open_repo,
            console=console,
            workspace=workspace,
            app=app,
        )
    finally:
        engine.dispose()


def _post(flow, *, key: str | None = None, message: str = "hello"):
    headers = {"Idempotency-Key": key} if key is not None else {}
    return flow.client.post(
        "/open/v1/targets/public-agent/messages",
        headers=headers,
        json={"external_user_id": "external", "message": message},
    )


def test_initial_insufficient_balance_is_409_before_supplier(billing_flow):
    response = _post(billing_flow)

    assert response.status_code == 409
    assert response.json()["code"] == "insufficient_credits"
    assert response.headers["X-DClaw-Billing-Status"] == "insufficient_credits"
    assert response.headers["X-DClaw-Invocation-Id"]
    assert billing_flow.console.calls == 0


def test_replay_uses_one_invocation_order_and_supplier_call(billing_flow):
    wallet = billing_flow.repository.ensure_wallet("user", "wallet-owner")
    billing_flow.repository.grant(
        str(wallet["id"]),
        credits=20,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="fund",
    )

    first = _post(billing_flow, key="request-1")
    replay = _post(billing_flow, key="request-1")

    assert first.status_code == replay.status_code == 200
    assert (
        first.headers["X-DClaw-Invocation-Id"]
        == replay.headers["X-DClaw-Invocation-Id"]
    )
    assert first.headers["X-DClaw-Billing-Status"]
    assert replay.headers["X-DClaw-Billing-Status"] == "captured"
    assert billing_flow.console.calls == 1
    with billing_flow.engine.connect() as conn:
        assert len(conn.execute(select(open_api_invocations)).all()) == 1
        assert len(conn.execute(select(billing_usage_orders)).all()) == 1
        assert len(conn.execute(select(billing_usage_items)).all()) == 1
    terminal = _events(first)[-1]
    assert terminal["type"] == "billing.completed"
    assert "supplier_reference" not in terminal
    assert "supplier_evidence" not in terminal


def test_idempotency_payload_conflict_is_409_without_second_supplier_call(
    billing_flow,
):
    wallet = billing_flow.repository.ensure_wallet("user", "wallet-owner")
    billing_flow.repository.grant(
        str(wallet["id"]),
        credits=20,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="fund-conflict",
    )
    assert (
        _post(billing_flow, key="request-1", message="first").status_code
        == 200
    )

    response = _post(billing_flow, key="request-1", message="changed")

    assert response.status_code == 409
    assert response.json() == {"code": "idempotency_conflict"}
    assert billing_flow.console.calls == 1


def test_expert_style_multi_call_has_one_order_many_items_and_durable_summary(
    billing_flow,
):
    wallet = billing_flow.repository.ensure_wallet("user", "wallet-owner")
    billing_flow.repository.grant(
        str(wallet["id"]),
        credits=20,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="fund-team",
    )
    billing_flow.console.calls_per_run = 3

    response = _post(billing_flow)

    assert response.status_code == 200
    invocation_id = response.headers["X-DClaw-Invocation-Id"]
    with billing_flow.engine.connect() as conn:
        invocation = (
            conn.execute(
                select(open_api_invocations).where(
                    open_api_invocations.c.id == invocation_id,
                ),
            )
            .mappings()
            .one()
        )
        items = (
            conn.execute(
                select(billing_usage_items).where(
                    billing_usage_items.c.usage_order_id
                    == invocation["billing_usage_order_id"],
                ),
            )
            .mappings()
            .all()
        )
    assert len(items) == 3
    assert json.loads(invocation["token_summary"]) == {
        "input_tokens": 3,
        "output_tokens": 3,
        "model_calls": 3,
    }
    assert _events(response)[-1]["type"] == "billing.completed"


def test_incremental_insufficient_emits_interrupted_and_stops_supplier(
    billing_flow,
):
    wallet = billing_flow.repository.ensure_wallet("user", "wallet-owner")
    billing_flow.repository.grant(
        str(wallet["id"]),
        credits=2,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="fund-partial",
    )
    billing_flow.console.calls_per_run = 3

    response = _post(billing_flow)

    assert response.status_code == 200
    assert billing_flow.console.calls == 1
    terminal = _events(response)[-1]
    assert terminal["type"] == "billing.interrupted"
    assert terminal["code"] == "insufficient_credits"
    assert terminal["completed_steps"] == 1
    assert terminal["status"] == "partially_completed"


def test_shadow_and_observe_do_not_mutate_wallet(billing_flow):
    for mode in ("shadow", "observe"):
        billing_flow.runtime.mode = mode
        billing_flow.runtime.usage_service = UsageService(
            billing_flow.repository,
            billing_flow.runtime.pricing,
            mode=mode,
        )
        response = _post(billing_flow, key=f"{mode}-request")
        assert response.status_code == 200
    wallet = billing_flow.repository.ensure_wallet("user", "wallet-owner")
    balance = billing_flow.repository.balance(str(wallet["id"]))
    assert balance.available == balance.held == 0


def test_missing_catalog_is_503_before_supplier(billing_flow):
    with billing_flow.engine.begin() as conn:
        conn.execute(delete(billing_price_rules))
        conn.execute(delete(billing_price_catalogs))

    response = _post(billing_flow)

    assert response.status_code == 503
    assert response.json() == {"code": "catalog_not_ready"}
    assert billing_flow.console.calls == 0


@pytest.mark.parametrize("mode", ("enforced", "shadow", "observe"))
def test_overdraft_user_still_requires_published_catalog(
    billing_flow,
    mode,
):
    billing_flow.runtime.mode = mode
    billing_flow.runtime.usage_service = UsageService(
        billing_flow.repository,
        billing_flow.runtime.pricing,
        mode=mode,
    )
    with billing_flow.engine.begin() as conn:
        user_id = conn.execute(
            insert(users)
            .values(
                username="overdraft-no-catalog",
                password_hash="hash",
                password_salt="salt",
                role="admin",
                billing_overdraft_enabled=True,
            )
            .returning(users.c.id),
        ).scalar_one()
        conn.execute(
            update(open_api_publications)
            .where(open_api_publications.c.id == "publication")
            .values(bound_user_id=str(user_id)),
        )
        conn.execute(delete(billing_price_rules))
        conn.execute(delete(billing_price_catalogs))

    response = _post(billing_flow, key="overdraft-no-catalog")

    assert response.status_code == 503
    assert response.json() == {"code": "catalog_not_ready"}
    assert billing_flow.console.calls == 0


def test_published_subset_returns_model_not_priced_before_supplier(
    billing_flow,
):
    billing_flow.runtime.pricing.publish(
        PriceCatalogDraft(
            version="subset-without-runtime-model",
            effective_at=datetime.now(timezone.utc),
            rules=(
                PriceRule(
                    id="other-model-only",
                    provider_id="provider",
                    model_key="other-model",
                    capability="chat",
                    unit_type="tokens",
                    input_credits_per_1k=1,
                    output_credits_per_1k=1,
                ),
            ),
        )
    )
    wallet = billing_flow.repository.ensure_wallet("user", "wallet-owner")
    billing_flow.repository.grant(
        str(wallet["id"]),
        credits=20,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="fund-unpriced-model",
    )

    response = _post(billing_flow, key="unpriced-model-request")

    assert response.status_code == 200
    terminal = _events(response)[-1]
    assert terminal["code"] == "model_not_priced"
    assert terminal["http_status"] == 409
    assert terminal["provider_id"] == "provider"
    assert terminal["model_key"] == "model"
    assert billing_flow.console.calls == 0


def test_stale_price_source_metadata_does_not_interrupt_supplier(
    billing_flow,
):
    wallet = billing_flow.repository.ensure_wallet("user", "wallet-owner")
    billing_flow.repository.grant(
        str(wallet["id"]),
        credits=10,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="fund-stale-source-test",
    )
    with billing_flow.engine.begin() as conn:
        conn.execute(
            update(billing_price_catalogs).values(
                metadata_json=json.dumps(
                    {
                        "source_stale": True,
                        "risk_status": "high",
                    }
                ),
            )
        )

    response = _post(billing_flow, key="stale-source-still-runs")

    assert response.status_code == 200
    assert billing_flow.console.calls == 1


def test_unknown_supplier_outcome_is_reconciling_and_terminal_is_sealed(
    billing_flow,
):
    wallet = billing_flow.repository.ensure_wallet("user", "wallet-owner")
    billing_flow.repository.grant(
        str(wallet["id"]),
        credits=20,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="fund-unknown",
    )
    billing_flow.console.omit_reference = True

    response = _post(billing_flow)

    terminal = _events(response)[-1]
    assert terminal["type"] == "billing.completed"
    assert terminal["billing_status"] == "reconciling"
    assert set(terminal) == {
        "type",
        "invocation_id",
        "credits_used",
        "credits_remaining",
        "billing_status",
        "status",
        "http_status",
        "code",
        "message",
        "required_credits",
        "headers",
    }


@pytest.mark.asyncio
async def test_client_iterator_close_does_not_stop_background_finalization(
    billing_flow,
):
    wallet = billing_flow.repository.ensure_wallet("user", "wallet-owner")
    billing_flow.repository.grant(
        str(wallet["id"]),
        credits=20,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="fund-disconnect",
    )
    release_second_call = asyncio.Event()
    billing_flow.console.calls_per_run = 2
    billing_flow.console.block_after_first = release_second_call
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/open/v1/targets/public-agent/messages",
            "raw_path": b"/open/v1/targets/public-agent/messages",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("127.0.0.1", 80),
            "client": ("127.0.0.1", 1234),
            "app": billing_flow.app,
        },
    )
    request.state.user_id = "wallet-owner"
    request.state.open_app_id = "app"
    request.state.open_publication_id = "publication"
    request.state.open_api_key_id = "key"
    response = await open_api.post_open_message(
        "public-agent",
        open_api.OpenMessageRequest(
            external_user_id="external",
            message="disconnect",
        ),
        request,
    )
    first = await response.body_iterator.__anext__()
    assert "step" in str(first)

    await response.body_iterator.aclose()
    release_second_call.set()
    assert await billing_flow.workspace.task_tracker.wait_all_done(timeout=2)

    invocation_id = response.headers["X-DClaw-Invocation-Id"]
    invocation = billing_flow.open_repo.get_invocation(invocation_id)
    assert invocation is not None
    assert invocation["status"] == "succeeded"
    assert invocation["token_summary"]["model_calls"] == 2


def test_recovery_releases_only_precontact_holds_once(billing_flow):
    session = billing_flow.runtime.coordinator.begin_invocation(
        OpenApiBillingCommand(
            app_id="app",
            publication_id="publication",
            api_key_id="key",
            target_type="agent",
            target_id="agent",
            external_user_id="external",
            external_session_id="restart",
            payload={"message": "restart"},
            idempotency_key="restart-held",
            mode="enforced",
            budget_credits=100,
        ),
    )
    billing_flow.repository.grant(
        session.wallet_id,
        credits=20,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="fund-restart-held",
    )
    fence = billing_flow.open_repo.claim_invocation_execution(
        session.invocation_id,
        "restart-held-worker",
        lease_seconds=30,
    )
    assert fence is not None
    billing_flow.runtime.usage_service.reserve_model_call(
        ReserveModelCall(
            usage_order_id=session.usage_order_id,
            item_key="held-before-contact",
            provider_id="provider",
            model_key="model",
            capability="chat",
            parameters={"tier": "standard"},
            input_tokens=1,
            max_output_tokens=1,
            invocation_id=session.invocation_id,
            execution_fence=fence,
        ),
    )
    with billing_flow.engine.begin() as conn:
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == session.invocation_id)
            .values(
                execution_lease_expires_at=datetime.now(timezone.utc)
                - timedelta(seconds=1),
            ),
        )

    recover_open_api_billing(billing_flow.runtime)
    ledger_after_first = billing_flow.repository.list_ledger(
        session.wallet_id,
        100,
        None,
    )
    recover_open_api_billing(billing_flow.runtime)

    assert (
        billing_flow.runtime.usage_service.list_items(session.usage_order_id)[
            0
        ]["status"]
        == "released"
    )
    assert len(
        billing_flow.repository.list_ledger(session.wallet_id, 100, None),
    ) == len(ledger_after_first)
    invocation = billing_flow.open_repo.get_invocation(session.invocation_id)
    assert invocation is not None
    assert invocation["status"] == "failed"
    assert invocation["billing_status"] == "settled"


def test_recovery_ignores_historical_unbilled_and_is_ledger_idempotent(
    billing_flow,
):
    wallet = billing_flow.repository.ensure_wallet("user", "wallet-owner")
    billing_flow.repository.grant(
        str(wallet["id"]),
        credits=20,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="fund-recovery",
    )
    response = _post(billing_flow, key="recover")
    invocation_id = response.headers["X-DClaw-Invocation-Id"]
    with billing_flow.engine.begin() as conn:
        order_id = conn.scalar(
            select(open_api_invocations.c.billing_usage_order_id).where(
                open_api_invocations.c.id == invocation_id,
            ),
        )
        conn.execute(
            update(billing_usage_orders)
            .where(billing_usage_orders.c.id == order_id)
            .values(status="reconciling"),
        )
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == invocation_id)
            .values(billing_status="reconciling"),
        )
        conn.execute(
            insert(open_api_invocations).values(
                id="historical",
                app_id="app",
                publication_id="publication",
                api_key_id="key",
                target_type="agent",
                target_id="agent",
                status="succeeded",
                billing_status="unbilled",
                token_summary="{}",
            ),
        )
    before = billing_flow.repository.list_ledger(str(wallet["id"]), 100, None)

    recover_open_api_billing(billing_flow.runtime)
    recover_open_api_billing(billing_flow.runtime)

    after = billing_flow.repository.list_ledger(str(wallet["id"]), 100, None)
    assert len(after) == len(before)
    with billing_flow.engine.connect() as conn:
        historical = (
            conn.execute(
                select(open_api_invocations).where(
                    open_api_invocations.c.id == "historical",
                ),
            )
            .mappings()
            .one()
        )
        recovered = (
            conn.execute(
                select(open_api_invocations).where(
                    open_api_invocations.c.id == invocation_id,
                ),
            )
            .mappings()
            .one()
        )
    assert historical["billing_status"] == "unbilled"
    # The bridge row is repaired from its fully resolved durable item; only
    # the historical unbilled row remains outside startup recovery.
    assert recovered["billing_status"] == "settled"


def _fund(flow, grant_credits: int, key: str) -> str:
    wallet = flow.repository.ensure_wallet("user", "wallet-owner")
    flow.repository.grant(
        str(wallet["id"]),
        credits=grant_credits,
        credit_type="purchased",
        expires_at=None,
        idempotency_key=key,
    )
    return str(wallet["id"])


def test_sqlite_invocation_execution_lease_is_owner_cas(
    billing_flow,
    monkeypatch,
):
    session = billing_flow.runtime.coordinator.begin_invocation(
        OpenApiBillingCommand(
            app_id="app",
            publication_id="publication",
            api_key_id="key",
            target_type="agent",
            target_id="agent",
            external_user_id="external",
            external_session_id="claim",
            payload={"message": "claim"},
            idempotency_key="claim-once",
            mode="enforced",
            budget_credits=100,
        ),
    )

    def claim(token: str):
        repo = SqlAlchemyOpenApiRepository(billing_flow.engine)
        return repo.claim_invocation_execution(
            session.invocation_id,
            token,
            lease_seconds=30,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = list(pool.map(claim, ("owner-a", "owner-b")))

    fences = [fence for fence in winners if fence is not None]
    assert len(fences) == 1
    first_fence = fences[0]
    assert first_fence.generation == 1
    invocation = billing_flow.open_repo.get_invocation(session.invocation_id)
    assert invocation is not None
    assert invocation["status"] == "running"
    winner = str(invocation["execution_owner_token"])
    loser = "owner-b" if winner == "owner-a" else "owner-a"
    loser_fence = type(first_fence)(loser, first_fence.generation)
    assert not billing_flow.open_repo.renew_invocation_execution(
        session.invocation_id,
        loser_fence,
        lease_seconds=60,
    )
    assert billing_flow.open_repo.renew_invocation_execution(
        session.invocation_id,
        first_fence,
        lease_seconds=60,
    )
    import qwenpaw.app.storage.repos.open_api_repo as repo_module

    monkeypatch.setattr(
        repo_module,
        "_now",
        lambda: datetime.now(timezone.utc) + timedelta(days=365),
    )
    assert (
        billing_flow.open_repo.takeover_invocation_execution(
            session.invocation_id,
            "recovery-a",
            lease_seconds=90,
        )
        is None
    )
    with billing_flow.engine.begin() as conn:
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == session.invocation_id)
            .values(
                execution_lease_expires_at=datetime.now(timezone.utc)
                - timedelta(seconds=1),
            ),
        )
    assert not billing_flow.open_repo.renew_invocation_execution(
        session.invocation_id,
        first_fence,
        lease_seconds=120,
    )

    def takeover(token: str):
        repo = SqlAlchemyOpenApiRepository(billing_flow.engine)
        return repo.takeover_invocation_execution(
            session.invocation_id,
            token,
            lease_seconds=120,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        takeovers = list(pool.map(takeover, ("recovery-a", "recovery-b")))
    takeover_fences = [fence for fence in takeovers if fence is not None]
    assert len(takeover_fences) == 1
    takeover_fence = takeover_fences[0]
    assert takeover_fence.generation == 2
    assert (
        billing_flow.open_repo.finalize_invocation_execution(
            session.invocation_id,
            first_fence,
            status="failed",
            status_code=500,
            error_summary="stale owner",
            terminal_event={"type": "billing.completed", "winner": "stale"},
        )
        is None
    )
    sealed = billing_flow.open_repo.finalize_invocation_execution(
        session.invocation_id,
        takeover_fence,
        status="succeeded",
        status_code=200,
        error_summary="",
        terminal_event={"type": "billing.completed", "winner": "takeover"},
    )
    assert sealed is not None
    assert sealed["terminal_event_json"]["winner"] == "takeover"
    assert sealed["execution_owner_token"] is None
    assert sealed["execution_lease_expires_at"] is None


def test_sqlite_late_provider_response_is_fenced_from_capture_and_terminal(
    billing_flow,
):
    session = _begin_recovery_session(billing_flow, "late-provider-fence")
    billing_flow.repository.grant(
        session.wallet_id,
        credits=10,
        credit_type="purchased",
        expires_at=None,
        idempotency_key="late-provider-funds",
    )
    old_fence = billing_flow.open_repo.claim_invocation_execution(
        session.invocation_id,
        "old-worker",
        lease_seconds=30,
    )
    assert old_fence is not None
    command_fields = {
        "invocation_id": session.invocation_id,
        "execution_fence": old_fence,
    }
    billing_flow.runtime.usage_service.reserve_model_call(
        ReserveModelCall(
            usage_order_id=session.usage_order_id,
            item_key="late-call",
            provider_id="provider",
            model_key="model",
            capability="chat",
            parameters={"tier": "standard"},
            input_tokens=1,
            max_output_tokens=1,
            **command_fields,
        ),
    )
    billing_flow.runtime.usage_service.settle_model_call(
        SettleModelCall(
            usage_order_id=session.usage_order_id,
            item_key="late-call",
            supplier_reference="",
            billability="unknown",
            execution_outcome="pending",
            evidence={"response_class": "provider_call_started"},
            **command_fields,
        ),
    )
    with billing_flow.engine.begin() as conn:
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == session.invocation_id)
            .values(
                execution_lease_expires_at=datetime.now(timezone.utc)
                - timedelta(seconds=1),
            ),
        )
    winner = billing_flow.open_repo.takeover_invocation_execution(
        session.invocation_id,
        "winner",
        lease_seconds=30,
    )
    assert winner is not None and winner.generation == 2
    terminal = {"type": "billing.interrupted", "winner": "winner"}
    assert billing_flow.open_repo.finalize_invocation_execution(
        session.invocation_id,
        winner,
        status="failed",
        status_code=500,
        error_summary="recovered",
        terminal_event=terminal,
    )

    with pytest.raises(BillingExecutionFencedError):
        billing_flow.runtime.usage_service.settle_model_call(
            SettleModelCall(
                usage_order_id=session.usage_order_id,
                item_key="late-call",
                supplier_reference="supplier-late",
                billability="billable",
                evidence={"response_class": "success"},
                actual_input_tokens=1,
                actual_output_tokens=1,
                **command_fields,
            ),
        )

    item = billing_flow.runtime.usage_service.list_items(
        session.usage_order_id,
    )[0]
    assert item["status"] == "reconciling"
    assert item["captured_credits"] == 0
    invocation = billing_flow.open_repo.get_invocation(session.invocation_id)
    assert invocation["terminal_event_json"] == terminal


def test_sqlite_invocation_terminal_snapshot_is_sealed_once(billing_flow):
    session = billing_flow.runtime.coordinator.begin_invocation(
        OpenApiBillingCommand(
            app_id="app",
            publication_id="publication",
            api_key_id="key",
            target_type="agent",
            target_id="agent",
            external_user_id="external",
            external_session_id="seal",
            payload={"message": "seal"},
            idempotency_key="seal-once",
            mode="enforced",
            budget_credits=100,
        ),
    )
    billing_flow.open_repo.update_billing_invocation(
        session.invocation_id,
        status="succeeded",
        terminal_event={"type": "billing.completed", "credits_remaining": 1},
    )
    billing_flow.open_repo.update_billing_invocation(
        session.invocation_id,
        status="failed",
        terminal_event={"type": "billing.completed", "credits_remaining": 9},
    )

    invocation = billing_flow.open_repo.get_invocation(session.invocation_id)
    assert invocation is not None
    assert invocation["status"] == "succeeded"
    assert invocation["terminal_event_json"]["credits_remaining"] == 1


@pytest.mark.parametrize("funded", [True, False])
@pytest.mark.asyncio
async def test_same_key_race_before_tracker_never_restarts_supplier(
    billing_flow,
    monkeypatch,
    funded,
):
    if funded:
        _fund(billing_flow, 20, "race-before-tracker-funds")
    original_prepare = open_api.prepare_open_agent_chat
    both_prepared = asyncio.Event()
    prepared_count = 0

    async def delayed_prepare(*args, **kwargs):
        nonlocal prepared_count
        prepared = await original_prepare(*args, **kwargs)
        prepared_count += 1
        if prepared_count == 2:
            both_prepared.set()
        await asyncio.wait_for(both_prepared.wait(), timeout=2)
        return prepared

    monkeypatch.setattr(
        open_api,
        "prepare_open_agent_chat",
        delayed_prepare,
    )
    transport = ASGITransport(app=billing_flow.app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        responses = await asyncio.gather(
            *(
                client.post(
                    "/open/v1/targets/public-agent/messages",
                    headers={
                        "Idempotency-Key": f"before-tracker-{funded}",
                    },
                    json={
                        "external_user_id": "external",
                        "message": "hello",
                    },
                )
                for _index in range(2)
            ),
        )

    assert billing_flow.console.calls == (1 if funded else 0)
    if funded:
        assert all(response.status_code == 200 for response in responses)
        assert _events(responses[0])[-1] == _events(responses[1])[-1]
    else:
        assert all(response.status_code == 409 for response in responses)
        assert responses[0].json() == responses[1].json()


class _ProducerJustFinishedTracker(TaskTracker):
    async def get_status(self, _run_key: str) -> str:
        return "running"


def test_replay_when_producer_just_finished_never_restarts_supplier(
    billing_flow,
):
    _fund(billing_flow, 20, "race-funds")
    first = _post(billing_flow, key="producer-finished")
    first_terminal = _events(first)[-1]
    assert billing_flow.console.calls == 1
    billing_flow.workspace.task_tracker = _ProducerJustFinishedTracker()

    replay = _post(billing_flow, key="producer-finished")

    assert billing_flow.console.calls == 1
    assert _events(replay) == [first_terminal]


def test_initial_insufficient_replay_uses_sealed_required_credits(
    billing_flow,
):
    first = _post(billing_flow, key="sealed-insufficient")
    _fund(billing_flow, 100, "late-funds")

    replay = _post(billing_flow, key="sealed-insufficient")

    assert replay.status_code == 409
    assert replay.json() == first.json()
    assert "required_credits" in replay.json()


class _RejectLimiter:
    async def try_acquire(self, **_kwargs):
        return None


def test_claimed_limiter_failure_is_sealed_and_replayed_exactly(billing_flow):
    _fund(billing_flow, 20, "limiter-funds")
    billing_flow.app.state.task_limiter = _RejectLimiter()

    first = _post(billing_flow, key="limiter-replay")
    assert first.status_code == 429
    snapshot = first.json()
    assert snapshot["type"] == "billing.interrupted"
    assert snapshot["code"] == "task_limit_exceeded"
    assert snapshot["http_status"] == 429
    assert snapshot["required_credits"] is None
    assert snapshot["message"]
    assert snapshot["headers"]["X-DClaw-Invocation-Id"]
    invocation_id = snapshot["headers"]["X-DClaw-Invocation-Id"]
    invocation = billing_flow.open_repo.get_invocation(invocation_id)
    assert invocation["terminal_event_json"] == snapshot
    assert invocation["execution_owner_token"] is None
    assert invocation["execution_lease_expires_at"] is None

    replay = _post(billing_flow, key="limiter-replay")

    assert replay.status_code == first.status_code
    assert replay.json() == snapshot
    assert {
        key: replay.headers[key] for key in snapshot["headers"]
    } == snapshot["headers"]
    assert billing_flow.console.calls == 0


def test_claimed_prepare_http_failure_is_sealed_without_supplier(
    billing_flow,
    monkeypatch,
):
    _fund(billing_flow, 20, "prepare-funds")

    async def fail_prepare(*_args, **_kwargs):
        raise open_api.HTTPException(404, "Open target is unavailable")

    monkeypatch.setattr(open_api, "prepare_open_agent_chat", fail_prepare)
    first = _post(billing_flow, key="prepare-replay")
    replay = _post(billing_flow, key="prepare-replay")

    assert first.status_code == replay.status_code == 404
    assert replay.json() == first.json()
    assert first.json()["code"] == "open_target_unavailable"
    assert first.json()["message"] == "Open target is unavailable"
    assert billing_flow.console.calls == 0


class _FailingStartTracker(TaskTracker):
    async def attach_or_start(self, *_args, **_kwargs):
        raise RuntimeError("tracker failed before producer start")


def test_claimed_tracker_start_failure_is_sealed_and_replayed_exactly(
    billing_flow,
):
    _fund(billing_flow, 20, "tracker-start-funds")
    billing_flow.workspace.task_tracker = _FailingStartTracker()

    first = _post(billing_flow, key="tracker-start-replay")
    replay = _post(billing_flow, key="tracker-start-replay")

    assert first.status_code == replay.status_code == 500
    assert replay.json() == first.json()
    assert first.json()["code"] == "request_failed"
    assert first.json()["message"] == "Internal server error"
    assert billing_flow.console.calls == 0


def test_terminal_replay_is_immutable_after_wallet_balance_changes(
    billing_flow,
):
    _fund(billing_flow, 20, "snapshot-funds")
    first = _post(billing_flow, key="sealed-terminal")
    first_terminal = _events(first)[-1]
    _fund(billing_flow, 100, "later-wallet-change")

    replay = _post(billing_flow, key="sealed-terminal")

    assert _events(replay) == [first_terminal]


def test_success_without_reference_counts_as_completed_before_insufficient(
    billing_flow,
):
    _fund(billing_flow, 2, "unknown-partial-funds")
    billing_flow.console.calls_per_run = 2
    billing_flow.console.omit_reference = True

    response = _post(billing_flow, key="unknown-partial")

    terminal = _events(response)[-1]
    assert terminal["type"] == "billing.interrupted"
    assert terminal["completed_steps"] == 1
    assert terminal["status"] == "partially_completed"
    invocation = billing_flow.open_repo.get_invocation(
        response.headers["X-DClaw-Invocation-Id"],
    )
    with billing_flow.engine.connect() as conn:
        item = (
            conn.execute(
                select(billing_usage_items).where(
                    billing_usage_items.c.usage_order_id
                    == invocation["billing_usage_order_id"],
                ),
            )
            .mappings()
            .one()
        )
    assert item["status"] == "reconciling"
    assert item["execution_outcome"] == "succeeded"


class _TimeoutThenInsufficientConsole:
    def __init__(self):
        self.calls = 0

    async def stream_one(self, _payload):
        meter = get_current_billing_meter()
        assert meter is not None
        call = meter.before_call(
            provider_id="provider",
            model_key="model",
            messages=[{"role": "user", "content": "hello"}],
            max_output_tokens=1,
        )
        meter.mark_provider_call_started(call)
        self.calls += 1
        meter.record_exception(call, TimeoutError("timeout"))
        yield 'data: {"step": 1}\n\n'
        meter.before_call(
            provider_id="provider",
            model_key="model",
            messages=[{"role": "user", "content": "again"}],
            max_output_tokens=1,
        )


def test_timeout_unknown_does_not_count_as_completed_step(billing_flow):
    _fund(billing_flow, 2, "timeout-funds")
    console = _TimeoutThenInsufficientConsole()
    billing_flow.workspace.channel_manager = _Channels(console)

    response = _post(billing_flow, key="timeout-partial")

    terminal = _events(response)[-1]
    assert terminal["completed_steps"] == 0
    assert terminal["status"] == "failed"
    with billing_flow.engine.connect() as conn:
        item = conn.execute(select(billing_usage_items)).mappings().one()
    assert item["execution_outcome"] == "failed"


class _BlockingContactConsole:
    def __init__(self, *, before_contact: bool):
        self.before_contact = before_contact
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def stream_one(self, _payload):
        meter = get_current_billing_meter()
        assert meter is not None
        if self.before_contact:
            self.started.set()
            await self.release.wait()
        call = meter.before_call(
            provider_id="provider",
            model_key="model",
            messages=[{"role": "user", "content": "cancel"}],
            max_output_tokens=1,
        )
        meter.mark_provider_call_started(call)
        self.calls += 1
        self.started.set()
        await self.release.wait()
        meter.record_response(call, _Response("cancel-supplier"))
        yield 'data: {"step": 1}\n\n'


@pytest.mark.asyncio
async def test_same_key_across_worker_trackers_is_attach_only(
    billing_flow,
    monkeypatch,
):
    _fund(billing_flow, 20, "multi-worker-funds")
    console = _BlockingContactConsole(before_contact=False)
    billing_flow.workspace.channel_manager = _Channels(console)
    second_workspace = SimpleNamespace(
        channel_manager=_Channels(console),
        chat_manager=_Chats(),
        task_tracker=TaskTracker(),
    )
    second_app = FastAPI()

    @second_app.middleware("http")
    async def bind_authenticated_publication(request: Request, call_next):
        request.state.user_id = "wallet-owner"
        request.state.open_app_id = "app"
        request.state.open_publication_id = "publication"
        request.state.open_api_key_id = "key"
        return await call_next(request)

    second_app.state.multi_agent_manager = _Manager(second_workspace)
    second_app.state.task_limiter = TaskConcurrencyLimiter(
        max_global=10,
        max_per_agent=10,
        max_per_user=10,
    )
    second_app.include_router(open_api.router)
    original_prepare = open_api.prepare_open_agent_chat
    both_prepared = asyncio.Event()
    prepared_count = 0

    async def delayed_prepare(*args, **kwargs):
        nonlocal prepared_count
        prepared = await original_prepare(*args, **kwargs)
        prepared_count += 1
        if prepared_count == 2:
            both_prepared.set()
        await asyncio.wait_for(both_prepared.wait(), timeout=2)
        return prepared

    monkeypatch.setattr(open_api, "prepare_open_agent_chat", delayed_prepare)
    first_transport = ASGITransport(app=billing_flow.app)
    second_transport = ASGITransport(app=second_app)
    async with (
        AsyncClient(
            transport=first_transport,
            base_url="http://worker-a",
        ) as first_client,
        AsyncClient(
            transport=second_transport,
            base_url="http://worker-b",
        ) as second_client,
    ):
        requests = [
            asyncio.create_task(
                client.post(
                    "/open/v1/targets/public-agent/messages",
                    headers={"Idempotency-Key": "multi-worker"},
                    json={
                        "external_user_id": "external",
                        "message": "hello",
                    },
                ),
            )
            for client in (first_client, second_client)
        ]
        await asyncio.wait_for(console.started.wait(), timeout=2)
        assert console.calls == 1
        console.release.set()
        responses = await asyncio.wait_for(
            asyncio.gather(*requests),
            timeout=3,
        )

    assert all(response.status_code == 200 for response in responses)
    assert console.calls == 1
    assert _events(responses[0])[-1] == _events(responses[1])[-1]
    assert (
        responses[0].headers["X-DClaw-Invocation-Id"]
        == responses[1].headers["X-DClaw-Invocation-Id"]
    )


@pytest.mark.asyncio
async def test_provider_blocked_longer_than_lease_is_kept_active_by_heartbeat(
    billing_flow,
    monkeypatch,
):
    monkeypatch.setenv("DCLAW_OPEN_API_EXECUTION_LEASE_SECONDS", "1")
    monkeypatch.setenv("DCLAW_OPEN_API_EXECUTION_HEARTBEAT_SECONDS", "0.05")
    _fund(billing_flow, 20, "heartbeat-funds")
    console = _BlockingContactConsole(before_contact=False)
    billing_flow.workspace.channel_manager = _Channels(console)
    route_task = asyncio.create_task(
        open_api.post_open_message(
            "public-agent",
            open_api.OpenMessageRequest(
                external_user_id="external",
                message="heartbeat",
            ),
            _request(billing_flow),
        ),
    )
    await asyncio.wait_for(console.started.wait(), timeout=2)
    response = await asyncio.wait_for(route_task, timeout=2)
    invocation = billing_flow.open_repo.list_invocations(limit=1)[0]
    assert invocation["execution_lease_expires_at"] < (
        datetime.now(timezone.utc) + timedelta(seconds=2)
    )

    await asyncio.sleep(1.2)

    renewed = billing_flow.open_repo.get_invocation(str(invocation["id"]))
    assert renewed["execution_lease_expires_at"] > datetime.now(timezone.utc)
    assert recover_open_api_billing(billing_flow.runtime) == 0
    console.release.set()
    body = await asyncio.wait_for(
        _consume_streaming_response(response),
        timeout=2,
    )
    assert "billing.completed" in body
    assert console.calls == 1


@pytest.mark.asyncio
async def test_owner_loss_stops_next_supplier_and_cannot_replace_winner(
    billing_flow,
    monkeypatch,
):
    monkeypatch.setenv("DCLAW_OPEN_API_EXECUTION_LEASE_SECONDS", "1")
    monkeypatch.setenv("DCLAW_OPEN_API_EXECUTION_HEARTBEAT_SECONDS", "0.05")
    _fund(billing_flow, 20, "owner-loss-funds")
    release_second = asyncio.Event()
    console = _SupplierConsole(
        calls_per_run=2,
        block_after_first=release_second,
    )
    billing_flow.workspace.channel_manager = _Channels(console)
    route_task = asyncio.create_task(
        open_api.post_open_message(
            "public-agent",
            open_api.OpenMessageRequest(
                external_user_id="external",
                message="owner loss",
            ),
            _request(billing_flow),
        ),
    )
    response = await asyncio.wait_for(route_task, timeout=2)
    while console.calls < 1:
        await asyncio.sleep(0.01)
    invocation = billing_flow.open_repo.list_invocations(limit=1)[0]
    invocation_id = str(invocation["id"])
    with billing_flow.engine.begin() as conn:
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == invocation_id)
            .values(
                execution_lease_expires_at=datetime.now(timezone.utc)
                - timedelta(seconds=1),
            ),
        )
    replacement_fence = billing_flow.open_repo.takeover_invocation_execution(
        invocation_id,
        "replacement-worker",
        lease_seconds=30,
    )
    assert replacement_fence is not None
    winner_terminal = {
        "type": "billing.completed",
        "invocation_id": invocation_id,
        "winner": "replacement-worker",
    }
    assert billing_flow.open_repo.finalize_invocation_execution(
        invocation_id,
        replacement_fence,
        status="failed",
        status_code=500,
        error_summary="recovered by replacement worker",
        terminal_event=winner_terminal,
    )

    await asyncio.sleep(0.15)
    release_second.set()
    await asyncio.wait_for(_consume_streaming_response(response), timeout=2)

    assert console.calls == 1
    invocation = billing_flow.open_repo.get_invocation(invocation_id)
    assert invocation["terminal_event_json"] == winner_terminal


def _seal_reconciling_takeover_winner(billing_flow, invocation_id: str):
    invocation = billing_flow.open_repo.get_invocation(invocation_id)
    assert invocation is not None
    order_id = str(invocation["billing_usage_order_id"])
    with billing_flow.engine.begin() as conn:
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == invocation_id)
            .values(
                execution_lease_expires_at=datetime.now(timezone.utc)
                - timedelta(seconds=1),
            ),
        )
    winner = billing_flow.open_repo.takeover_invocation_execution(
        invocation_id,
        "no-item-winner",
        lease_seconds=30,
    )
    assert winner is not None
    with billing_flow.engine.begin() as conn:
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == invocation_id)
            .values(billing_status="reconciling"),
        )
    terminal = {
        "type": "billing.interrupted",
        "invocation_id": invocation_id,
        "billing_status": "reconciling",
        "status": "failed",
        "http_status": 500,
        "code": "request_interrupted",
        "message": "recovered by takeover winner",
        "required_credits": None,
        "headers": {
            "X-DClaw-Invocation-Id": invocation_id,
            "X-DClaw-Billing-Status": "reconciling",
        },
    }
    sealed = billing_flow.open_repo.finalize_invocation_execution(
        invocation_id,
        winner,
        status="failed",
        status_code=500,
        error_summary="recovered by takeover winner",
        billing_status="reconciling",
        terminal_event=terminal,
    )
    assert sealed is not None
    return order_id, terminal


@pytest.mark.asyncio
async def test_stale_preproducer_failure_cannot_settle_takeover_winner_state(
    billing_flow,
    monkeypatch,
):
    wallet_id = _fund(billing_flow, 20, "stale-preproducer-funds")
    ledger_count = len(
        billing_flow.repository.list_ledger(wallet_id, 100, None),
    )
    prepare_started = asyncio.Event()
    release_prepare = asyncio.Event()

    async def fail_after_takeover(*_args, **_kwargs):
        prepare_started.set()
        await release_prepare.wait()
        raise open_api.HTTPException(500, "late preproducer failure")

    monkeypatch.setattr(
        open_api,
        "prepare_open_agent_chat",
        fail_after_takeover,
    )
    transport = ASGITransport(app=billing_flow.app)
    async with AsyncClient(
        transport=transport,
        base_url="http://stale-preproducer",
    ) as client:
        request_task = asyncio.create_task(
            client.post(
                "/open/v1/targets/public-agent/messages",
                headers={"Idempotency-Key": "stale-preproducer"},
                json={
                    "external_user_id": "external",
                    "message": "late failure",
                },
            ),
        )
        await asyncio.wait_for(prepare_started.wait(), timeout=2)
        invocation = billing_flow.open_repo.list_invocations(limit=1)[0]
        invocation_id = str(invocation["id"])
        order_id, winner_terminal = _seal_reconciling_takeover_winner(
            billing_flow,
            invocation_id,
        )
        release_prepare.set()
        response = await asyncio.wait_for(request_task, timeout=2)

    assert response.status_code == 500
    assert response.json() == winner_terminal
    order = billing_flow.runtime.usage_service.get_order(order_id)
    assert order["status"] == "quoted"
    durable = billing_flow.open_repo.get_invocation(invocation_id)
    assert durable["billing_status"] == "reconciling"
    assert durable["terminal_event_json"] == winner_terminal
    assert billing_flow.runtime.usage_service.list_items(order_id) == []
    assert (
        len(billing_flow.repository.list_ledger(wallet_id, 100, None))
        == ledger_count
    )


@pytest.mark.asyncio
async def test_stale_no_item_stream_finalize_cannot_settle_winner_state(
    billing_flow,
    monkeypatch,
):
    wallet_id = _fund(billing_flow, 20, "stale-stream-finalize-funds")
    ledger_count = len(
        billing_flow.repository.list_ledger(wallet_id, 100, None),
    )
    session = _begin_recovery_session(billing_flow, "stale-stream-finalize")
    old_fence = billing_flow.open_repo.claim_invocation_execution(
        session.invocation_id,
        "stale-stream-owner",
        lease_seconds=30,
    )
    assert old_fence is not None
    execution = billing_flow.runtime.execution(
        session.invocation_id,
        old_fence,
        30,
    )
    winner_state: dict[str, object] = {}
    original_payload = open_api._terminal_billing_payload

    def takeover_before_stale_payload(*args, **kwargs):
        order_id, terminal = _seal_reconciling_takeover_winner(
            billing_flow,
            session.invocation_id,
        )
        winner_state.update(order_id=order_id, terminal=terminal)
        return original_payload(*args, **kwargs)

    monkeypatch.setattr(
        open_api,
        "_terminal_billing_payload",
        takeover_before_stale_payload,
    )

    sealed = await open_api._shielded_finalize(
        billing_flow.runtime,
        session,
        execution,
        stream_started_at=0.0,
        stream_failure=None,
        stream_exception=None,
        cancelled=False,
        expert_team_run_id="",
        execution_fence=old_fence,
    )

    order_id = str(winner_state["order_id"])
    winner_terminal = winner_state["terminal"]
    assert sealed == winner_terminal
    order = billing_flow.runtime.usage_service.get_order(order_id)
    assert order["status"] == "quoted"
    durable = billing_flow.open_repo.get_invocation(session.invocation_id)
    assert durable["billing_status"] == "reconciling"
    assert durable["terminal_event_json"] == winner_terminal
    assert billing_flow.runtime.usage_service.list_items(order_id) == []
    assert (
        len(billing_flow.repository.list_ledger(wallet_id, 100, None))
        == ledger_count
    )


@pytest.mark.asyncio
async def test_fastapi_cancel_resistant_late_response_is_financially_fenced(
    billing_flow,
    monkeypatch,
):
    monkeypatch.setenv("DCLAW_OPEN_API_EXECUTION_LEASE_SECONDS", "1")
    monkeypatch.setenv("DCLAW_OPEN_API_EXECUTION_HEARTBEAT_SECONDS", "0.05")
    _fund(billing_flow, 20, "late-fastapi-funds")
    console = _CancelResistantLateResponseConsole()
    billing_flow.workspace.channel_manager = _Channels(console)
    response = await open_api.post_open_message(
        "public-agent",
        open_api.OpenMessageRequest(
            external_user_id="external",
            message="late FastAPI response",
        ),
        _request(billing_flow),
    )
    await asyncio.wait_for(console.started.wait(), timeout=2)
    invocation = billing_flow.open_repo.list_invocations(limit=1)[0]
    invocation_id = str(invocation["id"])
    with billing_flow.engine.begin() as conn:
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == invocation_id)
            .values(
                execution_lease_expires_at=datetime.now(timezone.utc)
                - timedelta(seconds=1),
            ),
        )
    winner = billing_flow.open_repo.takeover_invocation_execution(
        invocation_id,
        "late-response-winner",
        lease_seconds=30,
    )
    assert winner is not None
    terminal = {
        "type": "billing.interrupted",
        "invocation_id": invocation_id,
        "winner": "late-response-winner",
    }
    assert billing_flow.open_repo.finalize_invocation_execution(
        invocation_id,
        winner,
        status="failed",
        status_code=500,
        error_summary="recovered",
        terminal_event=terminal,
    )

    await asyncio.wait_for(_consume_streaming_response(response), timeout=2)

    item = billing_flow.runtime.usage_service.list_items(
        str(invocation["billing_usage_order_id"]),
    )[0]
    assert console.calls == 1
    assert item["status"] == "reconciling"
    assert item["captured_credits"] == 0
    assert (
        billing_flow.open_repo.get_invocation(invocation_id)[
            "terminal_event_json"
        ]
        == terminal
    )


def _request(flow) -> Request:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/open/v1/targets/public-agent/messages",
            "raw_path": b"/open/v1/targets/public-agent/messages",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("127.0.0.1", 80),
            "client": ("127.0.0.1", 1234),
            "app": flow.app,
        },
    )
    request.state.user_id = "wallet-owner"
    request.state.open_app_id = "app"
    request.state.open_publication_id = "publication"
    request.state.open_api_key_id = "key"
    return request


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("before_contact", "want_billing"),
    [(True, "settled"), (False, "reconciling")],
)
async def test_cancelled_background_run_shields_durable_finalization(
    billing_flow,
    before_contact,
    want_billing,
):
    _fund(billing_flow, 20, f"cancel-funds-{before_contact}")
    console = _BlockingContactConsole(before_contact=before_contact)
    billing_flow.workspace.channel_manager = _Channels(console)
    route_task = asyncio.create_task(
        open_api.post_open_message(
            "public-agent",
            open_api.OpenMessageRequest(
                external_user_id="external",
                message="cancel",
            ),
            _request(billing_flow),
        ),
    )
    await asyncio.wait_for(console.started.wait(), timeout=2)
    with billing_flow.engine.connect() as conn:
        invocation_id = str(
            conn.scalar(select(open_api_invocations.c.id)),
        )
    if before_contact:
        await billing_flow.workspace.task_tracker.request_stop(
            f"open-api:{invocation_id}",
        )
        response = await asyncio.wait_for(route_task, timeout=2)
        body_task = asyncio.create_task(_consume_streaming_response(response))
    else:
        response = await asyncio.wait_for(route_task, timeout=2)
        body_task = asyncio.create_task(_consume_streaming_response(response))
        await billing_flow.workspace.task_tracker.request_stop(
            f"open-api:{invocation_id}",
        )
    assert await billing_flow.workspace.task_tracker.wait_all_done(timeout=2)
    body = await asyncio.wait_for(body_task, timeout=2)

    invocation = billing_flow.open_repo.get_invocation(invocation_id)
    assert invocation is not None
    assert invocation["status"] == "cancelled"
    assert invocation["status_code"] == 499
    assert invocation["billing_status"] == want_billing
    assert invocation["terminal_event_json"]
    terminal_events = [
        json.loads(line[6:])
        for line in body.splitlines()
        if line.startswith("data: ")
        and json.loads(line[6:]).get("type", "").startswith("billing.")
    ]
    assert terminal_events == [invocation["terminal_event_json"]]


def test_recovery_reprojects_settled_order_and_running_request(billing_flow):
    wallet_id = _fund(billing_flow, 20, "reproject-funds")
    response = _post(billing_flow, key="reproject")
    invocation_id = response.headers["X-DClaw-Invocation-Id"]
    invocation = billing_flow.open_repo.get_invocation(invocation_id)
    order_id = invocation["billing_usage_order_id"]
    ledger_count = len(
        billing_flow.repository.list_ledger(wallet_id, 100, None),
    )
    with billing_flow.engine.begin() as conn:
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == invocation_id)
            .values(
                status="running",
                billing_status="held",
                captured_credits=0,
                token_summary="{}",
                terminal_event_json=None,
            ),
        )
        conn.execute(
            update(billing_usage_orders)
            .where(billing_usage_orders.c.id == order_id)
            .values(captured_credits=0),
        )

    recover_open_api_billing(billing_flow.runtime)
    recover_open_api_billing(billing_flow.runtime)

    recovered = billing_flow.open_repo.get_invocation(invocation_id)
    assert recovered["status"] == "succeeded"
    assert recovered["billing_status"] == "settled"
    assert recovered["captured_credits"] > 0
    assert recovered["token_summary"]["model_calls"] == 1
    assert recovered["terminal_event_json"]
    assert (
        len(
            billing_flow.repository.list_ledger(wallet_id, 100, None),
        )
        == ledger_count
    )


def test_recovery_keeps_successful_unknown_as_completed_reconciling(
    billing_flow,
):
    _fund(billing_flow, 20, "recover-unknown-funds")
    billing_flow.console.omit_reference = True
    response = _post(billing_flow, key="recover-unknown")
    invocation_id = response.headers["X-DClaw-Invocation-Id"]
    with billing_flow.engine.begin() as conn:
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == invocation_id)
            .values(status="running", terminal_event_json=None),
        )

    recover_open_api_billing(billing_flow.runtime)

    invocation = billing_flow.open_repo.get_invocation(invocation_id)
    assert invocation["status"] == "succeeded"
    assert invocation["billing_status"] == "reconciling"
    assert invocation["terminal_event_json"]


def _begin_recovery_session(flow, key: str):
    return flow.runtime.coordinator.begin_invocation(
        OpenApiBillingCommand(
            app_id="app",
            publication_id="publication",
            api_key_id="key",
            target_type="agent",
            target_id="agent",
            external_user_id="external",
            external_session_id=key,
            payload={"message": key},
            idempotency_key=key,
            mode="enforced",
            budget_credits=100,
        ),
    )


def test_recovery_does_not_touch_unexpired_active_owner(billing_flow):
    session = _begin_recovery_session(billing_flow, "active-owner")
    assert billing_flow.open_repo.claim_invocation_execution(
        session.invocation_id,
        "live-worker",
        lease_seconds=30,
    )

    assert recover_open_api_billing(billing_flow.runtime) == 0

    invocation = billing_flow.open_repo.get_invocation(session.invocation_id)
    assert invocation["status"] == "running"
    assert invocation["execution_owner_token"] == "live-worker"
    assert invocation["execution_lease_expires_at"] > datetime.now(
        timezone.utc,
    )
    assert invocation["terminal_event_json"] is None


def test_recovery_expired_lease_has_one_takeover_winner(billing_flow):
    session = _begin_recovery_session(billing_flow, "expired-owner")
    assert billing_flow.open_repo.claim_invocation_execution(
        session.invocation_id,
        "dead-worker",
        lease_seconds=30,
    )
    with billing_flow.engine.begin() as conn:
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == session.invocation_id)
            .values(
                execution_lease_expires_at=datetime.now(timezone.utc)
                - timedelta(seconds=1),
            ),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        recovered = list(
            pool.map(
                lambda _index: recover_open_api_billing(billing_flow.runtime),
                range(2),
            ),
        )

    assert sorted(recovered) == [0, 1]
    invocation = billing_flow.open_repo.get_invocation(session.invocation_id)
    assert invocation["status"] == "failed"
    assert invocation["execution_owner_token"] is None
    assert invocation["terminal_event_json"]["type"] == "billing.completed"
    assert invocation["terminal_event_json"]["headers"] == {
        "X-DClaw-Invocation-Id": session.invocation_id,
        "X-DClaw-Billing-Status": "settled",
    }
    assert recover_open_api_billing(billing_flow.runtime) == 0


def test_recovery_repairs_state_from_existing_terminal_once(billing_flow):
    _fund(billing_flow, 20, "stale-terminal-funds")
    response = _post(billing_flow, key="stale-terminal")
    invocation_id = response.headers["X-DClaw-Invocation-Id"]
    original = billing_flow.open_repo.get_invocation(invocation_id)
    terminal = dict(original["terminal_event_json"])
    with billing_flow.engine.begin() as conn:
        conn.execute(
            update(open_api_invocations)
            .where(open_api_invocations.c.id == invocation_id)
            .values(
                status="running",
                status_code=202,
                execution_owner_token="stale-worker",
                execution_lease_expires_at=datetime.now(timezone.utc)
                + timedelta(seconds=30),
            ),
        )

    assert recover_open_api_billing(billing_flow.runtime) == 1
    assert recover_open_api_billing(billing_flow.runtime) == 0

    repaired = billing_flow.open_repo.get_invocation(invocation_id)
    assert repaired["status"] == "succeeded"
    assert repaired["status_code"] == 200
    assert repaired["execution_owner_token"] is None
    assert repaired["terminal_event_json"] == terminal
