# -*- coding: utf-8 -*-
"""Router-level OpenAPI billing flow integration coverage."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from agentscope.model._model_usage import ChatUsage
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
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
from qwenpaw.app.billing.usage import ReserveModelCall, UsageService
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
    billing_usage_items,
    billing_usage_orders,
    billing_price_catalogs,
    billing_price_rules,
    create_all,
    open_api_invocations,
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
                    capability="text",
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
    assert replay.headers["X-DClaw-Billing-Status"] == "settled"
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
    billing_flow.runtime.usage_service.reserve_model_call(
        ReserveModelCall(
            usage_order_id=session.usage_order_id,
            item_key="held-before-contact",
            provider_id="provider",
            model_key="model",
            capability="text",
            parameters={"tier": "standard"},
            input_tokens=1,
            max_output_tokens=1,
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
    assert recovered["billing_status"] == "reconciling"
