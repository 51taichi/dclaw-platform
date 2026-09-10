from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from agentscope.tool import Toolkit

from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.agents.tools.agent_skill_reader import (
    MAX_AGENT_SKILL_FILE_BYTES,
    build_read_agent_skill_tool,
)


def _text(response) -> str:
    return response.content[0]["text"]


def _reader(tmp_path: Path):
    skill = tmp_path / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Demo\n\nDo the work.", encoding="utf-8")
    return skill, build_read_agent_skill_tool(
        {"demo": {"name": "demo", "dir": str(skill)}}
    )


def test_reads_only_a_registered_skill_text_file(tmp_path):
    skill, reader = _reader(tmp_path)
    refs = skill / "references"
    refs.mkdir()
    (refs / "methods.md").write_text("# M01\nEvidence first.", encoding="utf-8")

    root = asyncio.run(reader("demo"))
    nested = asyncio.run(reader("demo", "references/methods.md"))

    assert _text(root) == "# Demo\n\nDo the work."
    assert _text(nested) == "# M01\nEvidence first."


@pytest.mark.parametrize(
    "skill_name,relative_path",
    [
        ("missing", "SKILL.md"),
        ("demo", ""),
        ("demo", "../secret.md"),
        ("demo", "/etc/passwd"),
        ("demo", "references\\methods.md"),
        ("demo", "asset.png"),
    ],
)
def test_rejects_unregistered_or_unsafe_requests(
    tmp_path, skill_name, relative_path
):
    _skill, reader = _reader(tmp_path)

    response = asyncio.run(reader(skill_name, relative_path))

    assert _text(response).startswith("Error:")
    assert str(tmp_path) not in _text(response)


def test_rejects_symlink_even_when_target_is_inside_skill(tmp_path):
    skill, reader = _reader(tmp_path)
    target = skill / "target.md"
    target.write_text("private", encoding="utf-8")
    link = skill / "link.md"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable")

    response = asyncio.run(reader("demo", "link.md"))

    assert _text(response) == "Error: unsafe skill file path."


def test_rejects_invalid_utf8_and_oversized_files(tmp_path):
    skill, reader = _reader(tmp_path)
    (skill / "invalid.md").write_bytes(b"\xff")
    (skill / "large.md").write_bytes(b"x" * (MAX_AGENT_SKILL_FILE_BYTES + 1))

    invalid = asyncio.run(reader("demo", "invalid.md"))
    large = asyncio.run(reader("demo", "large.md"))

    assert _text(invalid) == "Error: skill file is not valid UTF-8 text."
    assert _text(large) == "Error: skill file exceeds the read limit."


class _Toolkit:
    def __init__(self, skills):
        self.skills = skills
        self.registered = []

    def register_tool_function(self, function, **_kwargs):
        self.registered.append(function)


def _agent(enabled: bool | None):
    agent = QwenPawAgent.__new__(QwenPawAgent)
    if enabled is None:
        tools = None
    else:
        tools = SimpleNamespace(
            builtin_tools={
                "read_agent_skill": SimpleNamespace(enabled=enabled),
            }
        )
    agent._agent_config = SimpleNamespace(tools=tools)
    agent._namesake_strategy = "skip"
    return agent


@pytest.mark.parametrize("enabled", [None, False])
def test_reader_is_absent_without_explicit_agent_opt_in(enabled):
    toolkit = _Toolkit({"demo": {"name": "demo", "dir": "/unused"}})

    _agent(enabled)._register_skill_reader(toolkit)

    assert toolkit.registered == []


def test_reader_is_registered_after_explicit_agent_opt_in():
    toolkit = _Toolkit({"demo": {"name": "demo", "dir": "/unused"}})

    _agent(True)._register_skill_reader(toolkit)

    assert [tool.__name__ for tool in toolkit.registered] == [
        "read_agent_skill"
    ]


def test_reader_exposes_a_valid_agentscope_tool_schema(tmp_path):
    _skill, reader = _reader(tmp_path)
    toolkit = Toolkit()

    toolkit.register_tool_function(reader)

    schemas = toolkit.get_json_schemas()
    schema = next(
        item for item in schemas
        if item["function"]["name"] == "read_agent_skill"
    )
    properties = schema["function"]["parameters"]["properties"]
    assert set(properties) == {"skill_name", "relative_path"}
