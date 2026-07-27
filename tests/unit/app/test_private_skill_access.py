import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import skills as skills_router


def _request(user_id: str, role: str = "user"):
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id, role=role))


def _write_skill(root: Path, name: str, description: str = "Test skill") -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: {description}
---
# {name}
""",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_create_skill_api_forces_user_created_skill_private(
    monkeypatch,
    tmp_path,
):
    from qwenpaw.app import agent_context

    workspace_dir = tmp_path / "workspace"

    async def fake_get_agent_for_request(_request):
        return SimpleNamespace(
            workspace_dir=str(workspace_dir),
            agent_id="default",
        )

    monkeypatch.setattr(
        agent_context,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )

    result = await skills_router.create_skill(
        _request("user-1"),
        skills_router.CreateSkillRequest(
            name="user_skill",
            content="""---
name: user_skill
description: User-created skill
---
# User Skill
""",
            enable=False,
            visibility="public",
        ),
    )

    manifest = json.loads((workspace_dir / "skill.json").read_text())
    entry = manifest["skills"]["user_skill"]
    assert result == {"created": True, "name": "user_skill"}
    assert entry["visibility"] == "private"
    assert entry["owner_user_id"] == "user-1"


def test_pool_private_skill_list_is_filtered_by_owner(monkeypatch, tmp_path):
    pool_dir = tmp_path / "skill_pool"
    for name in ("public_skill", "own_private", "other_private"):
        _write_skill(pool_dir, name)

    manifest = {
        "skills": {
            "public_skill": {
                "source": "customized",
                "visibility": "public",
            },
            "own_private": {
                "source": "customized",
                "visibility": "private",
                "owner_user_id": "user-1",
            },
            "other_private": {
                "source": "customized",
                "visibility": "private",
                "owner_user_id": "user-2",
            },
        }
    }
    monkeypatch.setattr(
        skills_router,
        "read_skill_pool_manifest",
        lambda: json.loads(json.dumps(manifest)),
    )
    monkeypatch.setattr(skills_router, "get_skill_pool_dir", lambda: pool_dir)
    monkeypatch.setattr(
        skills_router,
        "get_pool_builtin_sync_status",
        lambda pool_skills: {},
    )

    specs = skills_router._build_pool_skill_specs(_request("user-1"))

    assert [spec.name for spec in specs] == ["own_private", "public_skill"]


def test_pool_hidden_skill_is_filtered_from_client_lists(monkeypatch, tmp_path):
    pool_dir = tmp_path / "skill_pool"
    for name in ("visible_skill", "hidden_skill"):
        _write_skill(pool_dir, name)

    manifest = {
        "skills": {
            "visible_skill": {
                "source": "customized",
                "visibility": "public",
                "client_visible": True,
            },
            "hidden_skill": {
                "source": "customized",
                "visibility": "public",
                "client_visible": False,
            },
        }
    }
    monkeypatch.setattr(
        skills_router,
        "read_skill_pool_manifest",
        lambda: json.loads(json.dumps(manifest)),
    )
    monkeypatch.setattr(skills_router, "get_skill_pool_dir", lambda: pool_dir)
    monkeypatch.setattr(
        skills_router,
        "get_pool_builtin_sync_status",
        lambda pool_skills: {},
    )

    specs = skills_router._build_pool_skill_specs(_request("admin-user", "admin"))
    admin_specs = skills_router._build_pool_skill_specs(
        _request("admin-user", "admin"),
        include_hidden=True,
    )
    user_specs = skills_router._build_pool_skill_specs(
        _request("user-1"),
        include_hidden=True,
    )

    assert [spec.name for spec in specs] == ["visible_skill"]
    assert [spec.name for spec in admin_specs] == [
        "hidden_skill",
        "visible_skill",
    ]
    assert [spec.name for spec in user_specs] == ["visible_skill"]
    assert admin_specs[0].client_visible is False


def test_workspace_private_skill_list_is_filtered_by_owner(monkeypatch, tmp_path):
    workspace_dir = tmp_path / "workspace"
    skill_root = workspace_dir / "skills"
    for name in ("public_skill", "own_private", "other_private"):
        _write_skill(skill_root, name)

    (workspace_dir / "skill.json").write_text(
        json.dumps(
            {
                "skills": {
                    "public_skill": {
                        "enabled": True,
                        "source": "customized",
                    },
                    "own_private": {
                        "enabled": True,
                        "source": "customized",
                        "visibility": "private",
                        "owner_user_id": "user-1",
                    },
                    "other_private": {
                        "enabled": True,
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
    monkeypatch.setattr(
        skills_router,
        "read_skill_pool_manifest",
        lambda: {"skills": {}},
    )

    specs = skills_router._build_workspace_skill_specs(
        workspace_dir,
        _request("user-1"),
    )

    assert [spec.name for spec in specs] == ["own_private", "public_skill"]


def test_workspace_hidden_skill_inherits_pool_client_visibility(
    monkeypatch,
    tmp_path,
):
    workspace_dir = tmp_path / "workspace"
    skill_root = workspace_dir / "skills"
    _write_skill(skill_root, "hidden_skill")
    _write_skill(skill_root, "visible_skill")
    (workspace_dir / "skill.json").write_text(
        json.dumps(
            {
                "skills": {
                    "hidden_skill": {
                        "enabled": True,
                        "source": "customized",
                    },
                    "visible_skill": {
                        "enabled": True,
                        "source": "customized",
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        skills_router,
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

    specs = skills_router._build_workspace_skill_specs(
        workspace_dir,
        _request("user-1"),
    )

    assert [spec.name for spec in specs] == ["visible_skill"]


def test_workspace_private_skill_inherits_pool_owner_filter(
    monkeypatch,
    tmp_path,
):
    workspace_dir = tmp_path / "workspace"
    skill_root = workspace_dir / "skills"
    _write_skill(skill_root, "other_private")
    (workspace_dir / "skill.json").write_text(
        json.dumps(
            {
                "skills": {
                    "other_private": {
                        "enabled": True,
                        "source": "customized",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        skills_router,
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

    specs = skills_router._build_workspace_skill_specs(
        workspace_dir,
        _request("user-1"),
    )

    assert specs == []


def test_private_pool_skill_access_requires_owner(monkeypatch):
    monkeypatch.setattr(
        skills_router,
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

    with pytest.raises(HTTPException) as exc:
        skills_router._require_pool_skill_access(
            _request("user-1"),
            "other_private",
        )

    assert exc.value.status_code == 404


def test_admin_can_access_private_pool_skill(monkeypatch):
    monkeypatch.setattr(
        skills_router,
        "read_skill_pool_manifest",
        lambda: {
            "skills": {
                "private_skill": {
                    "source": "customized",
                    "visibility": "private",
                    "owner_user_id": "user-2",
                }
            }
        },
    )

    entry = skills_router._require_pool_skill_access(
        _request("admin-user", role="admin"),
        "private_skill",
    )

    assert entry["owner_user_id"] == "user-2"


def test_private_workspace_skill_access_requires_owner(tmp_path):
    workspace_dir = tmp_path / "workspace"
    skill_root = workspace_dir / "skills"
    _write_skill(skill_root, "other_private")
    (workspace_dir / "skill.json").write_text(
        json.dumps(
            {
                "skills": {
                    "other_private": {
                        "enabled": True,
                        "source": "customized",
                        "visibility": "private",
                        "owner_user_id": "user-2",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(HTTPException) as exc:
        skills_router._require_workspace_skill_access(
            _request("user-1"),
            workspace_dir,
            "other_private",
        )

    assert exc.value.status_code == 404


def test_private_workspace_skill_access_inherits_pool_owner(
    monkeypatch,
    tmp_path,
):
    workspace_dir = tmp_path / "workspace"
    skill_root = workspace_dir / "skills"
    _write_skill(skill_root, "other_private")
    (workspace_dir / "skill.json").write_text(
        json.dumps(
            {
                "skills": {
                    "other_private": {
                        "enabled": True,
                        "source": "customized",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        skills_router,
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

    with pytest.raises(HTTPException) as exc:
        skills_router._require_workspace_skill_access(
            _request("user-1"),
            workspace_dir,
            "other_private",
        )

    assert exc.value.status_code == 404
