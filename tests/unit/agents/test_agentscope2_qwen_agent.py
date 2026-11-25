from __future__ import annotations

from agentscope.credential import CredentialBase
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import TextBlock
from agentscope.model import ChatModelBase, ChatResponse
from pydantic import BaseModel
import pytest

from qwenpaw.agents import react_agent
from qwenpaw.agents.message_compat import Msg
from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.config.config import AgentProfileConfig
from qwenpaw.plan import PlanNotebook, SubTask


class _RecordingModel(ChatModelBase):
    class Parameters(BaseModel):
        pass

    def __init__(self, text: str = "ok") -> None:
        super().__init__(
            credential=CredentialBase(),
            model="scripted",
            parameters=self.Parameters(),
            stream=False,
        )
        self.formatter = OpenAIChatFormatter()
        self.text = text
        self.calls = []

    async def __call__(self, messages, **_kwargs):
        self.calls.append(list(messages))
        return ChatResponse(
            content=[TextBlock(text=self.text)],
            is_last=True,
        )


def _agent(monkeypatch, workspace, model, notebook=None):
    monkeypatch.setattr(
        react_agent,
        "create_model_and_formatter",
        lambda agent_id=None: (model, OpenAIChatFormatter()),
    )
    monkeypatch.setattr(
        react_agent,
        "get_active_model_supports_multimodal",
        lambda: True,
    )
    return QwenPawAgent(
        agent_config=AgentProfileConfig(
            id="test-agent",
            name="Test Agent",
            workspace_dir=str(workspace),
        ),
        request_context={"agent_id": "test-agent"},
        workspace_dir=workspace,
        plan_notebook=notebook,
    )


@pytest.mark.asyncio
async def test_real_qwen_agent_starts_and_uses_agentscope2_loop(
    monkeypatch,
    tmp_path,
):
    model = _RecordingModel("ready")
    agent = _agent(monkeypatch, tmp_path, model, PlanNotebook())

    result = await agent.reply(Msg("user", "hello", "user"))

    assert result.get_text_content() == "ready"
    assert "create_plan" in agent.toolkit.tools
    assert [item.role for item in agent.state.context] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_plan_hint_is_ephemeral_and_session_state_round_trips(
    monkeypatch,
    tmp_path,
):
    notebook = PlanNotebook()
    await notebook.create_plan(
        name="Upgrade",
        description="Upgrade AgentScope",
        expected_outcome="Tests pass",
        subtasks=[
            SubTask(
                name="Migrate",
                description="Migrate the loop",
                expected_outcome="No legacy API",
            ),
        ],
    )
    first_model = _RecordingModel()
    first = _agent(monkeypatch, tmp_path, first_model, notebook)
    await first.reply(Msg("user", "continue", "user"))

    call_text = "\n".join(
        message.get_text_content()
        for message in first_model.calls[0]
    )
    assert "<system-hint>" in call_text
    assert all(message.name != "plan" for message in first.state.context)

    saved = first.state_dict()
    second = _agent(
        monkeypatch,
        tmp_path,
        _RecordingModel(),
        PlanNotebook(),
    )
    second.load_state_dict(saved)

    assert [
        message.get_text_content() for message in second.state.context
    ] == [
        message.get_text_content() for message in first.state.context
    ]
    assert second.plan_notebook.current_plan is not None
    assert second.plan_notebook.current_plan.name == "Upgrade"
