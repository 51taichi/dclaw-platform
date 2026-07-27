# -*- coding: utf-8 -*-
"""Regression tests for packaged product agents and skills."""

from __future__ import annotations

import json
from pathlib import Path


def _patch_working_dir(monkeypatch, tmp_path: Path) -> None:
    """Point modules that cache WORKING_DIR at the isolated test dir."""
    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    monkeypatch.setattr("qwenpaw.config.config.WORKING_DIR", tmp_path)
    monkeypatch.setattr("qwenpaw.config.utils.WORKING_DIR", tmp_path)
    monkeypatch.setattr("qwenpaw.app.migration.WORKING_DIR", tmp_path)


def test_packaged_product_assets_seed_agents_and_skills(
    monkeypatch,
    tmp_path,
):
    """A fresh deployment should include product agents and custom skills."""
    from qwenpaw.agents.skill_system.registry import reconcile_pool_manifest
    from qwenpaw.agents.skill_system.store import read_skill_pool_manifest
    from qwenpaw.app.migration import ensure_product_builtin_assets
    from qwenpaw.config.utils import load_config

    _patch_working_dir(monkeypatch, tmp_path)

    ensure_product_builtin_assets()
    reconcile_pool_manifest()

    config = load_config()
    expected_agent_ids = {
        "default",
        "QwenPaw_QA_Agent_0.2",
        "fullstack_dev",
        "content_creation",
        "product_design",
        "data_analysis",
        "finance_research",
        "opc_company",
        "consultant",
        "legal",
        "marketing_agent",
        "qa",
    }
    assert expected_agent_ids.issubset(set(config.agents.profiles))
    assert config.agents.agent_order[: len(expected_agent_ids)] == [
        "default",
        "QwenPaw_QA_Agent_0.2",
        "qa",
        "fullstack_dev",
        "marketing_agent",
        "content_creation",
        "product_design",
        "data_analysis",
        "finance_research",
        "opc_company",
        "consultant",
        "legal",
    ]

    content_workspace = tmp_path / "workspaces" / "content_creation"
    assert (content_workspace / "agent.json").exists()
    content_agent = json.loads(
        (content_workspace / "agent.json").read_text(encoding="utf-8"),
    )
    assert content_agent["name"] == "内容创作专家"
    assert content_agent["workspace_dir"] == str(content_workspace)
    assert (
        content_agent["channels"]["voice"]["welcome_greeting"]
        == "Hi! This is DClaw. How can I help you?"
    )
    assert (
        content_agent["channels"]["sip"]["welcome_greeting"]
        == "你好，我是DClaw"
    )
    assert not (content_workspace / "BOOTSTRAP.md").exists()
    assert not (content_workspace / "chats.json").exists()
    assert not (content_workspace / "sessions_data").exists()

    default_profile = (
        tmp_path / "workspaces" / "default" / "PROFILE.md"
    ).read_text(encoding="utf-8")
    assert "DClaw" in default_profile
    assert "挑个你喜欢的" not in default_profile
    assert "你叫什么" not in default_profile

    content_profile = (content_workspace / "PROFILE.md").read_text(
        encoding="utf-8",
    )
    assert "内容创作专家" in content_profile
    assert "挑个你喜欢的" not in content_profile

    workspace_manifest = json.loads(
        (content_workspace / "skill.json").read_text(encoding="utf-8"),
    )
    enabled_skills = {
        name
        for name, entry in workspace_manifest.get("skills", {}).items()
        if entry.get("enabled")
    }
    assert "短剧创作工坊-20260528055448" in enabled_skills
    assert "短剧创作工坊" not in enabled_skills
    assert "skill_creator" in enabled_skills

    pool_manifest = read_skill_pool_manifest()
    pool_skills = pool_manifest.get("skills", {})
    for skill_name in [
        "ai_paint_assistant",
        "api_debugger",
        "database_assistant",
        "exam_question_generator",
        "短剧创作工坊-20260528055448",
    ]:
        assert skill_name in pool_skills
        assert pool_skills[skill_name]["source"] == "builtin"


def test_product_assets_remove_stale_bootstrap_from_existing_workspaces(
    monkeypatch,
    tmp_path,
):
    """Startup should clean old bootstrap prompts from builtin workspaces."""
    from qwenpaw.app.migration import ensure_product_builtin_assets

    _patch_working_dir(monkeypatch, tmp_path)

    ensure_product_builtin_assets()

    default_workspace = tmp_path / "workspaces" / "default"
    stale_bootstraps = [
        default_workspace / "BOOTSTRAP.md",
        default_workspace / "users" / "default" / "BOOTSTRAP.md",
        default_workspace / "sessions_data" / "old-session" / "BOOTSTRAP.md",
    ]
    for path in stale_bootstraps:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("嘿，我刚上线。我是谁？你是谁？", encoding="utf-8")

    stale_profiles = [
        default_workspace / "users" / "default" / "PROFILE.md",
        default_workspace / "sessions_data" / "old-session" / "PROFILE.md",
    ]
    for path in stale_profiles:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "- **名字：**\n  *（挑个你喜欢的）*\n",
            encoding="utf-8",
        )

    ensure_product_builtin_assets()

    for path in stale_bootstraps:
        assert not path.exists()
    for path in stale_profiles:
        content = path.read_text(encoding="utf-8")
        assert "DClaw" in content
        assert "挑个你喜欢的" not in content
