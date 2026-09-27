# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from agentscope_runtime.engine.schemas.agent_schemas import ContentType
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from qwenpaw.app.billing.execution import OpenApiExecutionFence
from qwenpaw.agents.react_agent import resolve_agent_runtime_boundary
from qwenpaw.app.sealed_agents.models import (
    SealedAgentRecord,
    SealedReleaseRecord,
)
from qwenpaw.app.open_api.runtime import (
    OpenMessageRequest,
    build_open_session_id,
    prepare_open_agent_chat,
    prepare_open_expert_team_chat,
)
from qwenpaw.app.routers import open_api
from qwenpaw.app.task_limits import TaskConcurrencyLimiter


def test_output_profile_is_larger_only_for_super_expert_release():
    base = {
        "release_id": "release-1",
        "version": "1.0.0",
        "content_digest": "a" * 64,
        "signer_id": "signer-1",
    }

    assert open_api._output_profile_for_release(None) == "default"
    assert (
        open_api._output_profile_for_release(SealedReleaseRecord(**base))
        == "default"
    )
    assert (
        open_api._output_profile_for_release(
            SealedReleaseRecord(**base, package_type="super_expert"),
        )
        == "super_expert"
    )


class FakeOpenApiRepository:
    def __init__(self, publication: dict[str, Any] | None = None) -> None:
        self.publication = publication
        self.invocations: list[dict[str, Any]] = []

    def get_enabled_publication_by_public_id(
        self,
        public_id: str,
    ) -> dict[str, Any] | None:
        if self.publication and self.publication["public_id"] == public_id:
            return self.publication
        return None

    def create_invocation(self, row: dict[str, Any]) -> dict[str, Any]:
        self.invocations.append(row)
        return row

    def get_invocation(self, invocation_id: str) -> dict[str, Any] | None:
        return next(
            (row for row in self.invocations if row["id"] == invocation_id),
            None,
        )

    def update_billing_invocation(self, invocation_id: str, **values):
        row = self.get_invocation(invocation_id)
        if row is not None:
            if "terminal_event" in values:
                if row.get("terminal_event_json") is not None:
                    return row
                values["terminal_event_json"] = values.pop("terminal_event")
            row.update(
                {
                    key: value
                    for key, value in values.items()
                    if value is not None
                },
            )
        return row

    def claim_invocation_execution(
        self,
        invocation_id: str,
        owner_token: str,
        *,
        lease_seconds,
    ):
        row = self.get_invocation(invocation_id)
        if (
            row is None
            or row.get("status") != "accepted"
            or row.get("execution_owner_token")
        ):
            return None
        generation = int(row.get("execution_fence_generation") or 0) + 1
        row.update(
            status="running",
            status_code=202,
            execution_owner_token=owner_token,
            execution_fence_generation=generation,
            execution_lease_expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=lease_seconds),
        )
        return OpenApiExecutionFence(owner_token, generation)

    def renew_invocation_execution(
        self,
        invocation_id: str,
        fence: OpenApiExecutionFence,
        *,
        lease_seconds,
    ) -> bool:
        row = self.get_invocation(invocation_id)
        current = datetime.now(timezone.utc)
        current_expiry = (row or {}).get("execution_lease_expires_at")
        owner_matches = bool(
            row
            and row.get("status") == "running"
            and row.get("execution_owner_token") == fence.owner_token
            and row.get("execution_fence_generation") == fence.generation,
        )
        expiry_valid = bool(
            isinstance(current_expiry, datetime) and current_expiry > current,
        )
        if (
            not owner_matches
            or not expiry_valid
            or (row or {}).get("terminal_event_json") is not None
        ):
            return False
        assert row is not None
        row["execution_lease_expires_at"] = current + timedelta(
            seconds=lease_seconds,
        )
        return True

    def finalize_invocation_execution(
        self,
        invocation_id: str,
        fence: OpenApiExecutionFence,
        *,
        status: str,
        status_code: int,
        error_summary: str,
        terminal_event: dict[str, Any],
        **values,
    ) -> dict[str, Any] | None:
        row = self.get_invocation(invocation_id)
        if (
            row is None
            or row.get("execution_owner_token") != fence.owner_token
            or row.get("execution_fence_generation") != fence.generation
            or row.get("terminal_event_json") is not None
        ):
            return None
        row.update(
            status=status,
            status_code=status_code,
            error_summary=error_summary,
            terminal_event_json=dict(terminal_event),
            execution_owner_token=None,
            execution_lease_expires_at=None,
        )
        row.update(
            {key: value for key, value in values.items() if value is not None},
        )
        return row

    def update_claimed_invocation(self, invocation_id, fence, **values):
        row = self.get_invocation(invocation_id)
        if (
            row is None
            or row.get("execution_owner_token") != fence.owner_token
            or row.get("execution_fence_generation") != fence.generation
            or row.get("terminal_event_json") is not None
        ):
            return None
        row.update(values)
        return row

    def update_invocation_status(
        self,
        invocation_id: str,
        *,
        status: str,
        status_code: int,
        latency_ms: int,
        error_summary: str = "",
        token_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        _ = token_summary
        for row in self.invocations:
            if row["id"] == invocation_id:
                row.update(
                    {
                        "status": status,
                        "status_code": status_code,
                        "latency_ms": latency_ms,
                        "error_summary": error_summary,
                    },
                )
                return row
        return None


class FakeConsoleChannel:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.streamed_payloads: list[dict[str, Any]] = []

    async def stream_one(self, payload: dict[str, Any]):
        self.streamed_payloads.append(payload)
        if self.fail:
            raise RuntimeError("stream failed")
        yield "data: done\n\n"


class TypedFailureConsoleChannel:
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        self.calls = 0

    async def stream_one(self, payload: dict[str, Any]):
        _ = payload
        self.calls += 1
        yield (
            "data: "
            + open_api.json.dumps(
                {
                    "object": "response",
                    "status": "failed",
                    "error": {"code": self.code, "message": self.message},
                },
            )
            + "\n\n"
        )
        raise RuntimeError("wrapped console failure must not replace code")


class FakeChannelManager:
    def __init__(
        self, console_channel: FakeConsoleChannel | None = None
    ) -> None:
        self.console_channel = console_channel or FakeConsoleChannel()
        self.requested: list[str] = []

    async def get_channel(self, name: str):
        self.requested.append(name)
        if name == "console":
            return self.console_channel
        return None


class FakeChatManager:
    def __init__(self, chat_id: str = "chat-open-1") -> None:
        self.chat_id = chat_id
        self.calls: list[dict[str, Any]] = []

    async def get_or_create_chat(
        self,
        session_id: str,
        owner_user_id: str,
        channel: str,
        name: str,
    ):
        self.calls.append(
            {
                "session_id": session_id,
                "owner_user_id": owner_user_id,
                "channel": channel,
                "name": name,
            },
        )
        return SimpleNamespace(id=self.chat_id)


class FakeTaskTracker:
    def __init__(
        self,
        *,
        is_new_run: bool = True,
        existing_events: list[str] | None = None,
        active_payload: dict[str, Any] | None = None,
    ) -> None:
        self.is_new_run = is_new_run
        self.existing_events = (
            ["data: existing\n\n"]
            if existing_events is None
            else existing_events
        )
        self.active_payload = active_payload
        self.attach_calls: list[dict[str, Any]] = []
        self.stream_payload: dict[str, Any] | None = None
        self.stream_fn: Any = None

    async def attach_or_start(
        self,
        chat_id: str,
        stream_payload: dict[str, Any],
        stream_fn,
        **kwargs,
    ):
        self.attach_calls.append(
            {
                "chat_id": chat_id,
                "stream_payload": stream_payload,
                "stream_fn": stream_fn,
                "kwargs": kwargs,
            },
        )
        self.stream_payload = stream_payload
        self.stream_fn = stream_fn
        return object(), self.is_new_run

    async def stream_from_queue(self, queue, chat_id: str):
        _ = queue, chat_id
        assert self.stream_payload is not None
        assert self.stream_fn is not None
        if not self.is_new_run:
            for event in self.existing_events:
                yield event
            return
        try:
            async for item in self.stream_fn(self.stream_payload):
                yield item
        except Exception:
            yield 'data: {"error": "internal server error"}\n\n'

    async def get_payload(self, chat_id: str):
        _ = chat_id
        return self.active_payload


class FakeMultiAgentManager:
    def __init__(self, workspace: Any) -> None:
        self.workspace = workspace
        self.calls: list[tuple[str, str]] = []

    async def get_agent(self, agent_id: str, user_id: str):
        self.calls.append((agent_id, user_id))
        return self.workspace


def _workspace(agent_id: str = "agent-published") -> Any:
    return SimpleNamespace(
        agent_id=agent_id,
        channel_manager=FakeChannelManager(),
        chat_manager=FakeChatManager(),
        task_tracker=FakeTaskTracker(),
    )


async def _consume_streaming_response(response) -> str:
    chunks: list[str] = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunks.append(chunk.decode("utf-8"))
        else:
            chunks.append(str(chunk))
    return "".join(chunks)


def _request(
    *,
    user_id: str = "owner-1",
    app_id: str = "app-1",
    publication_id: str = "pub-db-1",
    api_key_id: str = "key-1",
    workspace: Any | None = None,
    limiter: TaskConcurrencyLimiter | None = None,
) -> Request:
    workspace = workspace or _workspace()
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/open/v1/targets/public-agent/messages",
            "raw_path": b"/api/open/v1/targets/public-agent/messages",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("127.0.0.1", 8088),
            "client": ("127.0.0.1", 12345),
            "app": SimpleNamespace(
                state=SimpleNamespace(
                    multi_agent_manager=FakeMultiAgentManager(workspace),
                    task_limiter=limiter
                    or TaskConcurrencyLimiter(
                        max_global=10,
                        max_per_agent=10,
                        max_per_user=10,
                    ),
                ),
            ),
        },
    )
    request.state.user_id = user_id
    request.state.open_app_id = app_id
    request.state.open_publication_id = publication_id
    request.state.open_api_key_id = api_key_id
    return request


def _publication(
    *,
    publication_id: str = "pub-db-1",
    public_id: str = "public-agent",
    target_type: str = "agent",
    target_id: str = "agent-published",
    response_policy: str = "standard",
) -> dict[str, Any]:
    return {
        "id": publication_id,
        "public_id": public_id,
        "target_type": target_type,
        "target_id": target_id,
        "response_policy": response_policy,
        "owner_user_id": "owner-1",
        "bound_user_id": "owner-1",
        "status": "enabled",
    }


class _FakeBillingCoordinator:
    def __init__(self, repo):
        self.repo = repo

    def begin_invocation(self, command):
        invocation_id = f"billing-invocation-{len(self.repo.invocations) + 1}"
        self.repo.create_invocation(
            {
                "id": invocation_id,
                "app_id": command.app_id,
                "publication_id": command.publication_id,
                "api_key_id": command.api_key_id,
                "target_type": command.target_type,
                "target_id": command.target_id,
                "external_session_id": command.external_session_id,
                "external_user_id": command.external_user_id,
                "token_summary": {},
                "latency_ms": 0,
                "error_summary": "",
                "status": "accepted",
                "status_code": 202,
                "billing_status": "quoted",
                "billing_error_code": None,
                "sealed_runtime": command.sealed_runtime,
                "request_payload": dict(command.payload),
            },
        )
        return SimpleNamespace(
            invocation_id=invocation_id,
            usage_order_id=f"order-{invocation_id}",
            wallet_id="wallet",
            bound_user_id=getattr(
                self.repo,
                "billing_bound_user_id",
                "owner-1",
            ),
            app_id=command.app_id,
            api_key_id=command.api_key_id,
            publication_id=command.publication_id,
            catalog_version="test",
            mode="shadow",
            replayed=False,
        )


class _FakeUsageService:
    def list_items(self, _order_id):
        return [
            {
                "status": "released",
                "execution_outcome": "succeeded",
                "captured_credits": 0,
                "released_credits": 0,
            },
        ]

    def get_order(self, _order_id):
        return {"status": "settled", "captured_credits": 0}


class _FakeBillingExecution:
    meter = None
    insufficient = None

    def __init__(self, repo, invocation_id, fence):
        self.repo = repo
        self.invocation_id = invocation_id
        self.fence = fence
        self.terminal_snapshot = None
        self.finalizing = False
        self.producer_task = None

    def renew_lease(self):
        if not self.repo.renew_invocation_execution(
            self.invocation_id,
            self.fence,
            lease_seconds=30,
        ):
            raise AssertionError("fake execution lease was lost")

    def note_stream_ready(self):
        return None

    def begin_finalizing(self):
        self.finalizing = True

    async def wait_for_preflight(self):
        return None

    def note_finalized(self, terminal):
        self.finalizing = True
        self.terminal_snapshot = dict(terminal)

    async def wait_for_finalization(self):
        assert self.terminal_snapshot is not None
        return dict(self.terminal_snapshot)


class _FakeBillingRuntime:
    mode = "shadow"
    budget_credits = 100

    def __init__(self, repo):
        self.coordinator = _FakeBillingCoordinator(repo)
        self.open_api_repository = repo
        self.usage_service = _FakeUsageService()
        self.repository = SimpleNamespace(
            balance=lambda _wallet_id: SimpleNamespace(available=0),
        )

    def execution(self, invocation_id, fence, _lease_seconds):
        return _FakeBillingExecution(
            self.open_api_repository,
            invocation_id,
            fence,
        )


@pytest.fixture(autouse=True)
def _stub_router_billing_runtime(monkeypatch):
    monkeypatch.setattr(
        open_api,
        "create_open_api_billing_runtime",
        lambda **_kwargs: _FakeBillingRuntime(open_api.get_open_api_repository()),
    )


def test_build_open_session_id_is_stable_and_namespaced():
    assert (
        build_open_session_id("app-1", "public-agent", "ext-user", "session-1")
        == "open:app-1:public-agent:ext-user:session-1"
    )


def test_open_message_request_defaults_to_persistent_execution():
    request = OpenMessageRequest(external_user_id="user", message="hello")

    assert request.execution_mode == "persistent"


def test_open_message_request_accepts_explicit_execution_modes():
    persistent = OpenMessageRequest(
        external_user_id="user",
        message="hello",
        execution_mode="persistent",
    )
    isolated = OpenMessageRequest(
        external_user_id="user",
        message="hello",
        execution_mode="isolated_attempt",
    )

    assert persistent.execution_mode == "persistent"
    assert isolated.execution_mode == "isolated_attempt"


def test_open_message_request_rejects_unknown_execution_mode():
    with pytest.raises(ValidationError):
        OpenMessageRequest(
            external_user_id="user",
            message="hello",
            execution_mode="isolated",
        )
    assert (
        build_open_session_id(
            "app-1", "public-agent", "ext user", "bad header\r\n"
        )
        == "open:app-1:public-agent:ext_user:bad_header"
    )
    assert (
        build_open_session_id("app-1", "public-agent", "ext-user", None)
        == "open:app-1:public-agent:ext-user:default"
    )


@pytest.mark.asyncio
async def test_prepare_open_agent_chat_ignores_metadata_agent_id_and_binds_open_context():
    workspace = _workspace(agent_id="agent-published")
    request = _request(workspace=workspace)
    payload = OpenMessageRequest(
        external_user_id="ext-user",
        external_session_id="ext-session",
        message="hello open runtime",
        metadata={"agent_id": "malicious-agent", "topic": "safe"},
    )

    prepared = await prepare_open_agent_chat(
        request,
        _publication(),
        payload,
    )

    assert prepared.agent_id == "agent-published"
    assert (
        prepared.session_id == "open:app-1:public-agent:ext-user:ext-session"
    )
    assert prepared.channel == "open:app-1"
    assert prepared.chat_id == "chat-open-1"
    assert workspace.chat_manager.calls == [
        {
            "session_id": "open:app-1:public-agent:ext-user:ext-session",
            "owner_user_id": "owner-1",
            "channel": "open:app-1",
            "name": "hello open",
        },
    ]
    assert prepared.payload["sender_id"] == "owner-1"
    assert prepared.payload["channel_id"] == "open:app-1"
    assert prepared.payload["content_parts"][0].type == ContentType.TEXT
    assert prepared.payload["content_parts"][0].text == "hello open runtime"
    assert prepared.payload["meta"]["target_id"] == "agent-published"
    assert prepared.payload["meta"]["metadata"] == {
        "agent_id": "malicious-agent",
        "topic": "safe",
    }


@pytest.mark.asyncio
async def test_prepare_open_agent_chat_keeps_diagnostics_as_user_metadata():
    workspace = _workspace(agent_id="agent-published")
    request = _request(workspace=workspace)
    payload = OpenMessageRequest(
        external_user_id="ext-user",
        message="hello sealed runtime",
        metadata={"diagnostics_requested": True},
    )

    prepared = await prepare_open_agent_chat(
        request,
        _publication(),
        payload,
    )

    assert prepared.payload["meta"]["metadata"] == {
        "diagnostics_requested": True,
    }
    assert "sealed_runtime" not in prepared.payload["meta"]
    assert "_server_debug_endpoint_authorized" not in prepared.payload["meta"]
    assert "open_invocation_id" not in prepared.payload["meta"]


@pytest.mark.asyncio
async def test_prepare_isolated_agent_attempts_are_unique_without_durable_chats():
    workspace = _workspace(agent_id="agent-published")
    request = _request(workspace=workspace)
    payload = OpenMessageRequest(
        external_user_id="ext-user",
        external_session_id="customer-request-1",
        message="frozen business input",
        execution_mode="isolated_attempt",
        metadata={
            "execution_mode": "persistent",
            "open_invocation_id": "caller-forged",
        },
    )

    prepared = [
        await prepare_open_agent_chat(
            request,
            _publication(),
            payload,
            invocation_id=f"invocation-{index}",
        )
        for index in range(1, 4)
    ]

    assert len({item.session_id for item in prepared}) == 3
    assert workspace.chat_manager.calls == []
    for index, item in enumerate(prepared, start=1):
        assert item.chat_id == f"open-api:invocation-{index}"
        assert item.session_id.startswith(
            "open:attempt:e5f47b6539291f6539e20dfe:"
        )
        assert len(item.session_id) == 62
        assert item.payload["content_parts"][0].text == "frozen business input"
        assert item.payload["meta"]["external_session_id"] == "customer-request-1"
        assert item.payload["meta"]["execution_mode"] == "isolated_attempt"
        assert item.payload["meta"]["open_invocation_id"] == f"invocation-{index}"
        assert item.payload["meta"]["metadata"] == {
            "execution_mode": "persistent",
            "open_invocation_id": "caller-forged",
        }


@pytest.mark.asyncio
async def test_prepare_isolated_agent_chat_is_valid_for_sealed_runtime(tmp_path):
    workspace = _workspace(agent_id="luyu_agent")
    request = _request(
        workspace=workspace,
        app_id="a3101a92-5421-4a94-b6a1-cdecb02bdf04",
    )
    publication = _publication()
    publication["target_id"] = "luyu_agent"
    payload = OpenMessageRequest(
        external_user_id="codex-local-isolation-user",
        external_session_id="codex-frozen-request-20260902-002",
        message="frozen business input",
        execution_mode="isolated_attempt",
    )

    prepared = await prepare_open_agent_chat(
        request,
        publication,
        payload,
        invocation_id="675ae687-eb2c-4e7a-adc7-dc6b14a81566",
    )
    boundary = resolve_agent_runtime_boundary(
        agent_id=prepared.agent_id,
        session_id=prepared.session_id,
        configured_workspace=tmp_path / "sealed-release" / "agent",
        sealed=True,
        working_dir=tmp_path,
    )

    assert len(prepared.session_id) <= 128
    assert ":attempt:" in prepared.session_id
    assert boundary.session_root == (
        tmp_path / "sealed_sessions" / "luyu_agent" / prepared.session_id
    ).resolve()
    assert workspace.chat_manager.calls == []


@pytest.mark.asyncio
async def test_explicit_persistent_agent_preparation_keeps_existing_shape():
    workspace = _workspace(agent_id="agent-published")
    payload = OpenMessageRequest(
        external_user_id="ext-user",
        external_session_id="ext-session",
        message="hello",
        execution_mode="persistent",
    )

    prepared = await prepare_open_agent_chat(
        _request(workspace=workspace),
        _publication(),
        payload,
        invocation_id="persistent-invocation-1",
    )

    assert prepared.session_id == "open:app-1:public-agent:ext-user:ext-session"
    assert prepared.chat_id == "chat-open-1"
    assert "execution_mode" not in prepared.payload["meta"]
    assert (
        prepared.payload["meta"]["open_invocation_id"]
        == "persistent-invocation-1"
    )
    assert len(workspace.chat_manager.calls) == 1


@pytest.mark.asyncio
async def test_standard_and_sealed_publications_prepare_same_native_shape():
    payload = OpenMessageRequest(
        external_user_id="ext-user",
        external_session_id="ext-session",
        message="hello",
        metadata={"topic": "same"},
    )
    standard = await prepare_open_agent_chat(
        _request(workspace=_workspace(agent_id="agent-published")),
        _publication(response_policy="standard"),
        payload,
    )
    sealed = await prepare_open_agent_chat(
        _request(workspace=_workspace(agent_id="agent-published")),
        _publication(response_policy="sealed"),
        payload,
    )
    assert sealed.agent_id == standard.agent_id
    assert sealed.session_id == standard.session_id
    assert sealed.payload == standard.payload


@pytest.mark.asyncio
async def test_prepare_open_expert_team_chat_uses_leader_workspace_and_sets_team_meta():
    workspace = _workspace(agent_id="leader-agent")
    request = _request(workspace=workspace)
    payload = OpenMessageRequest(
        external_user_id="ext-user",
        external_session_id="team-session",
        message="build this",
        metadata={},
    )

    prepared = await prepare_open_expert_team_chat(
        request,
        _publication(target_type="expert_team", target_id="team-1"),
        payload,
        leader_agent_id="leader-agent",
    )

    manager = request.app.state.multi_agent_manager
    assert manager.calls == [("leader-agent", "owner-1")]
    assert prepared.agent_id == "leader-agent"
    assert prepared.payload["meta"]["expert_team_id"] == "team-1"
    assert prepared.payload["meta"]["target_type"] == "expert_team"


@pytest.mark.asyncio
async def test_post_open_message_returns_404_when_publication_is_missing(
    monkeypatch,
):
    repo = FakeOpenApiRepository(publication=None)
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)

    with pytest.raises(HTTPException) as exc_info:
        await open_api.post_open_message(
            "missing-public",
            OpenMessageRequest(
                external_user_id="u", external_session_id="s", message="hi"
            ),
            _request(),
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_post_open_message_rejects_api_key_publication_mismatch(
    monkeypatch,
):
    repo = FakeOpenApiRepository(
        publication=_publication(publication_id="pub-other")
    )
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)

    with pytest.raises(HTTPException) as exc_info:
        await open_api.post_open_message(
            "public-agent",
            OpenMessageRequest(
                external_user_id="u", external_session_id="s", message="hi"
            ),
            _request(publication_id="pub-db-1"),
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_post_open_message_rejects_isolated_expert_team_before_invocation(
    monkeypatch,
):
    repo = FakeOpenApiRepository(
        publication=_publication(target_type="expert_team", target_id="team-1")
    )
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)

    with pytest.raises(HTTPException) as exc_info:
        await open_api.post_open_message(
            "public-agent",
            OpenMessageRequest(
                external_user_id="u",
                external_session_id="s",
                message="hi",
                execution_mode="isolated_attempt",
            ),
            _request(),
        )

    assert exc_info.value.status_code == 400
    assert repo.invocations == []


@pytest.mark.asyncio
async def test_post_open_message_agent_publication_creates_invocation_from_request_state(
    monkeypatch,
):
    workspace = _workspace(agent_id="agent-published")
    repo = FakeOpenApiRepository(publication=_publication())
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)

    response = await open_api.post_open_message(
        "public-agent",
        OpenMessageRequest(
            external_user_id="ext-user",
            external_session_id="ext-session",
            message="hello",
        ),
        _request(workspace=workspace, api_key_id="key-from-state"),
    )

    assert response.headers["x-qwenpaw-chat-id"] == "chat-open-1"
    assert (
        response.headers["x-qwenpaw-session-id"]
        == "open:app-1:public-agent:ext-user:ext-session"
    )
    assert response.headers["x-qwenpaw-open-invocation-id"]
    assert repo.invocations[0]["api_key_id"] == "key-from-state"
    assert repo.invocations[0]["app_id"] == "app-1"
    assert repo.invocations[0]["publication_id"] == "pub-db-1"
    assert repo.invocations[0]["target_type"] == "agent"
    assert repo.invocations[0]["target_id"] == "agent-published"
    assert repo.invocations[0]["chat_id"] == "chat-open-1"
    assert repo.invocations[0]["external_session_id"] == "ext-session"
    assert repo.invocations[0]["external_user_id"] == "ext-user"
    assert repo.invocations[0]["status"] == "running"
    assert repo.invocations[0]["status_code"] == 202
    assert (
        workspace.task_tracker.attach_calls[0]["stream_payload"]["meta"][
            "publication_id"
        ]
        == "pub-db-1"
    )

    body = await _consume_streaming_response(response)

    assert body.startswith("data: done\n\n")
    assert '"type":"billing.completed"' in body
    assert repo.invocations[0]["status"] == "succeeded"
    assert repo.invocations[0]["status_code"] == 200


@pytest.mark.asyncio
async def test_open_api_concurrency_is_independent_from_bound_wallet(monkeypatch):
    workspace = _workspace(agent_id="agent-published")
    repo = FakeOpenApiRepository(publication=_publication())
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    limiter = TaskConcurrencyLimiter(
        max_global=20,
        max_per_agent=12,
        max_per_user=5,
    )
    held = []
    for index in range(5):
        permit = await limiter.try_acquire(
            agent_id=f"other-agent-{index}",
            user_id="owner-1",
        )
        assert permit is not None
        held.append(permit)

    try:
        response = await open_api.post_open_message(
            "public-agent",
            OpenMessageRequest(
                external_user_id="ext-user",
                external_session_id="ext-session",
                message="hello",
            ),
            _request(workspace=workspace, limiter=limiter),
        )
        assert response.status_code == 200
        await _consume_streaming_response(response)
    finally:
        for permit in held:
            await permit.release()


@pytest.mark.asyncio
async def test_open_api_concurrency_respects_configured_api_key_limit(monkeypatch):
    workspace = _workspace(agent_id="agent-published")
    repo = FakeOpenApiRepository(publication=_publication())
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    monkeypatch.setenv("DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_API_KEY", "5")
    monkeypatch.setenv("DCLAW_OPEN_API_WAIT_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setenv("DCLAW_OPEN_API_WAIT_POLL_SECONDS", "0.002")
    limiter = TaskConcurrencyLimiter(
        max_global=20,
        max_per_agent=12,
        max_per_user=20,
    )
    held = []
    for _ in range(5):
        permit = await limiter.try_acquire(
            agent_id="openapi-publication:pub-db-1",
            user_id="openapi-api-key:key-1",
        )
        assert permit is not None
        held.append(permit)

    try:
        response = await open_api.post_open_message(
            "public-agent",
            OpenMessageRequest(
                external_user_id="ext-user",
                external_session_id="ext-session",
                message="hello",
            ),
            _request(workspace=workspace, limiter=limiter),
        )
        assert response.status_code == 429
    finally:
        for permit in held:
            await permit.release()


@pytest.mark.asyncio
async def test_open_api_concurrency_respects_configured_publication_limit(
    monkeypatch,
):
    workspace = _workspace(agent_id="agent-published")
    repo = FakeOpenApiRepository(publication=_publication())
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    monkeypatch.setenv(
        "DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_PUBLICATION",
        "12",
    )
    monkeypatch.setenv("DCLAW_OPEN_API_WAIT_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setenv("DCLAW_OPEN_API_WAIT_POLL_SECONDS", "0.002")
    limiter = TaskConcurrencyLimiter(
        max_global=20,
        max_per_agent=20,
        max_per_user=20,
    )
    held = []
    for index in range(12):
        permit = await limiter.try_acquire(
            agent_id="openapi-publication:pub-db-1",
            user_id=f"openapi-api-key:other-key-{index}",
        )
        assert permit is not None
        held.append(permit)

    try:
        response = await open_api.post_open_message(
            "public-agent",
            OpenMessageRequest(
                external_user_id="ext-user",
                external_session_id="ext-session",
                message="hello",
            ),
            _request(workspace=workspace, limiter=limiter),
        )
        assert response.status_code == 429
    finally:
        for permit in held:
            await permit.release()


@pytest.mark.asyncio
async def test_open_api_wait_queue_drains_one_hundred_request_burst(monkeypatch):
    monkeypatch.setenv("DCLAW_OPEN_API_MAX_RUNNING_TASKS_GLOBAL", "20")
    monkeypatch.setenv(
        "DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_PUBLICATION",
        "30",
    )
    monkeypatch.setenv("DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_API_KEY", "20")
    monkeypatch.setenv("DCLAW_OPEN_API_WAIT_TIMEOUT_SECONDS", "2")
    monkeypatch.setenv("DCLAW_OPEN_API_WAIT_POLL_SECONDS", "0.005")
    monkeypatch.setenv("DCLAW_OPEN_API_MAX_WAITING_PER_PUBLICATION", "200")
    monkeypatch.setenv("DCLAW_OPEN_API_MAX_WAITING_PER_API_KEY", "100")
    app = SimpleNamespace(
        state=SimpleNamespace(
            task_limiter=TaskConcurrencyLimiter(
                max_global=32,
                max_per_agent=12,
                max_per_user=6,
            ),
        ),
    )
    active = 0
    peak = 0
    lock = asyncio.Lock()

    async def execute_one():
        nonlocal active, peak
        permit = await open_api._acquire_open_api_permit(
            app,
            publication_id="pub-db-1",
            api_key_id="key-1",
        )
        assert permit is not None
        async with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.005)
        async with lock:
            active -= 1
        await permit.release()

    await asyncio.gather(*(execute_one() for _ in range(100)))

    assert peak == 20
    assert active == 0
    snapshot = await app.state.task_limiter.snapshot()
    assert snapshot["rejected_acquire_count"] == 0


@pytest.mark.asyncio
async def test_open_api_concurrency_has_global_execution_limit(monkeypatch):
    monkeypatch.setenv("DCLAW_OPEN_API_MAX_RUNNING_TASKS_GLOBAL", "8")
    monkeypatch.setenv(
        "DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_PUBLICATION",
        "30",
    )
    monkeypatch.setenv("DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_API_KEY", "20")
    monkeypatch.setenv("DCLAW_OPEN_API_WAIT_TIMEOUT_SECONDS", "0.2")
    monkeypatch.setenv("DCLAW_OPEN_API_WAIT_POLL_SECONDS", "0.002")
    app = SimpleNamespace(
        state=SimpleNamespace(
            task_limiter=TaskConcurrencyLimiter(
                max_global=32,
                max_per_agent=12,
                max_per_user=6,
            ),
        ),
    )
    held = []
    for index in range(8):
        permit = await open_api._acquire_open_api_permit(
            app,
            publication_id=f"publication-{index}",
            api_key_id=f"api-key-{index}",
        )
        assert permit is not None
        held.append(permit)

    waiting = asyncio.create_task(
        open_api._acquire_open_api_permit(
            app,
            publication_id="publication-9",
            api_key_id="api-key-9",
        ),
    )
    await asyncio.sleep(0.02)

    try:
        assert not waiting.done()
        await held.pop().release()
        replacement = await asyncio.wait_for(waiting, timeout=0.1)
        assert replacement is not None
        held.append(replacement)
    finally:
        if not waiting.done():
            waiting.cancel()
        for permit in held:
            await permit.release()


@pytest.mark.asyncio
async def test_open_api_wait_queue_has_bounded_capacity():
    queue = open_api._OpenApiWaitQueue()
    first = await queue.try_join(
        "publication-1",
        "api-key-1",
        max_per_publication=1,
        max_per_api_key=1,
    )
    assert first is not None
    assert (
        await queue.try_join(
            "publication-1",
            "api-key-1",
            max_per_publication=1,
            max_per_api_key=1,
        )
        is None
    )
    await first.release()
    replacement = await queue.try_join(
        "publication-1",
        "api-key-1",
        max_per_publication=1,
        max_per_api_key=1,
    )
    assert replacement is not None
    await replacement.release()


@pytest.mark.asyncio
async def test_open_api_wait_queue_snapshot_reports_running_and_waiting():
    queue = open_api._OpenApiWaitQueue()
    assert await queue.try_acquire_execution_slot(3) is True
    ticket = await queue.try_join(
        "publication-1",
        "api-key-1",
        max_per_publication=2,
        max_per_api_key=2,
    )
    assert ticket is not None

    assert await queue.snapshot() == {
        "running_global": 1,
        "waiting_global": 1,
        "waiting_by_publication": {"publication-1": 1},
        "waiting_by_api_key": {"api-key-1": 1},
    }

    await ticket.release()
    await queue.release_execution_slot()


@pytest.mark.asyncio
async def test_open_api_queue_timeout_returns_retry_after(monkeypatch):
    workspace = _workspace(agent_id="agent-published")
    repo = FakeOpenApiRepository(publication=_publication())
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    monkeypatch.setenv(
        "DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_PUBLICATION",
        "30",
    )
    monkeypatch.setenv("DCLAW_OPEN_API_MAX_RUNNING_TASKS_PER_API_KEY", "20")
    monkeypatch.setenv("DCLAW_OPEN_API_WAIT_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setenv("DCLAW_OPEN_API_WAIT_POLL_SECONDS", "0.002")
    monkeypatch.setenv("DCLAW_OPEN_API_RETRY_AFTER_SECONDS", "5")
    limiter = TaskConcurrencyLimiter(
        max_global=32,
        max_per_agent=12,
        max_per_user=6,
    )
    held = []
    for _ in range(20):
        permit = await limiter.try_acquire(
            agent_id="openapi-publication:pub-db-1",
            user_id="openapi-api-key:key-1",
            max_per_agent=30,
            max_per_user=20,
        )
        assert permit is not None
        held.append(permit)

    try:
        response = await open_api.post_open_message(
            "public-agent",
            OpenMessageRequest(
                external_user_id="ext-user",
                external_session_id="ext-session",
                message="hello",
            ),
            _request(workspace=workspace, limiter=limiter),
        )
        assert response.status_code == 429
        assert response.headers["retry-after"] == "5"
        assert (await limiter.snapshot())["rejected_acquire_count"] == 1
    finally:
        for permit in held:
            await permit.release()


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [False, True])
async def test_persistent_mode_keeps_legacy_billing_payload_shape(
    monkeypatch,
    explicit,
):
    workspace = _workspace(agent_id="agent-published")
    repo = FakeOpenApiRepository(publication=_publication())
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    values = {
        "external_user_id": "ext-user",
        "external_session_id": "ext-session",
        "message": "hello",
    }
    if explicit:
        values["execution_mode"] = "persistent"

    response = await open_api.post_open_message(
        "public-agent",
        OpenMessageRequest(**values),
        _request(workspace=workspace),
    )
    await _consume_streaming_response(response)

    assert repo.invocations[0]["request_payload"] == {
        "external_user_id": "ext-user",
        "external_session_id": "ext-session",
        "message": "hello",
        "stream": True,
        "metadata": {},
    }


@pytest.mark.asyncio
async def test_isolated_agent_route_uses_ephemeral_chat_and_preserves_audit_ids(
    monkeypatch,
):
    workspace = _workspace(agent_id="agent-published")
    repo = FakeOpenApiRepository(publication=_publication())
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)

    response = await open_api.post_open_message(
        "public-agent",
        OpenMessageRequest(
            external_user_id="ext-user",
            external_session_id="customer-request-1",
            message="frozen input",
            execution_mode="isolated_attempt",
        ),
        _request(workspace=workspace),
    )

    assert workspace.chat_manager.calls == []
    assert response.headers["x-qwenpaw-chat-id"].startswith("open-api:")
    assert ":attempt:" in response.headers["x-qwenpaw-session-id"]
    assert repo.invocations[0]["external_session_id"] == "customer-request-1"
    assert repo.invocations[0]["request_payload"]["execution_mode"] == (
        "isolated_attempt"
    )
    stream_meta = workspace.task_tracker.attach_calls[0]["stream_payload"]["meta"]
    assert stream_meta["execution_mode"] == "isolated_attempt"
    assert stream_meta["external_session_id"] == "customer-request-1"

    assert "data: done" in await _consume_streaming_response(response)


@pytest.mark.asyncio
async def test_concurrent_isolated_and_persistent_routes_keep_separate_state(
    monkeypatch,
):
    isolated_workspace = _workspace(agent_id="agent-published")
    persistent_workspace = _workspace(agent_id="agent-published")
    repo = FakeOpenApiRepository(publication=_publication())
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)

    isolated_response, persistent_response = await asyncio.gather(
        open_api.post_open_message(
            "public-agent",
            OpenMessageRequest(
                external_user_id="ext-user",
                external_session_id="same-correlation",
                message="same frozen input",
                execution_mode="isolated_attempt",
            ),
            _request(workspace=isolated_workspace),
        ),
        open_api.post_open_message(
            "public-agent",
            OpenMessageRequest(
                external_user_id="ext-user",
                external_session_id="persistent-session",
                message="ordinary input",
            ),
            _request(workspace=persistent_workspace),
        ),
    )

    assert isolated_workspace.chat_manager.calls == []
    assert len(persistent_workspace.chat_manager.calls) == 1
    assert ":attempt:" in isolated_response.headers["x-qwenpaw-session-id"]
    assert persistent_response.headers["x-qwenpaw-session-id"] == (
        "open:app-1:public-agent:ext-user:persistent-session"
    )
    assert "execution_mode" not in (
        persistent_workspace.task_tracker.attach_calls[0]["stream_payload"][
            "meta"
        ]
    )

    await asyncio.gather(
        _consume_streaming_response(isolated_response),
        _consume_streaming_response(persistent_response),
    )


@pytest.mark.asyncio
async def test_standard_post_open_message_does_not_read_sealed_registry(
    monkeypatch,
):
    workspace = _workspace(agent_id="agent-published")
    repo = FakeOpenApiRepository(publication=_publication())
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    monkeypatch.setattr(
        open_api,
        "get_sealed_agent_registry",
        lambda: pytest.fail("standard OpenAPI read sealed Registry"),
    )

    response = await open_api.post_open_message(
        "public-agent",
        OpenMessageRequest(
            external_user_id="ext-user",
            external_session_id="ext-session",
            message="hello",
        ),
        _request(workspace=workspace),
    )

    body = await _consume_streaming_response(response)
    assert "data: done" in body


@pytest.mark.asyncio
async def test_sealed_post_open_message_preserves_native_stream_events(
    monkeypatch,
):
    events = [
        'data: {"type":"tool.call","name":"read_file"}\n\n',
        'data: {"type":"response.failed","error":"native_error"}\n\n',
        'data: {"type":"response.completed"}\n\n',
    ]
    workspace = _workspace(agent_id="agent-published")
    workspace.task_tracker = FakeTaskTracker(
        is_new_run=False,
        existing_events=events,
    )
    publication = _publication(response_policy="sealed")
    repo = FakeOpenApiRepository(publication=publication)
    release = SealedReleaseRecord(
        release_id="release-1",
        version="2.1.0",
        content_digest="sha256:" + "a" * 64,
        signer_id="publisher",
        state="active",
    )
    record = SealedAgentRecord(
        agent_id="agent-published",
        name="陆羽",
        active_release_id=release.release_id,
        releases=[release],
    )
    registry = SimpleNamespace(
        is_sealed=lambda _agent_id: True,
        get_agent=lambda _agent_id: record,
    )
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    monkeypatch.setattr(
        open_api,
        "get_sealed_agent_registry",
        lambda: registry,
    )

    response = await open_api.post_open_message(
        "public-agent",
        OpenMessageRequest(
            external_user_id="ext-user",
            external_session_id="ext-session",
            message="hello",
        ),
        _request(workspace=workspace),
    )

    body = await _consume_streaming_response(response)
    assert body == "".join(events)
    assert repo.invocations[0]["sealed_runtime"] == {
        "release_id": "release-1",
        "version": "2.1.0",
        "content_digest": "sha256:" + "a" * 64,
    }


@pytest.mark.asyncio
async def test_post_open_message_uses_billing_locked_bound_user(monkeypatch):
    workspace = _workspace(agent_id="agent-published")
    repo = FakeOpenApiRepository(publication=_publication())
    repo.billing_bound_user_id = "owner-2"
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    request = _request(workspace=workspace, user_id="owner-1")

    response = await open_api.post_open_message(
        "public-agent",
        OpenMessageRequest(
            external_user_id="ext-user",
            external_session_id="ext-session",
            message="hello",
        ),
        request,
    )

    assert request.state.user_id == "owner-2"
    assert workspace.chat_manager.calls[0]["owner_user_id"] == "owner-2"
    assert request.app.state.multi_agent_manager.calls == [
        ("agent-published", "owner-2"),
    ]
    await _consume_streaming_response(response)


@pytest.mark.asyncio
async def test_post_open_message_updates_existing_run_invocation_on_stream_completion(
    monkeypatch,
):
    workspace = _workspace(agent_id="agent-published")
    workspace.task_tracker = FakeTaskTracker(
        is_new_run=False,
        existing_events=["data: existing\n\n"],
    )
    repo = FakeOpenApiRepository(publication=_publication())
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)

    response = await open_api.post_open_message(
        "public-agent",
        OpenMessageRequest(
            external_user_id="ext-user",
            external_session_id="ext-session",
            message="hello",
        ),
        _request(workspace=workspace),
    )

    assert repo.invocations[0]["status"] == "running"

    body = await _consume_streaming_response(response)

    assert body == "data: existing\n\n"
    assert repo.invocations[0]["status"] == "running"
    assert workspace.channel_manager.console_channel.streamed_payloads == []


@pytest.mark.asyncio
async def test_post_open_message_marks_existing_run_cancelled_when_request_disconnected(
    monkeypatch,
):
    workspace = _workspace(agent_id="agent-published")
    workspace.task_tracker = FakeTaskTracker(
        is_new_run=False, existing_events=[]
    )
    repo = FakeOpenApiRepository(publication=_publication())
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    request = _request(workspace=workspace)

    async def disconnected() -> bool:
        return True

    request.is_disconnected = disconnected  # type: ignore[method-assign]

    response = await open_api.post_open_message(
        "public-agent",
        OpenMessageRequest(
            external_user_id="ext-user",
            external_session_id="ext-session",
            message="hello",
        ),
        request,
    )

    body = await _consume_streaming_response(response)

    assert body == ""
    assert repo.invocations[0]["status"] == "running"


@pytest.mark.asyncio
async def test_post_open_message_marks_existing_run_invocation_failed_on_error_event(
    monkeypatch,
):
    workspace = _workspace(agent_id="agent-published")
    workspace.task_tracker = FakeTaskTracker(
        is_new_run=False,
        existing_events=['data: {"error": "internal server error"}\n\n'],
    )
    repo = FakeOpenApiRepository(publication=_publication())
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)

    response = await open_api.post_open_message(
        "public-agent",
        OpenMessageRequest(
            external_user_id="ext-user",
            external_session_id="ext-session",
            message="hello",
        ),
        _request(workspace=workspace),
    )

    body = await _consume_streaming_response(response)

    assert "internal server error" in body
    assert repo.invocations[0]["status"] == "running"


@pytest.mark.asyncio
async def test_post_open_message_marks_existing_run_failed_on_expert_team_status_event(
    monkeypatch,
):
    workspace = _workspace(agent_id="leader-agent")
    workspace.task_tracker = FakeTaskTracker(
        is_new_run=False,
        existing_events=[
            'data: {"type": "expert_team.status", "run": {"state": "failed", "error": "team failed"}}\n\n',
        ],
    )
    repo = FakeOpenApiRepository(
        publication=_publication(
            public_id="public-team",
            target_type="expert_team",
            target_id="team-1",
        ),
    )

    def fake_get_team(team_id: str):
        assert team_id == "team-1"
        return SimpleNamespace(
            id="team-1", enabled=True, leader_agent_id="leader-agent"
        )

    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    monkeypatch.setattr(open_api, "get_expert_team_template", fake_get_team)
    monkeypatch.setattr(
        open_api,
        "get_latest_expert_team_run_by_chat",
        lambda chat_id: SimpleNamespace(
            id="existing-run-1", root_chat_id=chat_id
        ),
    )

    response = await open_api.post_open_message(
        "public-team",
        OpenMessageRequest(
            external_user_id="ext-user",
            external_session_id="team-session",
            message="build it",
        ),
        _request(workspace=workspace),
    )

    body = await _consume_streaming_response(response)

    assert "team failed" in body
    assert repo.invocations[0]["status"] == "running"


@pytest.mark.asyncio
async def test_post_open_message_updates_invocation_failed_when_stream_fails(
    monkeypatch,
):
    workspace = _workspace(agent_id="agent-published")
    workspace.channel_manager = FakeChannelManager(
        FakeConsoleChannel(fail=True)
    )
    repo = FakeOpenApiRepository(publication=_publication())
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)

    response = await open_api.post_open_message(
        "public-agent",
        OpenMessageRequest(
            external_user_id="ext-user",
            external_session_id="ext-session",
            message="hello",
        ),
        _request(workspace=workspace),
    )

    body = await _consume_streaming_response(response)

    assert "error" in body
    assert repo.invocations[0]["status"] == "failed"
    assert repo.invocations[0]["status_code"] == 500
    assert "stream failed" in repo.invocations[0]["error_summary"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "message", "http_status"),
    [
        (
            "response_format_adapter_unavailable",
            "Configured response format is unavailable",
            500,
        ),
        ("model_execution_failed", "Model execution failed", 502),
        ("tool_execution_failed", "Tool execution failed", 502),
        (
            "empty_final_response",
            "Model returned an empty final response",
            502,
        ),
        (
            "invalid_final_response",
            "Model returned an invalid JSON response",
            502,
        ),
    ],
)
async def test_direct_agent_typed_failure_is_sealed_in_terminal_and_invocation(
    monkeypatch,
    code,
    message,
    http_status,
):
    channel = TypedFailureConsoleChannel(code, message)
    workspace = _workspace(agent_id="agent-published")
    workspace.channel_manager = FakeChannelManager(channel)
    repo = FakeOpenApiRepository(publication=_publication())
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)

    response = await open_api.post_open_message(
        "public-agent",
        OpenMessageRequest(
            external_user_id="ext-user",
            external_session_id="ext-session",
            message="hello",
        ),
        _request(workspace=workspace),
    )
    body = await _consume_streaming_response(response)

    invocation = repo.invocations[0]
    terminal = invocation["terminal_event_json"]
    assert channel.calls == 1
    assert invocation["status"] == "failed"
    assert invocation["status_code"] == http_status
    assert terminal["status"] == "failed"
    assert terminal["code"] == code
    assert terminal["message"] == message
    assert terminal["http_status"] == http_status
    assert open_api.json.dumps(terminal, separators=(",", ":")) in body
    assert "wrapped console failure" not in body


def test_extract_stream_failure_preserves_typed_error_fields():
    failure = open_api._extract_stream_failure(
        'data: {"object":"response","status":"failed",'
        '"error":{"code":"model_execution_failed",'
        '"message":"Model execution failed"}}\n\n',
    )

    assert failure is not None
    assert failure.status == "failed"
    assert failure.code == "model_execution_failed"
    assert failure.message == "Model execution failed"
    assert failure.http_status == 502


@pytest.mark.asyncio
async def test_post_open_message_rejects_non_streaming_requests(monkeypatch):
    repo = FakeOpenApiRepository(publication=_publication())
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)

    with pytest.raises(HTTPException) as exc_info:
        await open_api.post_open_message(
            "public-agent",
            OpenMessageRequest(
                external_user_id="ext-user",
                external_session_id="ext-session",
                message="hello",
                stream=False,
            ),
            _request(),
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_post_open_message_expert_team_creates_team_run_payload_and_headers(
    monkeypatch,
):
    workspace = _workspace(agent_id="leader-agent")
    repo = FakeOpenApiRepository(
        publication=_publication(
            public_id="public-team",
            target_type="expert_team",
            target_id="team-1",
        ),
    )
    captured: dict[str, Any] = {}

    def fake_get_team(team_id: str):
        assert team_id == "team-1"
        return SimpleNamespace(
            id="team-1", enabled=True, leader_agent_id="leader-agent"
        )

    def fake_create_run(**kwargs):
        captured["create_run"] = kwargs
        return SimpleNamespace(id=kwargs["run_id"])

    async def fake_attach_run_to_chat(*args):
        captured["attach_run_to_chat"] = args

    class FakeExpertTeamOrchestrator:
        def __init__(self, *, workspace, console_channel):
            captured["orchestrator"] = (workspace, console_channel)

        async def stream_one(self, payload):
            captured["orchestrator_payload"] = payload
            yield "data: team\n\n"

    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    monkeypatch.setattr(open_api, "get_expert_team_template", fake_get_team)
    monkeypatch.setattr(open_api, "create_expert_team_run", fake_create_run)
    monkeypatch.setattr(
        open_api, "attach_run_to_chat", fake_attach_run_to_chat
    )
    monkeypatch.setattr(
        open_api, "ExpertTeamOrchestrator", FakeExpertTeamOrchestrator
    )

    response = await open_api.post_open_message(
        "public-team",
        OpenMessageRequest(
            external_user_id="ext-user",
            external_session_id="team-session",
            message="build it",
            metadata={"priority": "high"},
        ),
        _request(workspace=workspace),
    )

    run_id = response.headers["x-qwenpaw-expert-team-run-id"]
    assert run_id
    stream_payload = workspace.task_tracker.attach_calls[0]["stream_payload"]
    assert stream_payload["run_id"] == run_id

    body = await _consume_streaming_response(response)

    assert body.startswith("data: team\n\n")
    assert '"type":"billing.completed"' in body
    assert captured["create_run"] == {
        "team_id": "team-1",
        "root_chat_id": "chat-open-1",
        "root_session_id": "open:app-1:public-team:ext-user:team-session",
        "user_id": "owner-1",
        "input_text": "build it",
        "run_id": run_id,
    }
    assert captured["attach_run_to_chat"][0] is workspace
    assert captured["attach_run_to_chat"][1] == "chat-open-1"
    assert captured["attach_run_to_chat"][2].id == run_id
    assert captured["orchestrator_payload"]["run_id"] == run_id
    assert stream_payload["team_id"] == "team-1"
    assert stream_payload["root_chat_id"] == "chat-open-1"
    assert (
        stream_payload["root_session_id"]
        == "open:app-1:public-team:ext-user:team-session"
    )
    assert (
        stream_payload["native_payload"]["meta"]["expert_team_id"] == "team-1"
    )


@pytest.mark.asyncio
async def test_post_open_message_expert_team_status_failed_marks_invocation_failed(
    monkeypatch,
):
    workspace = _workspace(agent_id="leader-agent")
    repo = FakeOpenApiRepository(
        publication=_publication(
            public_id="public-team",
            target_type="expert_team",
            target_id="team-1",
        ),
    )

    def fake_get_team(team_id: str):
        assert team_id == "team-1"
        return SimpleNamespace(
            id="team-1", enabled=True, leader_agent_id="leader-agent"
        )

    def fake_create_run(**kwargs):
        return SimpleNamespace(id=kwargs["run_id"])

    async def fake_attach_run_to_chat(*args):
        _ = args

    class FakeExpertTeamOrchestrator:
        def __init__(self, *, workspace, console_channel):
            _ = workspace, console_channel

        async def stream_one(self, payload):
            _ = payload
            yield (
                'data: {"type": "expert_team.status", '
                '"run": {"state": "failed", "error": "team failed"}}\n\n'
            )

    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    monkeypatch.setattr(open_api, "get_expert_team_template", fake_get_team)
    monkeypatch.setattr(open_api, "create_expert_team_run", fake_create_run)
    monkeypatch.setattr(
        open_api, "attach_run_to_chat", fake_attach_run_to_chat
    )
    monkeypatch.setattr(
        open_api, "ExpertTeamOrchestrator", FakeExpertTeamOrchestrator
    )

    response = await open_api.post_open_message(
        "public-team",
        OpenMessageRequest(
            external_user_id="ext-user",
            external_session_id="team-session",
            message="build it",
        ),
        _request(workspace=workspace),
    )

    body = await _consume_streaming_response(response)

    assert "team failed" in body
    assert repo.invocations[0]["status"] == "failed"
    assert repo.invocations[0]["status_code"] == 500
    assert repo.invocations[0]["error_summary"] == "team failed"


@pytest.mark.asyncio
async def test_post_open_message_expert_team_existing_run_does_not_create_new_team_run(
    monkeypatch,
):
    workspace = _workspace(agent_id="leader-agent")
    workspace.task_tracker = FakeTaskTracker(
        is_new_run=False,
        existing_events=["data: existing-team\n\n"],
    )
    repo = FakeOpenApiRepository(
        publication=_publication(
            public_id="public-team",
            target_type="expert_team",
            target_id="team-1",
        ),
    )

    def fake_get_team(team_id: str):
        assert team_id == "team-1"
        return SimpleNamespace(
            id="team-1", enabled=True, leader_agent_id="leader-agent"
        )

    def fake_create_run(**kwargs):
        raise AssertionError(f"should not create duplicate run: {kwargs}")

    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    monkeypatch.setattr(open_api, "get_expert_team_template", fake_get_team)
    monkeypatch.setattr(open_api, "create_expert_team_run", fake_create_run)
    monkeypatch.setattr(
        open_api,
        "get_latest_expert_team_run_by_chat",
        lambda chat_id: SimpleNamespace(
            id="existing-run-1", root_chat_id=chat_id
        ),
    )

    response = await open_api.post_open_message(
        "public-team",
        OpenMessageRequest(
            external_user_id="ext-user",
            external_session_id="team-session",
            message="build it",
        ),
        _request(workspace=workspace),
    )

    assert response.headers["x-qwenpaw-expert-team-run-id"] == "existing-run-1"

    body = await _consume_streaming_response(response)

    assert body == "data: existing-team\n\n"
    assert repo.invocations[0]["status"] == "running"


@pytest.mark.asyncio
async def test_post_open_message_expert_team_existing_run_prefers_active_payload_run_id(
    monkeypatch,
):
    workspace = _workspace(agent_id="leader-agent")
    workspace.task_tracker = FakeTaskTracker(
        is_new_run=False,
        existing_events=["data: existing-team\n\n"],
        active_payload={"run_id": "pending-run-from-active-payload"},
    )
    repo = FakeOpenApiRepository(
        publication=_publication(
            public_id="public-team",
            target_type="expert_team",
            target_id="team-1",
        ),
    )

    def fake_get_team(team_id: str):
        assert team_id == "team-1"
        return SimpleNamespace(
            id="team-1", enabled=True, leader_agent_id="leader-agent"
        )

    def fake_create_run(**kwargs):
        raise AssertionError(f"should not create duplicate run: {kwargs}")

    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    monkeypatch.setattr(open_api, "get_expert_team_template", fake_get_team)
    monkeypatch.setattr(open_api, "create_expert_team_run", fake_create_run)
    monkeypatch.setattr(
        open_api,
        "get_latest_expert_team_run_by_chat",
        lambda chat_id: SimpleNamespace(
            id="stale-db-run", root_chat_id=chat_id
        ),
    )

    response = await open_api.post_open_message(
        "public-team",
        OpenMessageRequest(
            external_user_id="ext-user",
            external_session_id="team-session",
            message="build it",
        ),
        _request(workspace=workspace),
    )

    assert (
        response.headers["x-qwenpaw-expert-team-run-id"]
        == "pending-run-from-active-payload"
    )


def test_open_api_router_is_mounted_at_root_open_prefix_only(monkeypatch):
    app = FastAPI()
    app.include_router(open_api.router, prefix="/api")
    repo = FakeOpenApiRepository(
        publication=_publication(public_id="route-probe"),
    )
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    client = TestClient(app, raise_server_exceptions=False)
    payload = {
        "external_user_id": "route-probe",
        "message": "hello",
    }

    assert (
        client.post(
            "/api/open/v1/targets/route-probe/messages",
            json=payload,
        ).status_code
        != 404
    )
    assert (
        client.post(
            "/api/user/open/v1/targets/route-probe/messages",
            json=payload,
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/admin/open/v1/targets/route-probe/messages",
            json=payload,
        ).status_code
        == 404
    )
