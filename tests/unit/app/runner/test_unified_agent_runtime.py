from __future__ import annotations

from types import SimpleNamespace

import pytest
from agentscope.message import Msg

from qwenpaw.app.runner import runner as runner_module
from qwenpaw.app.runner.runner import AgentRunner
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
