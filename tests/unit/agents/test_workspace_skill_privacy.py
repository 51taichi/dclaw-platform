import json
from pathlib import Path

from qwenpaw.agents.skill_system import registry
from qwenpaw.agents.skill_system.workspace_service import SkillService


def _private_skill_content(name: str = "private_skill") -> str:
    return f"""---
name: {name}
description: Private workspace skill
---
# {name}
"""


def _write_workspace_private_skill(workspace_dir: Path) -> None:
    skill_dir = workspace_dir / "skills" / "private_skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        _private_skill_content(),
        encoding="utf-8",
    )
    (workspace_dir / "skill.json").write_text(
        json.dumps(
            {
                "skills": {
                    "private_skill": {
                        "enabled": True,
                        "channels": ["all"],
                        "source": "customized",
                        "visibility": "private",
                        "owner_user_id": "user-1",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_workspace_create_records_private_owner(tmp_path):
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    result = SkillService(workspace_dir).create_skill(
        name="private_skill",
        content=_private_skill_content(),
        visibility="private",
        owner_user_id="user-1",
    )

    manifest = json.loads((workspace_dir / "skill.json").read_text())
    assert result == "private_skill"
    assert manifest["skills"]["private_skill"]["visibility"] == "private"
    assert manifest["skills"]["private_skill"]["owner_user_id"] == "user-1"


def test_workspace_edit_preserves_private_owner(tmp_path):
    workspace_dir = tmp_path / "workspace"
    _write_workspace_private_skill(workspace_dir)

    result = SkillService(workspace_dir).save_skill(
        skill_name="private_skill",
        content=_private_skill_content() + "\nupdated\n",
    )

    manifest = json.loads((workspace_dir / "skill.json").read_text())
    assert result["success"] is True
    assert manifest["skills"]["private_skill"]["visibility"] == "private"
    assert manifest["skills"]["private_skill"]["owner_user_id"] == "user-1"


def test_workspace_rename_preserves_private_owner(tmp_path):
    workspace_dir = tmp_path / "workspace"
    _write_workspace_private_skill(workspace_dir)

    result = SkillService(workspace_dir).save_skill(
        skill_name="private_skill",
        target_name="renamed_private_skill",
        content=_private_skill_content("renamed_private_skill"),
    )

    manifest = json.loads((workspace_dir / "skill.json").read_text())
    assert result["success"] is True
    assert "private_skill" not in manifest["skills"]
    assert (
        manifest["skills"]["renamed_private_skill"]["visibility"]
        == "private"
    )
    assert (
        manifest["skills"]["renamed_private_skill"]["owner_user_id"]
        == "user-1"
    )


def test_workspace_reconcile_preserves_private_owner(tmp_path):
    workspace_dir = tmp_path / "workspace"
    _write_workspace_private_skill(workspace_dir)

    registry.reconcile_workspace_manifest(workspace_dir)

    manifest = json.loads((workspace_dir / "skill.json").read_text())
    assert manifest["skills"]["private_skill"]["visibility"] == "private"
    assert manifest["skills"]["private_skill"]["owner_user_id"] == "user-1"
