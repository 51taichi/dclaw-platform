from __future__ import annotations

from types import SimpleNamespace

import pytest
from agentscope.message import Msg

from qwenpaw.app.runner import runner as runner_module
from qwenpaw.app.runner.runner import AgentRunner
from qwenpaw.config.config import OrchestrationConfig
from qwenpaw.app.workspace.orchestration import WorkspaceTurnResult
from qwenpaw.app.sealed_agents import registry as registry_module


def _request():
    return SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        channel="console",
        channel_meta={},
    )


def _command_message():
    return Msg(name="user", role="user", content="/new")


@pytest.mark.asyncio
async def test_sealed_agent_uses_the_same_command_path(monkeypatch):
    class SealedRegistry:
        def is_sealed(self, _agent_id):
            return True

    command_result = Msg(
        name="assistant",
        role="assistant",
        content="ordinary command response",
    )

    async def fake_command_path(_request, _messages, _runner):
        yield command_result, True

    monkeypatch.setattr(
        registry_module,
        "get_sealed_agent_registry",
        lambda: SealedRegistry(),
    )
    monkeypatch.setattr(
        runner_module,
        "run_command_path",
        fake_command_path,
    )
    runtime = AgentRunner(agent_id="sealed-agent")

    actual = [
        item
        async for item in runtime.query_handler(
            [_command_message()],
            _request(),
        )
    ]

    assert actual == [(command_result, True)]


@pytest.mark.asyncio
async def test_ordinary_agent_command_never_reads_sealed_registry(monkeypatch):
    def fail_registry_lookup():
        pytest.fail("ordinary Runner must not read sealed Registry")

    command_result = Msg(
        name="assistant",
        role="assistant",
        content="ordinary command response",
    )

    async def fake_command_path(_request, _messages, _runner):
        yield command_result, True

    monkeypatch.setattr(
        registry_module,
        "get_sealed_agent_registry",
        fail_registry_lookup,
    )
    monkeypatch.setattr(
        runner_module,
        "run_command_path",
        fake_command_path,
    )
    runtime = AgentRunner(agent_id="ordinary-agent")

    actual = [
        item
        async for item in runtime.query_handler(
            [_command_message()],
            _request(),
        )
    ]

    assert actual == [(command_result, True)]


@pytest.mark.asyncio
async def test_undeclared_business_turn_uses_exact_standard_agent_path(
    monkeypatch,
    tmp_path,
):
    calls = []

    class Agent:
        async def __call__(self, messages):
            calls.append(messages)
            return Msg(name="assistant", role="assistant", content="standard")

    async def fake_stream(*, agents, coroutine_task):
        assert len(agents) == 1
        yield await coroutine_task, True

    def fail_authorization(**_kwargs):
        pytest.fail("undeclared Agent must not resolve orchestration authorization")

    monkeypatch.setattr(
        runner_module,
        "_stream_printing_messages_interruptible",
        fake_stream,
    )
    monkeypatch.setattr(
        runner_module,
        "resolve_active_workspace_authorization",
        fail_authorization,
        raising=False,
    )
    messages = [Msg(name="user", role="user", content="hello")]

    actual = [
        item
        async for item in runner_module._run_standard_or_orchestrated_turn(
            agent=Agent(),
            messages=messages,
            request=_request(),
            query="hello",
            mission_info=None,
            agent_id="ordinary-agent",
            agent_name="Agent",
            workspace_root=tmp_path,
            orchestration=OrchestrationConfig(),
        )
    ]

    assert len(actual) == 1
    assert actual[0][0].content == "standard"
    assert actual[0][1:] == (True, True)
    assert calls == [messages]


@pytest.mark.asyncio
async def test_declared_turn_never_falls_back_to_direct_model_on_failure(
    monkeypatch,
    tmp_path,
):
    class Agent:
        async def __call__(self, _messages):
            pytest.fail("Runner must not directly invoke the model as fallback")

    authorization = SimpleNamespace(
        installation_id="installation-1",
        granted_capabilities={},
    )
    monkeypatch.setattr(
        runner_module,
        "resolve_active_workspace_authorization",
        lambda **_kwargs: authorization,
        raising=False,
    )
    from qwenpaw.app.super_experts import composition as platform_module

    class PlatformService:
        def list_session_events(self, **_kwargs):
            return []

    monkeypatch.setattr(
        platform_module,
        "get_super_expert_platform_service",
        lambda: PlatformService(),
    )

    async def fail_closed(**_kwargs):
        assert callable(_kwargs["business_call"])
        return WorkspaceTurnResult(error_code="orchestration_timeout")

    monkeypatch.setattr(
        runner_module,
        "run_workspace_orchestration_turn",
        fail_closed,
        raising=False,
    )
    config = OrchestrationConfig(
        enabled=True,
        contract_version="1",
        entrypoint="runtime.py:create_runtime",
        required_host_capabilities=(
            "agent.execute",
            "session.context",
            "runtime.trace",
            "runtime.complete",
            "runtime.fail",
        ),
    )

    actual = [
        item
        async for item in runner_module._run_standard_or_orchestrated_turn(
            agent=Agent(),
            messages=[Msg(name="user", role="user", content="hello")],
            request=_request(),
            query="hello",
            mission_info=None,
            agent_id="generic-agent",
            agent_name="Generic",
            workspace_root=tmp_path,
            orchestration=config,
        )
    ]

    assert actual[0][0].content == "本轮处理未能安全完成，请稍后重试。"
    assert actual[0][1:] == (True, False)


@pytest.mark.asyncio
async def test_declared_turn_passes_loaded_conversation_history_to_runtime(
    monkeypatch,
    tmp_path,
):
    prior_history = [
        Msg(name="user", role="user", content="我是做就业培训的"),
        Msg(name="assistant", role="assistant", content="培训面向哪些人？"),
    ]
    current_messages = [
        Msg(name="user", role="user", content="失业人员，天门市，线下报名"),
    ]

    class Memory:
        def __init__(self):
            self.added = []

        async def get_memory(self, *, prepend_summary=True):
            assert prepend_summary is True
            return prior_history

        async def add(self, message):
            self.added.append(message)

    class Agent:
        def __init__(self):
            self.memory = Memory()

    agent = Agent()

    authorization = SimpleNamespace(
        installation_id="installation-1",
        granted_capabilities={},
    )
    monkeypatch.setattr(
        runner_module,
        "resolve_active_workspace_authorization",
        lambda **_kwargs: authorization,
        raising=False,
    )
    from qwenpaw.app.super_experts import composition as platform_module

    class PlatformService:
        def list_session_events(self, **_kwargs):
            return []

    monkeypatch.setattr(
        platform_module,
        "get_super_expert_platform_service",
        lambda: PlatformService(),
    )

    async def capture_history(**kwargs):
        assert kwargs["original_messages"] == current_messages
        assert kwargs["conversation_history"] == prior_history
        return WorkspaceTurnResult(
            message={"name": "assistant", "role": "assistant", "content": "继续"},
        )

    monkeypatch.setattr(
        runner_module,
        "run_workspace_orchestration_turn",
        capture_history,
        raising=False,
    )
    config = OrchestrationConfig(
        enabled=True,
        contract_version="1",
        entrypoint="runtime.py:create_runtime",
        required_host_capabilities=(
            "agent.execute",
            "session.context",
            "runtime.trace",
            "runtime.complete",
            "runtime.fail",
        ),
    )

    actual = [
        item
        async for item in runner_module._run_standard_or_orchestrated_turn(
            agent=agent,
            messages=current_messages,
            request=_request(),
            query="失业人员，天门市，线下报名",
            mission_info=None,
            agent_id="generic-agent",
            agent_name="Generic",
            workspace_root=tmp_path,
            orchestration=config,
        )
    ]

    assert actual[0][0].content == "继续"
    assert actual[0][1:] == (True, True)
    assert agent.memory.added[:1] == current_messages
    assert agent.memory.added[1].role == "assistant"
    assert agent.memory.added[1].content == "继续"
