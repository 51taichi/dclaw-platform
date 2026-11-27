import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.app.routers import skills as skills_router
from qwenpaw.agents.skill_system import pool_service
from qwenpaw.agents.skill_system import registry
from qwenpaw.agents.skill_system import store
from qwenpaw.agents.skill_system.models import BuiltinSkillVariant
from qwenpaw.agents.skill_system.pool_service import SkillPoolService


def _write_builtin_skill(
    root: Path,
    name: str,
    version: str = "1.0",
    body: str = "# Test Skill\n",
) -> Path:
    skill_dir = root / f"{name}-zh"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: Test skill
metadata:
  builtin_skill_version: "{version}"
---
{body}
""",
        encoding="utf-8",
    )
    return skill_dir


def _write_pool_skill(
    pool_dir: Path,
    name: str,
    *,
    visibility: str,
    owner_user_id: str = "",
    content: str = """---
name: private_skill
description: Private test skill
---
# Private Skill

old content
""",
) -> Path:
    skill_dir = pool_dir / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    (pool_dir / "skill.json").write_text(
        json.dumps(
            {
                "skills": {
                    name: {
                        "source": "customized",
                        "visibility": visibility,
                        "config": {"temperature": 0.3},
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if owner_user_id:
        manifest = json.loads((pool_dir / "skill.json").read_text())
        manifest["skills"][name]["owner_user_id"] = owner_user_id
        (pool_dir / "skill.json").write_text(
            json.dumps(manifest, ensure_ascii=False),
            encoding="utf-8",
        )
    return skill_dir


def _patch_pool_paths(monkeypatch, pool_dir: Path) -> None:
    monkeypatch.setattr(pool_service, "ensure_skill_pool_initialized", lambda: None)
    monkeypatch.setattr(pool_service, "get_skill_pool_dir", lambda: pool_dir)
    monkeypatch.setattr(
        pool_service,
        "get_pool_skill_manifest_path",
        lambda: pool_dir / "skill.json",
    )
    monkeypatch.setattr(store, "get_skill_pool_dir", lambda: pool_dir)
    monkeypatch.setattr(
        store,
        "get_pool_skill_manifest_path",
        lambda: pool_dir / "skill.json",
    )


def _request(user_id: str = "admin-user", role: str = "admin"):
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id, role=role))


def _patch_builtin_registry(
    monkeypatch,
    *,
    pool_dir: Path,
    source_dir: Path,
    skill_name: str = "editable-ppt-visual-builder",
    version: str = "2.1",
) -> None:
    monkeypatch.setattr(registry, "get_skill_pool_dir", lambda: pool_dir)
    monkeypatch.setattr(store, "get_skill_pool_dir", lambda: pool_dir)
    monkeypatch.setattr(
        registry,
        "get_pool_skill_manifest_path",
        lambda: pool_dir / "skill.json",
    )
    monkeypatch.setattr(
        store,
        "get_pool_skill_manifest_path",
        lambda: pool_dir / "skill.json",
    )
    monkeypatch.setattr(
        registry,
        "get_builtin_skill_language_preference",
        lambda: "zh",
    )
    monkeypatch.setattr(
        registry,
        "_get_packaged_builtin_registry",
        lambda: {
            skill_name: {
                "zh": BuiltinSkillVariant(
                    name=skill_name,
                    language="zh",
                    source_name=f"{skill_name}-zh",
                    skill_dir=source_dir,
                    skill_md_path=source_dir / "SKILL.md",
                    description="Test skill",
                    version_text=version,
                ),
            },
        },
    )


def test_builtin_candidate_detects_same_version_content_drift(monkeypatch, tmp_path):
    skill_name = "editable-ppt-visual-builder"
    pool_dir = tmp_path / "pool"
    source_dir = _write_builtin_skill(
        tmp_path / "builtins",
        skill_name,
        version="2.1",
        body="# New compose workflow\n",
    )
    pool_skill = _write_builtin_skill(
        pool_dir.parent,
        skill_name,
        version="2.1",
        body="# Old fixed-layout workflow\n",
    )
    pool_dir.mkdir(parents=True)
    pool_skill.rename(pool_dir / skill_name)
    (pool_dir / "skill.json").write_text(
        json.dumps(
            {
                "skills": {
                    skill_name: {
                        "source": "builtin",
                        "version_text": "2.1",
                        "builtin_language": "zh",
                        "builtin_source_name": f"{skill_name}-zh",
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    _patch_builtin_registry(
        monkeypatch,
        pool_dir=pool_dir,
        source_dir=source_dir,
    )

    candidate = registry.list_builtin_import_candidates()[0]
    sync_status = registry.get_pool_builtin_sync_status()

    assert candidate["status"] == "outdated"
    assert sync_status[skill_name]["sync_status"] == "outdated"


def test_managed_ppt_sync_updates_same_version_content(monkeypatch, tmp_path):
    skill_name = "editable-ppt-visual-builder"
    pool_dir = tmp_path / "pool"
    source_dir = _write_builtin_skill(
        tmp_path / "builtins",
        skill_name,
        version="2.1",
        body="# Custom compose workflow\n",
    )
    pool_skill = _write_builtin_skill(
        pool_dir.parent,
        skill_name,
        version="2.1",
        body="# Stale workflow\n",
    )
    pool_dir.mkdir(parents=True)
    pool_skill.rename(pool_dir / skill_name)
    (pool_dir / "skill.json").write_text(
        json.dumps(
            {
                "skills": {
                    skill_name: {
                        "source": "builtin",
                        "version_text": "2.1",
                        "builtin_language": "zh",
                        "builtin_source_name": f"{skill_name}-zh",
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    _patch_builtin_registry(
        monkeypatch,
        pool_dir=pool_dir,
        source_dir=source_dir,
    )

    registry._sync_managed_editable_ppt_builtin()

    synced = (pool_dir / skill_name / "SKILL.md").read_text(encoding="utf-8")
    assert "Custom compose workflow" in synced
    assert "Stale workflow" not in synced


def test_builtin_import_sets_public_visibility_for_new_pool_entries(
    monkeypatch,
    tmp_path,
):
    pool_dir = tmp_path / "pool"
    source_dir = _write_builtin_skill(tmp_path / "builtins", "demo_skill")

    monkeypatch.setattr(registry, "get_skill_pool_dir", lambda: pool_dir)
    monkeypatch.setattr(
        registry,
        "get_pool_skill_manifest_path",
        lambda: pool_dir / "skill.json",
    )
    monkeypatch.setattr(
        registry,
        "get_builtin_skill_language_preference",
        lambda: "zh",
    )
    monkeypatch.setattr(
        registry,
        "_get_packaged_builtin_registry",
        lambda: {
            "demo_skill": {
                "zh": BuiltinSkillVariant(
                    name="demo_skill",
                    language="zh",
                    source_name="demo_skill-zh",
                    skill_dir=source_dir,
                    skill_md_path=source_dir / "SKILL.md",
                    description="Test skill",
                    version_text="1.0",
                )
            }
        },
    )

    registry.import_builtin_skills(
        [{"skill_name": "demo_skill", "language": "zh"}],
    )

    manifest = json.loads((pool_dir / "skill.json").read_text())
    assert manifest["skills"]["demo_skill"]["visibility"] == "public"


def test_builtin_import_records_frontmatter_config_and_tags(
    monkeypatch,
    tmp_path,
):
    pool_dir = tmp_path / "pool"
    source_dir = tmp_path / "builtins" / "editable-ppt-visual-builder-zh"
    source_dir.mkdir(parents=True)
    (source_dir / "SKILL.md").write_text(
        """---
name: editable-ppt-visual-builder
description: 设计公司级可编辑 PPT 生成技能
metadata:
  builtin_skill_version: "2.0"
  qwenpaw:
    emoji: "📊"
config:
  display_name: "可编辑 PPT 视觉设计师"
  is_default: true
  market_category: "office"
  icon: "presentation"
tags:
  - PPT
  - GPT Image2
---
# 可编辑 PPT 视觉设计师
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(registry, "get_skill_pool_dir", lambda: pool_dir)
    monkeypatch.setattr(
        registry,
        "get_pool_skill_manifest_path",
        lambda: pool_dir / "skill.json",
    )
    monkeypatch.setattr(
        registry,
        "get_builtin_skill_language_preference",
        lambda: "zh",
    )
    monkeypatch.setattr(
        registry,
        "_get_packaged_builtin_registry",
        lambda: {
            "editable-ppt-visual-builder": {
                "zh": BuiltinSkillVariant(
                    name="editable-ppt-visual-builder",
                    language="zh",
                    source_name="editable-ppt-visual-builder-zh",
                    skill_dir=source_dir,
                    skill_md_path=source_dir / "SKILL.md",
                    description="设计公司级可编辑 PPT 生成技能",
                    version_text="2.0",
                )
            }
        },
    )

    registry.import_builtin_skills(
        [
            {
                "skill_name": "editable-ppt-visual-builder",
                "language": "zh",
            }
        ],
    )

    manifest = json.loads((pool_dir / "skill.json").read_text())
    entry = manifest["skills"]["editable-ppt-visual-builder"]
    assert entry["config"] == {
        "display_name": "可编辑 PPT 视觉设计师",
        "is_default": True,
        "market_category": "office",
        "icon": "presentation",
    }
    assert entry["tags"] == ["PPT", "GPT Image2"]


def test_builtin_import_preserves_existing_visibility(monkeypatch, tmp_path):
    pool_dir = tmp_path / "pool"
    source_dir = _write_builtin_skill(tmp_path / "builtins", "demo_skill")
    pool_dir.mkdir()
    (pool_dir / "skill.json").write_text(
        """{
  "skills": {
    "demo_skill": {
      "source": "builtin",
      "visibility": "private",
      "version_text": "0.9"
    }
  }
}
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(registry, "get_skill_pool_dir", lambda: pool_dir)
    monkeypatch.setattr(
        registry,
        "get_pool_skill_manifest_path",
        lambda: pool_dir / "skill.json",
    )
    monkeypatch.setattr(
        registry,
        "get_builtin_skill_language_preference",
        lambda: "zh",
    )
    monkeypatch.setattr(
        registry,
        "_get_packaged_builtin_registry",
        lambda: {
            "demo_skill": {
                "zh": BuiltinSkillVariant(
                    name="demo_skill",
                    language="zh",
                    source_name="demo_skill-zh",
                    skill_dir=source_dir,
                    skill_md_path=source_dir / "SKILL.md",
                    description="Test skill",
                    version_text="1.0",
                )
            }
        },
    )

    registry.import_builtin_skills(
        [{"skill_name": "demo_skill", "language": "zh"}],
        overwrite_conflicts=True,
    )

    manifest = json.loads((pool_dir / "skill.json").read_text())
    assert manifest["skills"]["demo_skill"]["visibility"] == "private"


def test_builtin_import_updates_same_version_when_content_changes(
    monkeypatch,
    tmp_path,
):
    pool_dir = tmp_path / "pool"
    source_dir = _write_builtin_skill(
        tmp_path / "builtins",
        "demo_skill",
        version="1.0",
        body="# New Skill\n\nfresh content\n",
    )
    pool_skill_dir = pool_dir / "demo_skill"
    pool_skill_dir.mkdir(parents=True)
    (pool_skill_dir / "SKILL.md").write_text(
        """---
name: demo_skill
description: Test skill
metadata:
  builtin_skill_version: "1.0"
---
# Old Skill

stale content
""",
        encoding="utf-8",
    )
    (pool_dir / "skill.json").write_text(
        """{
  "skills": {
    "demo_skill": {
      "source": "builtin",
      "visibility": "public",
      "version_text": "1.0",
      "builtin_language": "zh",
      "builtin_source_name": "demo_skill-zh"
    }
  }
}
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(registry, "get_skill_pool_dir", lambda: pool_dir)
    monkeypatch.setattr(
        registry,
        "get_pool_skill_manifest_path",
        lambda: pool_dir / "skill.json",
    )
    monkeypatch.setattr(
        registry,
        "get_builtin_skill_language_preference",
        lambda: "zh",
    )
    monkeypatch.setattr(
        registry,
        "_get_packaged_builtin_registry",
        lambda: {
            "demo_skill": {
                "zh": BuiltinSkillVariant(
                    name="demo_skill",
                    language="zh",
                    source_name="demo_skill-zh",
                    skill_dir=source_dir,
                    skill_md_path=source_dir / "SKILL.md",
                    description="Test skill",
                    version_text="1.0",
                )
            }
        },
    )

    result = registry.import_builtin_skills(
        [{"skill_name": "demo_skill", "language": "zh"}],
    )

    assert result["updated"] == ["demo_skill"]
    assert "fresh content" in (pool_skill_dir / "SKILL.md").read_text(
        encoding="utf-8",
    )


def test_pool_edit_preserves_private_visibility(monkeypatch, tmp_path):
    pool_dir = tmp_path / "pool"
    _write_pool_skill(
        pool_dir,
        "private_skill",
        visibility="private",
    )
    _patch_pool_paths(monkeypatch, pool_dir)

    result = SkillPoolService().save_pool_skill(
        skill_name="private_skill",
        content="""---
name: private_skill
description: Private test skill
---
# Private Skill

new content
""",
    )

    manifest = json.loads((pool_dir / "skill.json").read_text())
    assert result["success"] is True
    assert manifest["skills"]["private_skill"]["visibility"] == "private"
    assert manifest["skills"]["private_skill"]["source"] == "customized"


def test_pool_create_records_private_owner(monkeypatch, tmp_path):
    pool_dir = tmp_path / "pool"
    pool_dir.mkdir()
    _patch_pool_paths(monkeypatch, pool_dir)

    result = SkillPoolService().create_skill(
        name="owned_private_skill",
        content="""---
name: owned_private_skill
description: Owned private skill
---
# Owned Private Skill
""",
        visibility="private",
        owner_user_id="user-1",
    )

    manifest = json.loads((pool_dir / "skill.json").read_text())
    assert result == "owned_private_skill"
    assert manifest["skills"]["owned_private_skill"]["visibility"] == "private"
    assert manifest["skills"]["owned_private_skill"]["owner_user_id"] == "user-1"


@pytest.mark.asyncio
async def test_setting_pool_skill_as_default_installs_it_for_all_workspaces(
    monkeypatch,
    tmp_path,
):
    pool_dir = tmp_path / "pool"
    workspace_a = tmp_path / "workspaces" / "a"
    workspace_b = tmp_path / "workspaces" / "b"
    _write_pool_skill(
        pool_dir,
        "default_skill",
        visibility="public",
        content="""---
name: default_skill
description: Default test skill
---
# Default Skill
""",
    )
    _patch_pool_paths(monkeypatch, pool_dir)
    monkeypatch.setattr(
        skills_router,
        "get_pool_skill_manifest_path",
        lambda: pool_dir / "skill.json",
    )
    monkeypatch.setattr(
        skills_router,
        "read_skill_pool_manifest",
        lambda: json.loads((pool_dir / "skill.json").read_text()),
    )
    monkeypatch.setattr(
        skills_router,
        "list_workspaces",
        lambda: [
            {
                "agent_id": "a",
                "agent_name": "A",
                "workspace_dir": str(workspace_a),
            },
            {
                "agent_id": "b",
                "agent_name": "B",
                "workspace_dir": str(workspace_b),
            },
        ],
    )
    for workspace_dir in (workspace_a, workspace_b):
        workspace_dir.mkdir(parents=True)
        (workspace_dir / "skill.json").write_text(
            json.dumps({"skills": {}}, ensure_ascii=False),
            encoding="utf-8",
        )

    result = await skills_router.update_pool_skill_config(
        _request(),
        "default_skill",
        skills_router.SkillConfigRequest(config={"is_default": True}),
    )

    assert result == {"updated": True}
    for workspace_dir in (workspace_a, workspace_b):
        manifest = json.loads((workspace_dir / "skill.json").read_text())
        entry = manifest["skills"]["default_skill"]
        assert entry["enabled"] is True
        assert (workspace_dir / "skills" / "default_skill" / "SKILL.md").exists()


@pytest.mark.asyncio
async def test_pool_governance_update_hides_default_skill_without_unsetting_default(
    monkeypatch,
    tmp_path,
):
    pool_dir = tmp_path / "pool"
    _write_pool_skill(
        pool_dir,
        "default_skill",
        visibility="public",
        content="""---
name: default_skill
description: Default test skill
---
# Default Skill
""",
    )
    manifest = json.loads((pool_dir / "skill.json").read_text())
    manifest["skills"]["default_skill"]["config"]["is_default"] = True
    (pool_dir / "skill.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    _patch_pool_paths(monkeypatch, pool_dir)
    monkeypatch.setattr(
        skills_router,
        "get_pool_skill_manifest_path",
        lambda: pool_dir / "skill.json",
    )
    monkeypatch.setattr(
        skills_router,
        "read_skill_pool_manifest",
        lambda: json.loads((pool_dir / "skill.json").read_text()),
    )

    result = await skills_router.update_pool_skill_governance(
        _request(),
        "default_skill",
        skills_router.PoolSkillGovernanceRequest(client_visible=False),
    )

    assert result == {"updated": True}
    updated = json.loads((pool_dir / "skill.json").read_text())
    entry = updated["skills"]["default_skill"]
    assert entry["client_visible"] is False
    assert entry["config"]["is_default"] is True
    assert entry["visibility"] == "public"


@pytest.mark.asyncio
async def test_pool_governance_rejects_public_to_private_transition(
    monkeypatch,
    tmp_path,
):
    pool_dir = tmp_path / "pool"
    _write_pool_skill(
        pool_dir,
        "public_skill",
        visibility="public",
        content="""---
name: public_skill
description: Public test skill
---
# Public Skill
""",
    )
    _patch_pool_paths(monkeypatch, pool_dir)
    monkeypatch.setattr(
        skills_router,
        "get_pool_skill_manifest_path",
        lambda: pool_dir / "skill.json",
    )
    monkeypatch.setattr(
        skills_router,
        "read_skill_pool_manifest",
        lambda: json.loads((pool_dir / "skill.json").read_text()),
    )

    with pytest.raises(skills_router.HTTPException) as exc_info:
        await skills_router.update_pool_skill_governance(
            _request(),
            "public_skill",
            skills_router.PoolSkillGovernanceRequest(visibility="private"),
        )

    assert exc_info.value.status_code == 400
    updated = json.loads((pool_dir / "skill.json").read_text())
    assert updated["skills"]["public_skill"]["visibility"] == "public"


@pytest.mark.asyncio
async def test_pool_save_rejects_public_to_private_transition_before_content_write(
    monkeypatch,
    tmp_path,
):
    pool_dir = tmp_path / "pool"
    original_content = """---
name: public_skill
description: Public test skill
---
# Original Public Skill
"""
    _write_pool_skill(
        pool_dir,
        "public_skill",
        visibility="public",
        content=original_content,
    )
    _patch_pool_paths(monkeypatch, pool_dir)
    monkeypatch.setattr(
        skills_router,
        "get_pool_skill_manifest_path",
        lambda: pool_dir / "skill.json",
    )
    monkeypatch.setattr(
        skills_router,
        "read_skill_pool_manifest",
        lambda: json.loads((pool_dir / "skill.json").read_text()),
    )

    with pytest.raises(skills_router.HTTPException) as exc_info:
        await skills_router.save_pool_skill(
            _request(),
            skills_router.SavePoolSkillRequest(
                name="public_skill",
                source_name="public_skill",
                content="""---
name: public_skill
description: Public test skill
---
# Mutated Public Skill
""",
                config={},
                visibility="private",
            ),
        )

    assert exc_info.value.status_code == 400
    assert (
        pool_dir / "public_skill" / "SKILL.md"
    ).read_text(encoding="utf-8") == original_content
    updated = json.loads((pool_dir / "skill.json").read_text())
    assert updated["skills"]["public_skill"]["visibility"] == "public"


def test_pool_edit_preserves_private_owner(monkeypatch, tmp_path):
    pool_dir = tmp_path / "pool"
    _write_pool_skill(
        pool_dir,
        "private_skill",
        visibility="private",
        owner_user_id="user-1",
    )
    _patch_pool_paths(monkeypatch, pool_dir)

    result = SkillPoolService().save_pool_skill(
        skill_name="private_skill",
        content="""---
name: private_skill
description: Private test skill
---
# Private Skill

new content
""",
    )

    manifest = json.loads((pool_dir / "skill.json").read_text())
    assert result["success"] is True
    assert manifest["skills"]["private_skill"]["visibility"] == "private"
    assert manifest["skills"]["private_skill"]["owner_user_id"] == "user-1"


def test_pool_rename_preserves_private_visibility(monkeypatch, tmp_path):
    pool_dir = tmp_path / "pool"
    _write_pool_skill(
        pool_dir,
        "private_skill",
        visibility="private",
    )
    _patch_pool_paths(monkeypatch, pool_dir)

    result = SkillPoolService().save_pool_skill(
        skill_name="private_skill",
        target_name="renamed_private_skill",
        content="""---
name: renamed_private_skill
description: Private test skill
---
# Renamed Private Skill

new content
""",
    )

    manifest = json.loads((pool_dir / "skill.json").read_text())
    assert result["success"] is True
    assert "private_skill" not in manifest["skills"]
    assert (
        manifest["skills"]["renamed_private_skill"]["visibility"]
        == "private"
    )


def test_pool_rename_preserves_private_owner(monkeypatch, tmp_path):
    pool_dir = tmp_path / "pool"
    _write_pool_skill(
        pool_dir,
        "private_skill",
        visibility="private",
        owner_user_id="user-1",
    )
    _patch_pool_paths(monkeypatch, pool_dir)

    result = SkillPoolService().save_pool_skill(
        skill_name="private_skill",
        target_name="renamed_private_skill",
        content="""---
name: renamed_private_skill
description: Private test skill
---
# Renamed Private Skill

new content
""",
    )

    manifest = json.loads((pool_dir / "skill.json").read_text())
    assert result["success"] is True
    assert manifest["skills"]["renamed_private_skill"]["visibility"] == "private"
    assert (
        manifest["skills"]["renamed_private_skill"]["owner_user_id"]
        == "user-1"
    )


def test_pool_download_copies_private_owner_to_workspace(monkeypatch, tmp_path):
    pool_dir = tmp_path / "pool"
    workspace_dir = tmp_path / "workspace"
    _write_pool_skill(
        pool_dir,
        "private_skill",
        visibility="private",
        owner_user_id="user-1",
    )
    _patch_pool_paths(monkeypatch, pool_dir)
    workspace_dir.mkdir()
    (workspace_dir / "skill.json").write_text(
        json.dumps({"skills": {}}, ensure_ascii=False),
        encoding="utf-8",
    )

    result = SkillPoolService().download_to_workspace(
        "private_skill",
        workspace_dir,
    )

    manifest = json.loads((workspace_dir / "skill.json").read_text())
    assert result["success"] is True
    assert manifest["skills"]["private_skill"]["visibility"] == "private"
    assert manifest["skills"]["private_skill"]["owner_user_id"] == "user-1"


def test_pool_reconcile_preserves_private_owner(monkeypatch, tmp_path):
    pool_dir = tmp_path / "pool"
    _write_pool_skill(
        pool_dir,
        "private_skill",
        visibility="private",
        owner_user_id="user-1",
    )
    monkeypatch.setattr(registry, "get_skill_pool_dir", lambda: pool_dir)
    monkeypatch.setattr(
        registry,
        "get_pool_skill_manifest_path",
        lambda: pool_dir / "skill.json",
    )
    monkeypatch.setattr(registry, "_get_packaged_builtin_registry", lambda: {})

    registry.reconcile_pool_manifest()

    manifest = json.loads((pool_dir / "skill.json").read_text())
    assert manifest["skills"]["private_skill"]["visibility"] == "private"
    assert manifest["skills"]["private_skill"]["owner_user_id"] == "user-1"
