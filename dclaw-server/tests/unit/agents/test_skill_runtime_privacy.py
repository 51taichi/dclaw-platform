import json
from pathlib import Path

from qwenpaw.agents.skill_system import registry


def _write_skill_dir(workspace_dir: Path, name: str) -> None:
    skill_dir = workspace_dir / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: Runtime privacy test skill
---
# {name}
""",
        encoding="utf-8",
    )


def test_runtime_effective_skills_are_filtered_by_private_owner(tmp_path):
    workspace_dir = tmp_path / "workspace"
    for name in ("public_skill", "own_private", "other_private"):
        _write_skill_dir(workspace_dir, name)
    (workspace_dir / "skill.json").write_text(
        json.dumps(
            {
                "skills": {
                    "public_skill": {
                        "enabled": True,
                        "channels": ["all"],
                        "source": "customized",
                    },
                    "own_private": {
                        "enabled": True,
                        "channels": ["all"],
                        "source": "customized",
                        "visibility": "private",
                        "owner_user_id": "user-1",
                    },
                    "other_private": {
                        "enabled": True,
                        "channels": ["all"],
                        "source": "customized",
                        "visibility": "private",
                        "owner_user_id": "user-2",
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    resolved = registry.resolve_effective_skills(
        workspace_dir,
        "console",
        user_id="user-1",
    )

    assert resolved == ["own_private", "public_skill"]


def test_runtime_effective_skills_inherit_pool_private_owner(
    monkeypatch,
    tmp_path,
):
    workspace_dir = tmp_path / "workspace"
    _write_skill_dir(workspace_dir, "other_private")
    (workspace_dir / "skill.json").write_text(
        json.dumps(
            {
                "skills": {
                    "other_private": {
                        "enabled": True,
                        "channels": ["all"],
                        "source": "customized",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        registry,
        "read_skill_pool_manifest",
        lambda: {
            "skills": {
                "other_private": {
                    "source": "customized",
                    "visibility": "private",
                    "owner_user_id": "user-2",
                }
            }
        },
    )

    resolved = registry.resolve_effective_skills(
        workspace_dir,
        "console",
        user_id="user-1",
    )

    assert resolved == []


def test_runtime_effective_skills_filter_hidden_pool_skill(
    monkeypatch,
    tmp_path,
):
    workspace_dir = tmp_path / "workspace"
    _write_skill_dir(workspace_dir, "hidden_skill")
    _write_skill_dir(workspace_dir, "visible_skill")
    (workspace_dir / "skill.json").write_text(
        json.dumps(
            {
                "skills": {
                    "hidden_skill": {
                        "enabled": True,
                        "channels": ["all"],
                        "source": "customized",
                    },
                    "visible_skill": {
                        "enabled": True,
                        "channels": ["all"],
                        "source": "customized",
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        registry,
        "read_skill_pool_manifest",
        lambda: {
            "skills": {
                "hidden_skill": {
                    "source": "customized",
                    "visibility": "public",
                    "client_visible": False,
                },
                "visible_skill": {
                    "source": "customized",
                    "visibility": "public",
                    "client_visible": True,
                },
            }
        },
    )

    resolved = registry.resolve_effective_skills(
        workspace_dir,
        "console",
        user_id="user-1",
    )

    assert resolved == ["visible_skill"]
