# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from qwenpaw.agents import react_agent
from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.config.config import AgentProfileConfig, ToolsConfig


class DummyToolkit:
    def register_tool_function(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class RecordingContextManager:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get_agent_context(self, **kwargs: Any):
        from agentscope.memory import InMemoryMemory

        self.calls.append(kwargs)
        return InMemoryMemory()


def test_session_isolation_keeps_system_prompt_on_agent_root_workspace(
    tmp_path,
    monkeypatch,
) -> None:
    agent_root = tmp_path / "support_agent"
    agent_root.mkdir()
    session_id = "open:app-1:public-support:user-1:session-1"
    captured: dict[str, Any] = {}

    def fake_build_system_prompt_from_working_dir(**kwargs: Any) -> str:
        captured["working_dir"] = Path(kwargs["working_dir"])
        captured["agent_id"] = kwargs["agent_id"]
        return "root profile prompt"

    def fake_react_init(self, **kwargs: Any) -> None:
        captured["sys_prompt"] = kwargs["sys_prompt"]
        object.__setattr__(self, "name", kwargs["name"])
        object.__setattr__(self, "toolkit", kwargs["toolkit"])
        object.__setattr__(self, "memory", kwargs["memory"])

    monkeypatch.setattr(
        react_agent,
        "build_system_prompt_from_working_dir",
        fake_build_system_prompt_from_working_dir,
    )
    monkeypatch.setattr(react_agent, "build_multimodal_hint", lambda: "")
    monkeypatch.setattr(
        react_agent,
        "create_model_and_formatter",
        lambda agent_id=None: (object(), object()),
    )
    monkeypatch.setattr(
        QwenPawAgent,
        "_create_toolkit",
        lambda self, namesake_strategy="skip": DummyToolkit(),
    )
    monkeypatch.setattr(QwenPawAgent, "_register_skills", lambda self, toolkit: None)
    monkeypatch.setattr(QwenPawAgent, "_register_hooks", lambda self: None)
    monkeypatch.setattr(react_agent.ReActAgent, "__init__", fake_react_init)
    monkeypatch.setattr(
        react_agent,
        "CommandHandler",
        lambda **_kwargs: SimpleNamespace(),
    )

    QwenPawAgent(
        agent_config=AgentProfileConfig(
            id="support_agent",
            name="Support Agent",
            workspace_dir=str(agent_root),
        ),
        request_context={
            "session_id": session_id,
            "agent_id": "support_agent",
            "channel": "open:app-1",
        },
        workspace_dir=agent_root,
    )

    assert captured["working_dir"] == agent_root
    assert captured["agent_id"] == "support_agent"
    assert captured["sys_prompt"].startswith("root profile prompt")
    assert "Knowledge-base retrieval policy" in captured["sys_prompt"]
    assert "cite the exact [kb:" in captured["sys_prompt"].lower()
    assert (agent_root / "sessions_data" / session_id).exists()


def test_knowledge_policy_respects_disabled_search_tools() -> None:
    tools = ToolsConfig()
    tools.builtin_tools["search_knowledge"].enabled = False
    tools.builtin_tools["search_mindspace"].enabled = False
    agent = QwenPawAgent.__new__(QwenPawAgent)
    agent._agent_config = SimpleNamespace(tools=tools)

    assert agent._knowledge_retrieval_policy_enabled() is False


def test_isolated_open_api_disables_context_dialog_persistence(
    tmp_path,
    monkeypatch,
) -> None:
    agent_root = tmp_path / "support_agent"
    agent_root.mkdir()
    context_manager = RecordingContextManager()

    monkeypatch.setattr(
        react_agent,
        "build_system_prompt_from_working_dir",
        lambda **_kwargs: "prompt",
    )
    monkeypatch.setattr(react_agent, "build_multimodal_hint", lambda: "")
    monkeypatch.setattr(
        react_agent,
        "create_model_and_formatter",
        lambda agent_id=None: (object(), object()),
    )
    monkeypatch.setattr(
        QwenPawAgent,
        "_create_toolkit",
        lambda self, namesake_strategy="skip": DummyToolkit(),
    )
    monkeypatch.setattr(QwenPawAgent, "_register_skills", lambda self, toolkit: None)
    monkeypatch.setattr(QwenPawAgent, "_register_hooks", lambda self: None)
    monkeypatch.setattr(
        react_agent.ReActAgent,
        "__init__",
        lambda self, **kwargs: (
            object.__setattr__(self, "_module_dict", {}),
            object.__setattr__(self, "name", kwargs["name"]),
            object.__setattr__(self, "toolkit", kwargs["toolkit"]),
            object.__setattr__(self, "memory", kwargs["memory"]),
        )[-1],
    )
    monkeypatch.setattr(
        react_agent,
        "CommandHandler",
        lambda **_kwargs: SimpleNamespace(),
    )

    QwenPawAgent(
        agent_config=AgentProfileConfig(
            id="support_agent",
            name="Support Agent",
            workspace_dir=str(agent_root),
        ),
        context_manager=context_manager,
        request_context={
            "session_id": "isolated-session",
            "agent_id": "support_agent",
            "channel": "open:app-1",
            "execution_mode": "isolated_attempt",
            "target_type": "agent",
            "_persist_context_dialog": False,
        },
        workspace_dir=agent_root,
    )

    assert context_manager.calls == [{"persist_dialog": False}]
