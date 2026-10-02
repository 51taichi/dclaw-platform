from __future__ import annotations

import json
from pathlib import Path

import frontmatter

from qwenpaw.config.config import AgentProfileConfig

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE = (
    REPO_ROOT
    / "agent_sources"
    / "douyin_engagement_agent"
    / "workspace"
)


def test_douyin_engagement_workspace_loads_as_an_ordinary_agent() -> None:
    payload = json.loads((WORKSPACE / "agent.json").read_text(encoding="utf-8"))

    config = AgentProfileConfig.model_validate(payload)

    assert config.id == "douyin_engagement_agent"
    assert config.name == "抖音互动 Agent"
    assert config.orchestration.enabled is False
    assert config.system_prompt_files == ["AGENTS.md", "SOUL.md", "PROFILE.md"]
    assert config.running.history_max_length == 10_000


def test_douyin_engagement_workspace_exposes_no_runtime_tools() -> None:
    payload = json.loads((WORKSPACE / "agent.json").read_text(encoding="utf-8"))

    config = AgentProfileConfig.model_validate(payload)

    assert config.tools is not None
    assert config.tools.builtin_tools
    assert all(
        tool.enabled is False
        for tool in config.tools.builtin_tools.values()
    )


def test_douyin_operation_contract_skill_is_enabled_and_discoverable() -> None:
    manifest = json.loads((WORKSPACE / "skill.json").read_text(encoding="utf-8"))
    skill_path = WORKSPACE / "skills" / "douyin_operation_contract" / "SKILL.md"
    skill = frontmatter.loads(skill_path.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "workspace-skill-manifest.v1"
    assert manifest["skills"]["douyin_operation_contract"]["enabled"] is True
    assert manifest["skills"]["douyin_operation_contract"]["source"] == "local"
    assert skill["name"] == "douyin_operation_contract"
    assert skill["description"]
