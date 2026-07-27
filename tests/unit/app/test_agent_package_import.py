# -*- coding: utf-8 -*-
"""Tests for importing exported agent packages."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from qwenpaw.app import agent_package_import as importer
from qwenpaw.config.config import Config, AgentProfileRef


def _zip_bytes(files: dict[str, str]) -> bytes:
    """Build a small in-memory zip file."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _legacy_utf8_zip_name(name: str) -> str:
    """Encode a UTF-8 filename as if the zip omitted the UTF-8 flag."""
    return name.encode("utf-8").decode("cp437")


def _agent_json(
    agent_id: str = "xzj_business_manager",
    *,
    name: str = "湘左记招商经理",
) -> str:
    return json.dumps(
        {
            "id": agent_id,
            "name": name,
            "description": "企业微信招商客服 Agent",
            "workspace_dir": "/old/export/path",
            "language": "zh",
            "system_prompt_files": ["AGENTS.md", "PROFILE.md"],
        },
        ensure_ascii=False,
    )


def _skill_md(name: str = "customer_reply_flow") -> str:
    return (
        "---\n"
        f"name: {name}\n"
        "description: 客户回复流程\n"
        "---\n"
        "# 客户回复流程\n"
        "收到客户消息后先识别意图，再根据知识库回复。\n"
    )


def _patch_persistence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    config: Config,
) -> list[object]:
    """Patch config persistence while still writing agent.json for assertions."""
    saved: list[object] = []

    monkeypatch.setattr(importer, "WORKING_DIR", str(tmp_path))
    monkeypatch.setattr(importer, "load_config", lambda: config)
    monkeypatch.setattr(
        importer,
        "save_config",
        lambda updated: saved.append(updated),
    )

    def _save_agent_config(agent_id: str, agent_config) -> None:
        workspace_dir = Path(agent_config.workspace_dir)
        workspace_dir.mkdir(parents=True, exist_ok=True)
        (workspace_dir / "agent.json").write_text(
            json.dumps(
                agent_config.model_dump(exclude_none=True),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        saved.append((agent_id, agent_config))

    monkeypatch.setattr(importer, "save_agent_config", _save_agent_config)
    return saved


def test_preview_accepts_wrapped_workspace_and_nested_skills():
    """Preview should tolerate a single wrapper directory."""
    data = _zip_bytes(
        {
            "bundle/agent.json": _agent_json(),
            "bundle/AGENTS.md": "# 工作规则\n",
            "bundle/PROFILE.md": "# 身份\n招商经理\n",
            "bundle/skills/customer_reply_flow/SKILL.md": _skill_md(),
            "bundle/知识库/产品.md": "湘左记产品资料",
        },
    )

    preview = importer.preview_agent_package(data, existing_ids=set())

    assert preview.id == "xzj_business_manager"
    assert preview.name == "湘左记招商经理"
    assert preview.root_path == "bundle"
    assert preview.skills == ["customer_reply_flow"]
    assert preview.files_count == 5
    assert preview.has_conflict is False


def test_import_normalizes_workspace_config_and_nested_skills(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Import should rewrite agent config and normalize discovered skills."""
    config = Config()
    config.agents.profiles = {
        "default": AgentProfileRef(
            id="default",
            workspace_dir=str(tmp_path / "workspaces" / "default"),
        ),
    }
    config.agents.agent_order = ["default"]
    saved = _patch_persistence(monkeypatch, tmp_path, config)

    data = _zip_bytes(
        {
            "export-root/config/agent.json": _agent_json(),
            "export-root/AGENTS.md": "# 工作规则\n",
            "export-root/custom-skill/customer_reply_flow/SKILL.md": _skill_md(),
            "export-root/知识库/产品.md": "湘左记产品资料",
            "export-root/__MACOSX/._junk": "ignored",
        },
    )

    result = importer.import_agent_package(data)

    workspace_dir = tmp_path / "workspaces" / "xzj_business_manager"
    assert result.imported is True
    assert result.agent_id == "xzj_business_manager"
    assert result.workspace_dir == str(workspace_dir)
    assert result.skills == ["customer_reply_flow"]
    assert config.agents.profiles["xzj_business_manager"].workspace_dir == str(
        workspace_dir,
    )
    assert config.agents.agent_order == ["default", "xzj_business_manager"]
    assert saved

    agent_payload = json.loads(
        (workspace_dir / "agent.json").read_text(encoding="utf-8"),
    )
    assert agent_payload["id"] == "xzj_business_manager"
    assert agent_payload["workspace_dir"] == str(workspace_dir)
    assert (
        workspace_dir / "skills" / "customer_reply_flow" / "SKILL.md"
    ).exists()
    assert "customer_reply_flow" in json.loads(
        (workspace_dir / "skill.json").read_text(encoding="utf-8"),
    )["skills"]
    assert (workspace_dir / "知识库" / "产品.md").read_text(
        encoding="utf-8",
    ) == "湘左记产品资料"
    assert not (workspace_dir / "__MACOSX").exists()


def test_import_recovers_legacy_utf8_zip_filenames(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """WeChat/Windows zips can carry UTF-8 filename bytes without the flag."""
    config = Config()
    config.agents.profiles = {}
    config.agents.agent_order = []
    _patch_persistence(monkeypatch, tmp_path, config)

    data = _zip_bytes(
        {
            "bundle/agent.json": _agent_json(),
            "bundle/skills/customer_reply_flow/SKILL.md": _skill_md(),
            _legacy_utf8_zip_name("bundle/知识库/index.md"): "招商知识索引",
            _legacy_utf8_zip_name("bundle/客户档案/README.md"): "客户档案说明",
            _legacy_utf8_zip_name("bundle/会话记录/README.md"): "会话记录说明",
        },
    )

    result = importer.import_agent_package(data)

    workspace_dir = tmp_path / "workspaces" / "xzj_business_manager"
    assert result.files_count == 5
    assert (workspace_dir / "知识库" / "index.md").read_text(
        encoding="utf-8",
    ) == "招商知识索引"
    assert (workspace_dir / "客户档案" / "README.md").exists()
    assert (workspace_dir / "会话记录" / "README.md").exists()
    assert not list(workspace_dir.glob("*τƒÑ*"))
    assert not list(workspace_dir.glob("*σ«ó*"))


def test_import_uses_archive_root_when_nested_agent_json_has_no_wrapper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """A package without one wrapper dir should still copy sibling folders."""
    config = Config()
    config.agents.profiles = {}
    config.agents.agent_order = []
    _patch_persistence(monkeypatch, tmp_path, config)

    data = _zip_bytes(
        {
            "config/agent.json": _agent_json(),
            "skills/customer_reply_flow/SKILL.md": _skill_md(),
            "知识库/产品.md": "湘左记产品资料",
        },
    )

    preview = importer.preview_agent_package(data, existing_ids=set())
    result = importer.import_agent_package(data)

    workspace_dir = tmp_path / "workspaces" / "xzj_business_manager"
    assert preview.root_path == "."
    assert result.files_count == 3
    assert (
        workspace_dir / "skills" / "customer_reply_flow" / "SKILL.md"
    ).exists()
    assert (workspace_dir / "知识库" / "产品.md").exists()


def test_import_rejects_duplicate_id_with_suggestion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Import should never overwrite an existing agent by default."""
    config = Config()
    config.agents.profiles = {
        "xzj_business_manager": AgentProfileRef(
            id="xzj_business_manager",
            workspace_dir=str(tmp_path / "workspaces" / "old"),
        ),
    }
    _patch_persistence(monkeypatch, tmp_path, config)

    data = _zip_bytes({"agent.json": _agent_json()})

    with pytest.raises(importer.AgentPackageConflict) as exc_info:
        importer.import_agent_package(data)

    assert exc_info.value.detail["reason"] == "agent_id_conflict"
    assert exc_info.value.detail["agent_id"] == "xzj_business_manager"
    assert exc_info.value.detail["suggested_id"] == "xzj_business_manager_2"


def test_import_update_mode_replaces_existing_agent_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Update mode should modify the existing agent instead of minting a new ID."""
    workspace_dir = tmp_path / "workspaces" / "xzj_business_manager"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "old.txt").write_text("stale", encoding="utf-8")
    (workspace_dir / "agent.json").write_text(
        _agent_json(name="旧招商经理"),
        encoding="utf-8",
    )

    config = Config()
    config.agents.profiles = {
        "default": AgentProfileRef(
            id="default",
            workspace_dir=str(tmp_path / "workspaces" / "default"),
        ),
        "xzj_business_manager": AgentProfileRef(
            id="xzj_business_manager",
            workspace_dir=str(workspace_dir),
            enabled=False,
        ),
    }
    config.agents.agent_order = ["default", "xzj_business_manager"]
    _patch_persistence(monkeypatch, tmp_path, config)

    data = _zip_bytes(
        {
            "bundle/agent.json": _agent_json(name="湘左记招商经理新版"),
            "bundle/skills/customer_reply_flow/SKILL.md": _skill_md(),
            "bundle/知识库/index.md": "新版知识库",
        },
    )

    result = importer.import_agent_package(data, mode="update")

    assert result.imported is True
    assert result.agent_id == "xzj_business_manager"
    assert result.name == "湘左记招商经理新版"
    assert result.workspace_dir == str(workspace_dir)
    assert config.agents.agent_order == ["default", "xzj_business_manager"]
    assert config.agents.profiles["xzj_business_manager"].workspace_dir == str(
        workspace_dir,
    )
    assert config.agents.profiles["xzj_business_manager"].enabled is True
    assert not (workspace_dir / "old.txt").exists()
    assert (workspace_dir / "知识库" / "index.md").read_text(
        encoding="utf-8",
    ) == "新版知识库"
    assert (
        workspace_dir / "skills" / "customer_reply_flow" / "SKILL.md"
    ).exists()


def test_import_update_mode_adopts_orphaned_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Update mode should recover a same-ID workspace left outside config."""
    workspace_dir = tmp_path / "workspaces" / "xzj_business_manager"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "old.txt").write_text("stale", encoding="utf-8")

    config = Config()
    config.agents.profiles = {
        "default": AgentProfileRef(
            id="default",
            workspace_dir=str(tmp_path / "workspaces" / "default"),
        ),
    }
    config.agents.agent_order = ["default"]
    _patch_persistence(monkeypatch, tmp_path, config)

    data = _zip_bytes(
        {
            "bundle/agent.json": _agent_json(),
            "bundle/skills/customer_reply_flow/SKILL.md": _skill_md(),
            "bundle/知识库/index.md": "新版知识库",
        },
    )

    preview = importer.preview_agent_package(data, existing_ids=set())

    assert preview.has_conflict is True
    assert preview.suggested_id == "xzj_business_manager_2"

    result = importer.import_agent_package(data, mode="update")

    assert result.imported is True
    assert result.agent_id == "xzj_business_manager"
    assert result.workspace_dir == str(workspace_dir)
    assert config.agents.agent_order == ["default", "xzj_business_manager"]
    assert config.agents.profiles["xzj_business_manager"].workspace_dir == str(
        workspace_dir,
    )
    assert not (workspace_dir / "old.txt").exists()
    assert (workspace_dir / "知识库" / "index.md").read_text(
        encoding="utf-8",
    ) == "新版知识库"


def test_import_cleans_workspace_when_skill_install_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Failed imports should not leave a partial workspace behind."""
    config = Config()
    config.agents.profiles = {
        "default": AgentProfileRef(
            id="default",
            workspace_dir=str(tmp_path / "workspaces" / "default"),
        ),
    }
    config.agents.agent_order = ["default"]
    _patch_persistence(monkeypatch, tmp_path, config)

    def _fail_install(*_args, **_kwargs):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(importer, "_install_discovered_skills", _fail_install)

    data = _zip_bytes(
        {
            "agent.json": _agent_json(),
            "skills/customer_reply_flow/SKILL.md": _skill_md(),
        },
    )

    with pytest.raises(RuntimeError, match="scan failed"):
        importer.import_agent_package(data)

    assert "xzj_business_manager" not in config.agents.profiles
    assert config.agents.agent_order == ["default"]
    assert not (tmp_path / "workspaces" / "xzj_business_manager").exists()
