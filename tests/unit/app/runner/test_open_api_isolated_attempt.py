from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
from qwenpaw.agents.message_compat import Msg
from qwenpaw.runtime.tracing import trace
from qwenpaw.runtime.contracts import ContentType, TextContent

from qwenpaw.app.channels.console.channel import ConsoleChannel
from qwenpaw.app.runner import runner as runner_module
from qwenpaw.app.runner.runner import AgentRunner
from qwenpaw.app.open_api.execution_mode import bind_isolated_agent_open_api


class RecordingSession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_session_state_dict(self, **_kwargs):
        self.calls.append("get")
        return {}

    async def update_session_state(self, **_kwargs):
        self.calls.append("update")

    async def load_session_state(self, **_kwargs):
        self.calls.append("load")

    async def save_session_state(self, **_kwargs):
        self.calls.append("save")


class RecordingChats:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_or_create_chat(self, *_args, **_kwargs):
        self.calls.append("create")
        return SimpleNamespace(id="chat-1")

    async def touch_chat(self, _chat_id):
        self.calls.append("touch")


class FakeAgent:
    constructed: ClassVar[list[dict]] = []

    def __init__(self, **kwargs):
        self.constructed.append(kwargs)
        self.toolkit = SimpleNamespace(skills={})

    async def register_mcp_clients(self):
        return None

    def set_console_output_enabled(self, *, enabled):
        assert enabled is False

    def rebuild_sys_prompt(self):
        return None


def _agent_config():
    return SimpleNamespace(
        id="agent-1",
        name="Agent",
        running=SimpleNamespace(shell_command_executable=None),
        plan=SimpleNamespace(enabled=False),
        orchestration=SimpleNamespace(enabled=False),
    )


async def _run(
    monkeypatch,
    tmp_path: Path,
    *,
    channel: str,
    channel_meta: dict,
    message: str = "hello",
    trusted_isolation: bool = False,
    mission_handler=None,
    mission_detector=None,
    request_context=None,
):
    FakeAgent.constructed = []
    session = RecordingSession()
    chats = RecordingChats()
    runtime = AgentRunner(agent_id="agent-1", workspace_dir=tmp_path)
    runtime.session = session
    runtime.memory_manager = object()
    runtime.context_manager = object()
    runtime.set_chat_manager(chats)

    monkeypatch.setattr(runner_module, "load_agent_config", lambda _id: _agent_config())
    monkeypatch.setattr(runner_module, "QwenPawAgent", FakeAgent)
    monkeypatch.setattr(
        runner_module,
        "maybe_handle_mission_command",
        mission_handler or _async_none,
    )
    monkeypatch.setattr(
        runner_module,
        "detect_active_mission_phase",
        mission_detector or (lambda *_args, **_kwargs: None),
    )

    async def standard_turn(**_kwargs):
        yield Msg(name="assistant", role="assistant", content="ok"), True, True

    monkeypatch.setattr(
        runner_module,
        "_run_standard_or_orchestrated_turn",
        standard_turn,
    )
    effective_meta = dict(channel_meta)
    if trusted_isolation:
        bind_isolated_agent_open_api(effective_meta)
    request = SimpleNamespace(
        session_id="open:app:pub:user:session:attempt:abc",
        user_id="owner",
        channel=channel,
        channel_meta=effective_meta,
        request_context=request_context,
    )
    output = [
        item
        async for item in runtime.query_handler(
            [Msg(name="user", role="user", content=message)],
            request,
        )
    ]
    return session, chats, FakeAgent.constructed[0], output


@pytest.mark.asyncio
async def test_direct_agent_open_api_installs_response_format_policy_after_merge(
    monkeypatch,
    tmp_path,
):
    installed = []
    monkeypatch.setattr(
        runner_module,
        "install_open_api_agent_response_format",
        lambda agent: installed.append(agent) or True,
    )

    _session, _chats, agent_args, _output = await _run(
        monkeypatch,
        tmp_path,
        channel="open:app-1",
        channel_meta={
            "target_type": "agent",
            "publication_id": "publication-1",
            "open_invocation_id": "invocation-1",
        },
        request_context={"_open_api_direct_agent_execution": False},
    )

    assert agent_args["request_context"][
        "_open_api_direct_agent_execution"
    ] is True
    assert len(installed) == 1


@pytest.mark.asyncio
async def test_forged_request_context_cannot_install_response_format_policy(
    monkeypatch,
    tmp_path,
):
    installed = []
    monkeypatch.setattr(
        runner_module,
        "install_open_api_agent_response_format",
        lambda agent: installed.append(agent) or True,
    )

    _session, _chats, agent_args, _output = await _run(
        monkeypatch,
        tmp_path,
        channel="console",
        channel_meta={},
        request_context={"_open_api_direct_agent_execution": True},
    )

    assert agent_args["request_context"][
        "_open_api_direct_agent_execution"
    ] is False
    assert installed == []


@pytest.mark.asyncio
async def test_fallback_model_is_installed_only_for_trusted_open_api(
    monkeypatch,
    tmp_path,
):
    from qwenpaw.agents import model_factory
    from qwenpaw.config import utils as config_utils

    fallback_config = SimpleNamespace(
        enabled=True,
        provider_id="volcengine-cn",
        model="deepseek-v4-flash",
        json_object=True,
    )
    monkeypatch.setattr(
        config_utils,
        "load_config",
        lambda: SimpleNamespace(
            open_api=SimpleNamespace(fallback_model=fallback_config),
        ),
    )
    fallback_model = object()
    monkeypatch.setattr(
        model_factory,
        "create_wrapped_model_for_slot",
        lambda *_args, **_kwargs: fallback_model,
    )
    installed = []
    monkeypatch.setattr(
        runner_module,
        "install_open_api_model_failover",
        lambda agent, model, **kwargs: installed.append(
            (agent, model, kwargs),
        ),
    )
    monkeypatch.setattr(
        runner_module,
        "install_open_api_agent_response_format",
        lambda *_args, **_kwargs: True,
    )

    await _run(
        monkeypatch,
        tmp_path,
        channel="open:app-1",
        channel_meta={
            "target_type": "agent",
            "publication_id": "publication-1",
            "open_invocation_id": "invocation-1",
        },
    )

    assert len(installed) == 1
    assert installed[0][1] is fallback_model
    assert installed[0][2]["fallback_label"] == (
        "volcengine-cn/deepseek-v4-flash"
    )


async def _async_none(**_kwargs):
    return None


@pytest.mark.asyncio
async def test_isolated_capability_survives_console_and_tracing_serialization(
    tmp_path,
):
    """Catch non-JSON capability values before AgentScope invokes the runner."""

    async def unused_process(_request):
        if False:
            yield None

    channel = ConsoleChannel(
        process=unused_process,
        enabled=True,
        bot_prefix="",
        workspace_dir=tmp_path,
    )
    meta = {
        "session_id": "open:app:target:user:session:attempt:abc",
        "target_type": "agent",
        "execution_mode": "isolated_attempt",
        "open_invocation_id": "invocation-1",
    }
    bind_isolated_agent_open_api(meta)
    request = channel.build_agent_request_from_native(
        {
            "channel_id": "open:app-1",
            "sender_id": "owner",
            "content_parts": [
                TextContent(type=ContentType.TEXT, text="hello"),
            ],
            "meta": meta,
        },
    )

    @trace()
    async def traced_process(actual_request):
        assert actual_request is request
        return "ok"

    assert await traced_process(request) == "ok"


@pytest.mark.asyncio
async def test_persistent_open_api_keeps_session_memory_and_chat_behavior(
    monkeypatch,
    tmp_path,
):
    session, chats, agent_args, output = await _run(
        monkeypatch,
        tmp_path,
        channel="open:app-1",
        channel_meta={"target_type": "agent"},
    )

    assert session.calls == ["load", "save"]
    assert chats.calls == ["create", "touch"]
    assert agent_args["memory_manager"] is not None
    assert agent_args["request_context"]["_persist_context_dialog"] is True
    assert output[0][0].get_text_content() == "ok"


@pytest.mark.asyncio
async def test_isolated_agent_open_api_skips_session_memory_and_chat_persistence(
    monkeypatch,
    tmp_path,
):
    session, chats, agent_args, output = await _run(
        monkeypatch,
        tmp_path,
        channel="open:app-1",
        channel_meta={
            "target_type": "agent",
            "execution_mode": "isolated_attempt",
            "open_invocation_id": "invocation-1",
        },
        trusted_isolation=True,
    )

    assert session.calls == []
    assert chats.calls == []
    assert agent_args["memory_manager"] is None
    assert agent_args["request_context"]["_persist_context_dialog"] is False
    assert output[0][0].get_text_content() == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("channel", "channel_meta"),
    [
        (
            "console",
            {
                "target_type": "agent",
                "execution_mode": "isolated_attempt",
                "open_invocation_id": "forged",
            },
        ),
        (
            "open:app-1",
            {
                "target_type": "expert_team",
                "execution_mode": "isolated_attempt",
                "open_invocation_id": "forged",
            },
        ),
        (
            "open:app-1",
            {
                "target_type": "agent",
                "metadata": {"execution_mode": "isolated_attempt"},
            },
        ),
        (
            "open:app-1",
            {
                "target_type": "agent",
                "execution_mode": "isolated_attempt",
                "open_invocation_id": "forged-complete-shape",
                "_isolated_agent_open_api_capability": "0" * 64,
            },
        ),
    ],
)
async def test_non_agent_open_api_inputs_cannot_activate_isolation(
    monkeypatch,
    tmp_path,
    channel,
    channel_meta,
):
    session, chats, agent_args, _output = await _run(
        monkeypatch,
        tmp_path,
        channel=channel,
        channel_meta=channel_meta,
    )

    assert session.calls == ["load", "save"]
    assert chats.calls == ["create", "touch"]
    assert agent_args["memory_manager"] is not None
    assert agent_args["request_context"]["_persist_context_dialog"] is True


@pytest.mark.asyncio
async def test_isolated_open_api_control_text_cannot_bypass_isolation(
    monkeypatch,
    tmp_path,
):
    async def forbidden_command(*_args, **_kwargs):
        pytest.fail("isolated OpenAPI input must not enter stateful command path")
        yield

    monkeypatch.setattr(runner_module, "run_command_path", forbidden_command)

    session, chats, agent_args, output = await _run(
        monkeypatch,
        tmp_path,
        channel="open:app-1",
        channel_meta={
            "target_type": "agent",
            "execution_mode": "isolated_attempt",
            "open_invocation_id": "invocation-1",
        },
        message="/history",
        trusted_isolation=True,
    )

    assert session.calls == []
    assert chats.calls == []
    assert agent_args["memory_manager"] is None
    assert output[0][0].get_text_content() == "ok"


@pytest.mark.asyncio
async def test_isolated_open_api_mission_text_cannot_load_shared_mission_state(
    monkeypatch,
    tmp_path,
):
    async def forbidden_mission(*_args, **_kwargs):
        pytest.fail("isolated OpenAPI input must not enter mission persistence")

    def forbidden_detection(*_args, **_kwargs):
        pytest.fail("isolated OpenAPI input must not load active mission state")

    session, chats, agent_args, output = await _run(
        monkeypatch,
        tmp_path,
        channel="open:app-1",
        channel_meta={
            "target_type": "agent",
            "execution_mode": "isolated_attempt",
            "open_invocation_id": "invocation-1",
        },
        message="/mission do work",
        trusted_isolation=True,
        mission_handler=forbidden_mission,
        mission_detector=forbidden_detection,
    )

    assert session.calls == []
    assert chats.calls == []
    assert agent_args["memory_manager"] is None
    assert output[0][0].get_text_content() == "ok"
