from pathlib import Path

from qwenpaw.agents.react_agent import (
    SEALED_DENIED_BUILTIN_TOOLS,
    resolve_agent_runtime_boundary,
    tool_allowed_for_runtime,
)


def test_sealed_runtime_uses_private_source_and_external_session_root(tmp_path):
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
    assert boundary.session_root == (
        tmp_path / "sealed_sessions" / "luyu" / "chat-1"
    ).resolve()
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
        "read_file", sealed=True, plugin_tool=False
    )
    assert not tool_allowed_for_runtime(
        "send_file_to_user", sealed=True, plugin_tool=False
    )
    assert not tool_allowed_for_runtime(
        "custom_plugin", sealed=True, plugin_tool=True
    )
    assert tool_allowed_for_runtime(
        "web_search", sealed=True, plugin_tool=False
    )
    assert tool_allowed_for_runtime(
        "read_agent_skill", sealed=True, plugin_tool=False
    )
    assert tool_allowed_for_runtime(
        "read_file", sealed=False, plugin_tool=False
    )
