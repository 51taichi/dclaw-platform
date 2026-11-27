from pathlib import Path

import pytest

from qwenpaw.agents.react_agent import (
    SEALED_DENIED_BUILTIN_TOOLS,
    resolve_agent_runtime_boundary,
    tool_allowed_for_runtime,
)


def test_sealed_runtime_uses_private_source_and_external_session_root(
    tmp_path,
):
    source = tmp_path / "sealed_agents" / "releases" / "luyu" / "v1" / "agent"
    boundary = resolve_agent_runtime_boundary(
        agent_id="luyu",
        session_id="chat-1",
        configured_workspace=source,
        sealed=True,
        working_dir=tmp_path,
    )

    assert boundary.prompt_root == source.resolve()
    assert boundary.skills_root == source.resolve()
    assert (
        boundary.session_root
        == (tmp_path / "sealed_sessions" / "luyu" / "chat-1").resolve()
    )
    assert not boundary.session_root.is_relative_to(source.resolve())


def test_standard_runtime_keeps_existing_session_layout(tmp_path):
    source = tmp_path / "agents" / "writer"
    boundary = resolve_agent_runtime_boundary(
        agent_id="writer",
        session_id="chat-1",
        configured_workspace=source,
        sealed=False,
        working_dir=tmp_path,
    )

    assert boundary.session_root == (source / "sessions_data" / "chat-1")


def test_sealed_runtime_denies_asset_exfiltration_and_plugin_tools():
    assert "execute_shell_command" in SEALED_DENIED_BUILTIN_TOOLS
    assert not tool_allowed_for_runtime(
        "read_file",
        sealed=True,
        unrestricted=False,
        plugin_tool=False,
    )
    assert not tool_allowed_for_runtime(
        "send_file_to_user",
        sealed=True,
        unrestricted=False,
        plugin_tool=False,
    )
    assert not tool_allowed_for_runtime(
        "custom_plugin",
        sealed=True,
        unrestricted=False,
        plugin_tool=True,
    )
    assert tool_allowed_for_runtime(
        "web_search",
        sealed=True,
        unrestricted=False,
        plugin_tool=False,
    )
    assert tool_allowed_for_runtime(
        "read_agent_skill",
        sealed=True,
        unrestricted=False,
        plugin_tool=False,
    )
    assert tool_allowed_for_runtime(
        "read_file",
        sealed=False,
        unrestricted=False,
        plugin_tool=False,
    )


def test_super_expert_inherits_ordinary_builtin_and_plugin_tools():
    assert tool_allowed_for_runtime(
        "execute_shell_command",
        sealed=True,
        unrestricted=True,
        plugin_tool=False,
    )
    assert tool_allowed_for_runtime(
        "custom_plugin",
        sealed=True,
        unrestricted=True,
        plugin_tool=True,
    )


@pytest.mark.asyncio
async def test_super_expert_registers_configured_mcp_clients():
    class Toolkit:
        def __init__(self):
            self.registered = []

        async def register_mcp_client(self, client, **kwargs):
            self.registered.append((client, kwargs))

    class Client:
        name = "platform"
        read_timeout_seconds = 15

    from qwenpaw.agents.react_agent import QwenPawAgent

    agent = QwenPawAgent.__new__(QwenPawAgent)
    agent._sealed_runtime = True
    agent._sealed_runtime_features = frozenset({"mcp_client"})
    agent._mcp_clients = [Client()]
    agent.toolkit = Toolkit()

    await agent.register_mcp_clients()

    assert [client.name for client, _kwargs in agent.toolkit.registered] == [
        "platform",
    ]


def test_super_expert_registers_packaged_and_platform_skills(
    monkeypatch,
    tmp_path,
):
    from qwenpaw.agents import react_agent

    packaged = tmp_path / "release"
    overlay = tmp_path / "overlay"
    monkeypatch.setattr(
        react_agent,
        "ensure_skills_initialized",
        lambda root: None,
    )
    monkeypatch.setattr(
        react_agent,
        "resolve_effective_skills",
        lambda root, *_args, **_kwargs: [
            "core" if Path(root) == packaged else "pdf",
        ],
    )
    monkeypatch.setattr(
        react_agent,
        "get_workspace_skills_dir",
        lambda root: Path(root) / "skills",
    )
    for root, name in ((packaged, "core"), (overlay, "pdf")):
        (root / "skills" / name).mkdir(parents=True)

    class Toolkit:
        def __init__(self):
            self.paths = []

        def register_agent_skill(self, path):
            self.paths.append(Path(path))

    agent = react_agent.QwenPawAgent.__new__(react_agent.QwenPawAgent)
    agent._request_context = {"channel": "console"}
    agent._skill_workspace_dirs = [packaged, overlay]
    toolkit = Toolkit()

    agent._register_skills(toolkit)

    assert toolkit.paths == [
        packaged / "skills" / "core",
        overlay / "skills" / "pdf",
    ]
