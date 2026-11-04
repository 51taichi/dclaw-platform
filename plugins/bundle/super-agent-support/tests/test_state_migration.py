from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from super_agent.state_migration import StateMigrationError, migrate_empty_field


def _write_state(root: Path, installation: str, session: str, user: str, revisions: dict) -> Path:
    scoped = root / "state" / hashlib.sha256(installation.encode()).hexdigest() / hashlib.sha256(session.encode()).hexdigest()
    scoped.mkdir(parents=True)
    path = scoped / "work.json"
    path.write_text(json.dumps({
        "identity": {"installation_id": installation, "session_id": session, "user_id": user},
        "revisions": revisions,
    }), encoding="utf-8")
    return path


def _grants(agent: str = "comic"):
    records = {
        "old": SimpleNamespace(agent_id=agent, tenant_id="tenant", release_id="0.2.0"),
        "new": SimpleNamespace(agent_id=agent, tenant_id="tenant", release_id="0.2.1"),
    }
    return SimpleNamespace(get=records.get)


def _input(root: Path, grants=None) -> dict:
    return {
        "storage_root": root,
        "grants": grants or _grants(),
        "source_installation_id": "old",
        "target_installation_id": "new",
        "session_id": "task",
        "user_id": "57",
        "pointer": "/revisions/story",
    }


def test_migrates_history_without_changing_target_revisions(tmp_path):
    story = [{"version": "v1", "status": "candidate", "based_on": {}, "content": "story"}]
    old = _write_state(tmp_path, "old", "task", "57", {"story": story})
    existing = {
        "story": [],
        "script": [{"version": f"v{n}", "content": f"script {n}"} for n in range(1, 4)],
        "design": [{"version": "v1", "based_on": {"script": "v3"}}],
    }
    new = _write_state(tmp_path, "new", "task", "57", existing)
    args = _input(tmp_path)

    preview = migrate_empty_field(**args)
    assert preview["source_versions"] == ["v1"]
    assert json.loads(new.read_text())["revisions"]["story"] == []
    receipt = migrate_empty_field(
        **args, apply=True,
        expected_source_file_sha256=preview["source_file_sha256"],
        expected_target_file_sha256=preview["target_file_sha256"],
    )

    after = json.loads(new.read_text())["revisions"]
    assert after["story"] == story
    assert after["script"] == existing["script"]
    assert after["design"] == existing["design"]
    assert json.loads(old.read_text())["revisions"]["story"] == story
    assert receipt["status"] == "committed"
    assert receipt["target_file_sha256_after"] == hashlib.sha256(new.read_bytes()).hexdigest()
    assert json.loads((tmp_path / "migrations" / "receipts" / f"{receipt['migration_id']}.json").read_text()) == receipt


def test_rejects_stale_preview_without_changing_target(tmp_path):
    _write_state(tmp_path, "old", "task", "57", {"story": [{"version": "v1"}]})
    new = _write_state(tmp_path, "new", "task", "57", {"story": [], "script": []})
    args = _input(tmp_path)
    preview = migrate_empty_field(**args)
    new.write_text(new.read_text() + " ", encoding="utf-8")
    before = new.read_bytes()

    with pytest.raises(StateMigrationError, match="state changed since preview"):
        migrate_empty_field(
            **args, apply=True,
            expected_source_file_sha256=preview["source_file_sha256"],
            expected_target_file_sha256=preview["target_file_sha256"],
        )
    assert new.read_bytes() == before


@pytest.mark.parametrize("target_user,target_agent", [
    ("other", "comic"),
    ("57", "other-agent"),
])
def test_rejects_cross_user_or_agent(tmp_path, target_user, target_agent):
    _write_state(tmp_path, "old", "task", "57", {"story": [{"version": "v1"}]})
    _write_state(tmp_path, "new", "task", target_user, {"story": []})
    records = {
        "old": SimpleNamespace(agent_id="comic", tenant_id="tenant", release_id="old"),
        "new": SimpleNamespace(agent_id=target_agent, tenant_id="tenant", release_id="new"),
    }
    with pytest.raises(StateMigrationError):
        migrate_empty_field(**_input(tmp_path, SimpleNamespace(get=records.get)))
