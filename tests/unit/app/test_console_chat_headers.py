# -*- coding: utf-8 -*-
"""Tests for console chat streaming response metadata."""
from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.task_limits import TaskConcurrencyLimiter
from qwenpaw.app.billing.usage import InsufficientUsageCreditsError
from qwenpaw.app.routers import console


class _FakeConsoleChannel:
    def resolve_session_id(self, sender_id: str, channel_meta: dict) -> str:
        _ = sender_id
        return channel_meta["session_id"]

    async def stream_one(self, *args, **kwargs):
        _ = args, kwargs
        if False:
            yield None


class _FakeChannelManager:
    async def get_channel(self, name: str):
        assert name == "console"
        return _FakeConsoleChannel()


class _FakeChatManager:
    def __init__(self, chat_id: str = "chat-real-id"):
        self.chat_id = chat_id
        self.calls: list[dict[str, str]] = []

    async def get_or_create_chat(
        self,
        session_id: str,
        user_id: str,
        channel: str,
        name: str,
    ):
        self.calls.append(
            {
                "session_id": session_id,
                "user_id": user_id,
                "channel": channel,
                "name": name,
            },
        )
        return SimpleNamespace(id=self.chat_id, name="existing", meta={})


class _FakeTaskTracker:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    async def start_new(
        self,
        chat_id: str,
        native_payload,
        stream_one,
        **kwargs,
    ):
        self.calls.append(
            {
                "chat_id": chat_id,
                "native_payload": native_payload,
                "stream_one": stream_one,
                "kwargs": kwargs,
            },
        )
        return object(), None

    async def stream_from_queue(self, queue, chat_id: str):
        _ = queue, chat_id
        if False:
            yield ""


class _FakeRequest:
    def __init__(self, limiter=None):
        self.state = SimpleNamespace(user_id=42)
        if limiter is not None:
            self.app = SimpleNamespace(
                state=SimpleNamespace(task_limiter=limiter),
            )


@pytest.mark.asyncio
async def test_console_chat_returns_503_when_channel_manager_is_unavailable(
    monkeypatch,
):
    async def fake_get_agent_for_request(request):
        _ = request
        return SimpleNamespace(channel_manager=None)

    monkeypatch.setattr(
        console,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )

    with pytest.raises(HTTPException) as exc_info:
        await console.post_console_chat(
            {
                "channel": "console",
                "user_id": "default",
                "session_id": "draft-session",
                "input": [],
            },
            request=_FakeRequest(),
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Console channel manager is unavailable"


@pytest.mark.asyncio
async def test_console_chat_stream_response_exposes_real_chat_id(monkeypatch):
    workspace = SimpleNamespace(
        channel_manager=_FakeChannelManager(),
        chat_manager=_FakeChatManager(),
        task_tracker=_FakeTaskTracker(),
    )

    async def fake_get_agent_for_request(request):
        _ = request
        return workspace

    monkeypatch.setattr(
        console,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )

    response = await console.post_console_chat(
        {
            "channel": "console",
            "user_id": "default",
            "session_id": "draft-session",
            "input": [],
        },
        request=_FakeRequest(),
    )

    assert response.headers["x-qwenpaw-chat-id"] == "chat-real-id"
    assert response.headers["x-qwenpaw-session-id"] == "draft-session"


def test_console_chat_dict_input_text_stays_single_text_part():
    native_payload = console._extract_session_and_payload(
        {
            "channel": "console",
            "user_id": "frontend-default",
            "session_id": "precreated-chat-id",
            "chat_id": "precreated-chat-id",
            "input": [{"role": "user", "content": "整理项目进展"}],
        },
    )

    assert len(native_payload["content_parts"]) == 1
    part = native_payload["content_parts"][0]
    assert getattr(part, "type", None) == "text"
    assert getattr(part, "text", None) == "整理项目进展"


def test_console_chat_uses_chat_id_when_session_id_is_missing():
    native_payload = console._extract_session_and_payload(
        {
            "channel": "console",
            "user_id": "frontend-default",
            "chat_id": "precreated-chat-id",
            "input": [{"role": "user", "content": "整理项目进展"}],
        },
    )

    assert native_payload["meta"]["session_id"] == "precreated-chat-id"


@pytest.mark.asyncio
async def test_console_chat_keeps_precreated_chat_session_with_request_user(
    monkeypatch,
):
    chat_manager = _FakeChatManager(chat_id="precreated-chat-id")
    workspace = SimpleNamespace(
        channel_manager=_FakeChannelManager(),
        chat_manager=chat_manager,
        task_tracker=_FakeTaskTracker(),
    )

    async def fake_get_agent_for_request(request):
        _ = request
        return workspace

    monkeypatch.setattr(
        console,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )

    response = await console.post_console_chat(
        {
            "channel": "console",
            "user_id": "frontend-default",
            "session_id": "precreated-chat-id",
            "input": [],
        },
        request=_FakeRequest(),
    )

    assert chat_manager.calls[0]["session_id"] == "precreated-chat-id"
    assert chat_manager.calls[0]["user_id"] == "42"
    assert response.headers["x-qwenpaw-chat-id"] == "precreated-chat-id"
    assert response.headers["x-qwenpaw-session-id"] == "precreated-chat-id"


@pytest.mark.asyncio
async def test_console_chat_can_start_task_without_sse_stream(monkeypatch):
    chat_manager = _FakeChatManager(chat_id="mobile-task-id")
    workspace = SimpleNamespace(
        channel_manager=_FakeChannelManager(),
        chat_manager=chat_manager,
        task_tracker=_FakeTaskTracker(),
    )

    async def fake_get_agent_for_request(request):
        _ = request
        return workspace

    monkeypatch.setattr(
        console,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )

    response = await console.post_console_chat(
        {
            "channel": "console",
            "user_id": "frontend-default",
            "session_id": "mobile-task-id",
            "stream": False,
            "input": [{"role": "user", "content": "整理项目进展"}],
        },
        request=_FakeRequest(),
    )

    payload = json.loads(response.body.decode("utf-8"))

    assert payload == {
        "chat_id": "mobile-task-id",
        "session_id": "mobile-task-id",
        "expert_team_run_id": "",
        "status": "started",
    }
    assert response.media_type == "application/json"
    assert workspace.task_tracker.calls[0]["chat_id"] == "mobile-task-id"
    parts = workspace.task_tracker.calls[0]["native_payload"]["content_parts"]
    assert len(parts) == 1
    assert getattr(parts[0], "type", None) == "text"
    assert getattr(parts[0], "text", None) == "整理项目进展"


@pytest.mark.asyncio
async def test_console_chat_expert_team_run_uses_authenticated_user(monkeypatch):
    workspace = SimpleNamespace(
        channel_manager=_FakeChannelManager(),
        chat_manager=_FakeChatManager(),
        task_tracker=_FakeTaskTracker(),
    )
    captured: dict[str, str] = {}

    async def fake_get_agent_for_request(request):
        _ = request
        return workspace

    def fake_create_expert_team_run(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="run-1")

    async def fake_attach_run_to_chat(*args, **kwargs):
        _ = args, kwargs

    monkeypatch.setattr(console, "get_agent_for_request", fake_get_agent_for_request)
    monkeypatch.setattr(console, "create_expert_team_run", fake_create_expert_team_run)
    monkeypatch.setattr(console, "attach_run_to_chat", fake_attach_run_to_chat)

    response = await console.post_console_chat(
        {
            "channel": "console",
            "user_id": "frontend-default",
            "session_id": "draft-session",
            "expert_team_id": "software_dev_team",
            "input": [],
        },
        request=_FakeRequest(),
    )

    assert response.headers["x-qwenpaw-expert-team-run-id"] == "run-1"
    assert captured["user_id"] == "42"


@pytest.mark.asyncio
async def test_console_chat_returns_429_when_task_limit_is_full(monkeypatch):
    workspace = SimpleNamespace(
        agent_id="default",
        channel_manager=_FakeChannelManager(),
        chat_manager=_FakeChatManager(),
        task_tracker=_FakeTaskTracker(),
    )
    limiter = TaskConcurrencyLimiter(
        max_global=1,
        max_per_agent=1,
        max_per_user=1,
    )
    held = await limiter.try_acquire(agent_id="default", user_id="42")

    async def fake_get_agent_for_request(request):
        _ = request
        return workspace

    monkeypatch.setattr(console, "get_agent_for_request", fake_get_agent_for_request)

    try:
        with pytest.raises(HTTPException) as exc_info:
            await console.post_console_chat(
                {
                    "channel": "console",
                    "user_id": "42",
                    "session_id": "draft-session",
                    "input": [],
                },
                request=_FakeRequest(limiter),
            )
    finally:
        await held.release()

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_console_producer_emits_safe_insufficient_credit_event(
    monkeypatch,
):
    class _InsufficientChannel(_FakeConsoleChannel):
        async def stream_one(self, *_args, **_kwargs):
            raise InsufficientUsageCreditsError(required=7, available=2)
            yield  # pragma: no cover

    class _Prepared:
        def __init__(self):
            self.finalized = []

        @contextmanager
        def activate(self):
            yield

        def finalize(self, state, error_code=None):
            self.finalized.append((state, error_code))
            return True

        def finalize_completed(self):
            raise AssertionError("insufficient run cannot complete")

    prepared = _Prepared()
    tracker = _FakeTaskTracker()
    workspace = SimpleNamespace(
        channel_manager=SimpleNamespace(
            get_channel=lambda _name: None,
        ),
        chat_manager=_FakeChatManager(),
        task_tracker=tracker,
    )

    async def get_channel(_name):
        return _InsufficientChannel()

    workspace.channel_manager.get_channel = get_channel

    async def fake_get_agent_for_request(_request):
        return workspace

    monkeypatch.setattr(
        console,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )
    monkeypatch.setattr(
        console,
        "prepare_user_billing_execution",
        lambda *_args, **_kwargs: prepared,
    )

    await console.post_console_chat(
        {
            "channel": "console",
            "session_id": "chat-1",
            "input": [{"role": "user", "content": "hello"}],
        },
        request=_FakeRequest(),
    )
    call = tracker.calls[0]
    events = [
        event
        async for event in call["stream_one"](call["native_payload"])
    ]
    payload = json.loads(events[0].removeprefix("data: "))

    assert payload == {
        "type": "billing.error",
        "code": "INSUFFICIENT_CREDITS",
        "available_credits": 2,
        "required_credits": 7,
        "top_up_path": "/wallet",
    }
    assert prepared.finalized == [("failed", "INSUFFICIENT_CREDITS")]


@pytest.mark.asyncio
async def test_continue_message_resumes_paused_team_without_new_run(
    monkeypatch,
):
    class _StartingTracker(_FakeTaskTracker):
        async def start_new(self, *args, **kwargs):
            queue, _ = await super().start_new(*args, **kwargs)
            return queue, True

    tracker = _StartingTracker()
    workspace = SimpleNamespace(
        channel_manager=_FakeChannelManager(),
        chat_manager=_FakeChatManager(chat_id="chat-team"),
        task_tracker=tracker,
    )
    paused = SimpleNamespace(
        id="run-paused",
        team_id="software_dev_team",
        user_id="42",
        state="paused_insufficient_balance",
        billing_usage_order_id="order-1",
        required_credits=5,
        next_member_key="engineer",
        input_text="build it",
    )
    prepared = SimpleNamespace(session=SimpleNamespace(usage_order_id="order-1"))

    async def fake_get_agent_for_request(_request):
        return workspace

    monkeypatch.setattr(console, "get_agent_for_request", fake_get_agent_for_request)
    monkeypatch.setattr(
        console,
        "get_latest_expert_team_run_by_chat",
        lambda _chat_id: paused,
    )
    monkeypatch.setattr(
        console,
        "resume_user_billing_execution",
        lambda *_args, **_kwargs: prepared,
    )
    monkeypatch.setattr(
        console,
        "resume_expert_team_run",
        lambda *_args: paused,
    )
    monkeypatch.setattr(
        console,
        "create_expert_team_run",
        lambda **_kwargs: pytest.fail("continue must not create a new run"),
    )

    response = await console.post_console_chat(
        {
            "channel": "console",
            "session_id": "chat-team",
            "input": [{"role": "user", "content": "继续"}],
        },
        request=_FakeRequest(),
    )

    assert response.headers["x-qwenpaw-expert-team-run-id"] == "run-paused"
    assert tracker.calls[0]["native_payload"]["run_id"] == "run-paused"
