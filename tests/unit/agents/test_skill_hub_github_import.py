import pytest

from qwenpaw.agents.skill_system import hub
from qwenpaw.exceptions import SkillsError


def test_github_repo_url_with_multiple_skills_requires_explicit_path(monkeypatch):
    monkeypatch.setattr(
        hub,
        "_github_get_content_entry",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            hub.HTTPError(args[2], 404, "not found", None, None),
        ),
    )
    monkeypatch.setattr(
        hub,
        "_github_list_skill_md_roots",
        lambda *args, **kwargs: [
            "skills/gsap",
            "skills/hyperframes",
            "skills/three",
        ],
    )

    with pytest.raises(SkillsError) as exc_info:
        hub._fetch_bundle_from_repo_and_skill_hint(
            owner="heygen-com",
            repo="hyperframes",
            skill_hint="",
            requested_version="",
            default_branch="main",
        )

    message = str(exc_info.value)
    assert "multiple skills" in message
    assert (
        "https://github.com/heygen-com/hyperframes/tree/main/skills/hyperframes"
        in message
    )


def test_github_repo_url_with_single_skill_still_auto_selects(monkeypatch):
    content_entry = {"type": "file", "download_url": "https://example.com/SKILL.md"}

    def fake_get_content_entry(_owner, _repo, path, _ref):
        if path == "skills/hyperframes/SKILL.md":
            return content_entry
        raise hub.HTTPError(path, 404, "not found", None, None)

    monkeypatch.setattr(hub, "_github_get_content_entry", fake_get_content_entry)
    monkeypatch.setattr(
        hub,
        "_github_list_skill_md_roots",
        lambda *args, **kwargs: ["skills/hyperframes"],
    )
    monkeypatch.setattr(
        hub,
        "_github_read_file",
        lambda _entry: "---\nname: hyperframes\n---\n",
    )
    monkeypatch.setattr(
        hub,
        "_github_collect_tree_files",
        lambda **kwargs: {"SKILL.md": "---\nname: hyperframes\n---\n"},
    )

    bundle, source_url = hub._fetch_bundle_from_repo_and_skill_hint(
        owner="heygen-com",
        repo="hyperframes",
        skill_hint="",
        requested_version="",
        default_branch="main",
    )

    assert bundle["name"] == "hyperframes"
    assert bundle["files"]["SKILL.md"].startswith("---")
    assert source_url == "https://github.com/heygen-com/hyperframes"
