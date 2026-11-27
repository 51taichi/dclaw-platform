# -*- coding: utf-8 -*-
"""Tests for QwenPawAgent skill registration workspace selection."""
from __future__ import annotations

from pathlib import Path

from qwenpaw.agents.react_agent import QwenPawAgent


class _FakeToolkit:
    def __init__(self) -> None:
        self.registered: list[str] = []

    def register_agent_skill(self, skill_dir: str) -> None:
        self.registered.append(skill_dir)


def test_skill_registration_uses_root_workspace_when_session_is_isolated(
    monkeypatch,
    tmp_path,
) -> None:
    root_workspace = tmp_path / "workspace"
    isolated_workspace = root_workspace / "sessions_data" / "session-1"
    skill_dir = root_workspace / "skills" / "demo_skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo_skill\ndescription: demo\n---\n# Demo\n",
        encoding="utf-8",
    )
    isolated_workspace.mkdir(parents=True)

    initialized: list[Path] = []
    resolved: list[Path] = []

    def fake_ensure(workspace_dir: Path) -> None:
        initialized.append(Path(workspace_dir))

    def fake_resolve(
        workspace_dir: Path,
        _channel_name: str,
        **_kwargs,
    ) -> list[str]:
        resolved.append(Path(workspace_dir))
        return ["demo_skill"]

    monkeypatch.setattr(
        "qwenpaw.agents.react_agent.ensure_skills_initialized",
        fake_ensure,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.react_agent.resolve_effective_skills",
        fake_resolve,
    )

    agent = QwenPawAgent.__new__(QwenPawAgent)
    agent._workspace_dir = isolated_workspace
    agent._skills_workspace_dir = root_workspace
    agent._request_context = {"channel": "default"}

    toolkit = _FakeToolkit()
    agent._register_skills(toolkit)

    assert initialized == [root_workspace]
    assert resolved == [root_workspace]
    assert toolkit.registered == [str(skill_dir)]
