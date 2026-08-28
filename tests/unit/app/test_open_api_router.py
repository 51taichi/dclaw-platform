# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from agentscope_runtime.engine.schemas.agent_schemas import ContentType
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from qwenpaw.app.open_api.runtime import (
    OpenMessageRequest,
    build_open_session_id,
    prepare_open_agent_chat,
    prepare_open_expert_team_chat,
)
from qwenpaw.app.routers import open_api
from qwenpaw.app.task_limits import TaskConcurrencyLimiter


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
    ) -> bool:
        row = self.get_invocation(invocation_id)
        if (
            row is None
            or row.get("status") != "accepted"
            or row.get("execution_owner_token")
        ):
            return False
        row.update(
            status="running",
            status_code=202,
            execution_owner_token=owner_token,
        )
        return True

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


class FakeChannelManager:
    def __init__(self, console_channel: FakeConsoleChannel | None = None) -> None:
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
            ["data: existing\n\n"] if existing_events is None else existing_events
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
) -> dict[str, Any]:
    return {
        "id": publication_id,
        "public_id": public_id,
        "target_type": target_type,
        "target_id": target_id,
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
            },
        )
        return SimpleNamespace(
            invocation_id=invocation_id,
            usage_order_id=f"order-{invocation_id}",
            wallet_id="wallet",
            bound_user_id="owner-1",
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

    def __init__(self):
        self.terminal_snapshot = None

    def note_stream_ready(self):
        return None

    async def wait_for_preflight(self):
        return None

    def note_finalized(self, terminal):
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

    def execution(self):
        return _FakeBillingExecution()


@pytest.fixture(autouse=True)
def _stub_router_billing_runtime(monkeypatch):
    monkeypatch.setattr(
        open_api,
        "create_open_api_billing_runtime",
        lambda: _FakeBillingRuntime(open_api.get_open_api_repository()),
    )


def test_build_open_session_id_is_stable_and_namespaced():
    assert (
        build_open_session_id("app-1", "public-agent", "ext-user", "session-1")
        == "open:app-1:public-agent:ext-user:session-1"
    )
    assert (
        build_open_session_id("app-1", "public-agent", "ext user", "bad header\r\n")
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
    assert prepared.session_id == "open:app-1:public-agent:ext-user:ext-session"
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
async def test_post_open_message_returns_404_when_publication_is_missing(monkeypatch):
    repo = FakeOpenApiRepository(publication=None)
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)

    with pytest.raises(HTTPException) as exc_info:
        await open_api.post_open_message(
            "missing-public",
            OpenMessageRequest(external_user_id="u", external_session_id="s", message="hi"),
            _request(),
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_post_open_message_rejects_api_key_publication_mismatch(monkeypatch):
    repo = FakeOpenApiRepository(publication=_publication(publication_id="pub-other"))
    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)

    with pytest.raises(HTTPException) as exc_info:
        await open_api.post_open_message(
            "public-agent",
            OpenMessageRequest(external_user_id="u", external_session_id="s", message="hi"),
            _request(publication_id="pub-db-1"),
        )

    assert exc_info.value.status_code == 403


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
    assert response.headers["x-qwenpaw-session-id"] == "open:app-1:public-agent:ext-user:ext-session"
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
    assert workspace.task_tracker.attach_calls[0]["stream_payload"]["meta"]["publication_id"] == "pub-db-1"

    body = await _consume_streaming_response(response)

    assert body.startswith("data: done\n\n")
    assert '"type":"billing.completed"' in body
    assert repo.invocations[0]["status"] == "succeeded"
    assert repo.invocations[0]["status_code"] == 200


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
    workspace.task_tracker = FakeTaskTracker(is_new_run=False, existing_events=[])
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
        return SimpleNamespace(id="team-1", enabled=True, leader_agent_id="leader-agent")

    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    monkeypatch.setattr(open_api, "get_expert_team_template", fake_get_team)
    monkeypatch.setattr(
        open_api,
        "get_latest_expert_team_run_by_chat",
        lambda chat_id: SimpleNamespace(id="existing-run-1", root_chat_id=chat_id),
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
async def test_post_open_message_updates_invocation_failed_when_stream_fails(monkeypatch):
    workspace = _workspace(agent_id="agent-published")
    workspace.channel_manager = FakeChannelManager(FakeConsoleChannel(fail=True))
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
        return SimpleNamespace(id="team-1", enabled=True, leader_agent_id="leader-agent")

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
    monkeypatch.setattr(open_api, "attach_run_to_chat", fake_attach_run_to_chat)
    monkeypatch.setattr(open_api, "ExpertTeamOrchestrator", FakeExpertTeamOrchestrator)

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
    assert stream_payload["root_session_id"] == "open:app-1:public-team:ext-user:team-session"
    assert stream_payload["native_payload"]["meta"]["expert_team_id"] == "team-1"


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
        return SimpleNamespace(id="team-1", enabled=True, leader_agent_id="leader-agent")

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
    monkeypatch.setattr(open_api, "attach_run_to_chat", fake_attach_run_to_chat)
    monkeypatch.setattr(open_api, "ExpertTeamOrchestrator", FakeExpertTeamOrchestrator)

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
        return SimpleNamespace(id="team-1", enabled=True, leader_agent_id="leader-agent")

    def fake_create_run(**kwargs):
        raise AssertionError(f"should not create duplicate run: {kwargs}")

    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    monkeypatch.setattr(open_api, "get_expert_team_template", fake_get_team)
    monkeypatch.setattr(open_api, "create_expert_team_run", fake_create_run)
    monkeypatch.setattr(
        open_api,
        "get_latest_expert_team_run_by_chat",
        lambda chat_id: SimpleNamespace(id="existing-run-1", root_chat_id=chat_id),
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
        return SimpleNamespace(id="team-1", enabled=True, leader_agent_id="leader-agent")

    def fake_create_run(**kwargs):
        raise AssertionError(f"should not create duplicate run: {kwargs}")

    monkeypatch.setattr(open_api, "get_open_api_repository", lambda: repo)
    monkeypatch.setattr(open_api, "get_expert_team_template", fake_get_team)
    monkeypatch.setattr(open_api, "create_expert_team_run", fake_create_run)
    monkeypatch.setattr(
        open_api,
        "get_latest_expert_team_run_by_chat",
        lambda chat_id: SimpleNamespace(id="stale-db-run", root_chat_id=chat_id),
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

    assert client.post(
        "/api/open/v1/targets/route-probe/messages",
        json=payload,
    ).status_code != 404
    assert client.post(
        "/api/user/open/v1/targets/route-probe/messages",
        json=payload,
    ).status_code == 404
    assert client.post(
        "/api/admin/open/v1/targets/route-probe/messages",
        json=payload,
    ).status_code == 404
