from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from super_agent.state_migration import (
    StateMigrationError,
    bind_reconciled_state,
    migrate_empty_field,
    reconcile_shadowed_migration,
)
from super_agent.orchestration import WorkspaceOrchestrationError, WorkspaceStateTransaction


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


def test_bootstraps_missing_target_then_migrates_one_field(tmp_path):
    source = _write_state(tmp_path, "old", "task", "57", {
        "story": [{"version": "v1", "content": "story"}],
        "script": [{"version": "v1", "content": "script"}],
    })
    document = json.loads(source.read_text())
    document.update(schema_version=1, confirmed={}, pending_cards={}, processed_interactions=[])
    source.write_text(json.dumps(document), encoding="utf-8")
    args = {
        **_input(tmp_path),
        "bootstrap_empty_target": True,
        "target_state_filename": "work-new.json",
    }

    preview = migrate_empty_field(**args)
    assert preview["target_file_sha256"] == "missing"
    assert preview["target_bootstrap_required"] is True
    receipt = migrate_empty_field(
        **args, apply=True,
        expected_source_file_sha256=preview["source_file_sha256"],
        expected_target_file_sha256=preview["target_file_sha256"],
    )

    target_dir = tmp_path / "state" / hashlib.sha256(b"new").hexdigest() / hashlib.sha256(b"task").hexdigest()
    restored = json.loads(next(target_dir.glob("*.json")).read_text())
    assert restored["revisions"]["story"] == document["revisions"]["story"]
    assert restored["revisions"]["script"] == []
    assert restored["identity"]["installation_id"] == "new"
    assert receipt["status"] == "committed"
    assert next(target_dir.glob("*.json")).name == "work-new.json"


def test_wrong_migrated_filename_cannot_commit_a_shadow_state(tmp_path):
    source = _write_state(tmp_path, "old", "task", "57", {
        "story": [{"version": "v1", "content": "story"}],
    })
    document = json.loads(source.read_text())
    document.update(schema_version=1, confirmed={}, pending_cards={}, processed_interactions=[])
    source.write_text(json.dumps(document), encoding="utf-8")
    args = {
        **_input(tmp_path), "bootstrap_empty_target": True,
        "target_state_filename": "work-wrong.json",
    }
    preview = migrate_empty_field(**args)
    migrate_empty_field(
        **args, apply=True,
        expected_source_file_sha256=preview["source_file_sha256"],
        expected_target_file_sha256=preview["target_file_sha256"],
    )
    transaction = WorkspaceStateTransaction.begin(
        tmp_path, installation_id="new", session_id="task", invocation_id="turn",
    )
    (transaction.transaction_root / "work-actual.json").write_text(
        json.dumps({"identity": {
            "installation_id": "new", "session_id": "task", "user_id": "57",
        }, "revisions": {"design": [{"version": "v1"}]}}),
        encoding="utf-8",
    )
    with pytest.raises(WorkspaceOrchestrationError) as error:
        transaction.commit()
    assert error.value.diagnostic_ref == "state_scope_conflict"
    transaction.discard()
    target_dir = tmp_path / "state" / hashlib.sha256(b"new").hexdigest() / hashlib.sha256(b"task").hexdigest()
    assert [item.name for item in target_dir.glob("*.json")] == ["work-wrong.json"]


def test_bootstrap_requires_target_filename(tmp_path):
    source = _write_state(tmp_path, "old", "task", "57", {
        "story": [{"version": "v1"}],
    })
    document = json.loads(source.read_text())
    document.update(schema_version=1, confirmed={}, pending_cards={}, processed_interactions=[])
    source.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(StateMigrationError, match="target state filename required"):
        migrate_empty_field(**_input(tmp_path), bootstrap_empty_target=True)


def test_reconciles_shadowed_migration_without_losing_either_state(tmp_path):
    source = _write_state(tmp_path, "old", "task", "57", {
        "story": [{"version": "v1", "content": "story"}],
        "design": [{"version": "v1", "content": "old design"}],
    })
    document = json.loads(source.read_text())
    document.update(schema_version=1, confirmed={}, pending_cards={}, processed_interactions=[])
    source.write_text(json.dumps(document), encoding="utf-8")
    # Reproduce a migration made before target filenames were required.
    target_dir = tmp_path / "state" / hashlib.sha256(b"new").hexdigest() / hashlib.sha256(b"task").hexdigest()
    target_dir.mkdir(parents=True)
    migrated = target_dir / "work-old.json"
    migrated_document = dict(document)
    migrated_document["identity"] = {**document["identity"], "installation_id": "new"}
    migrated.write_text(json.dumps(migrated_document), encoding="utf-8")
    active = target_dir / "work-new.json"
    active_document = {**migrated_document, "revisions": {"story": [], "design": [{"version": "v1", "content": "new design"}]}}
    active.write_text(json.dumps(active_document), encoding="utf-8")
    migrated_sha = hashlib.sha256(migrated.read_bytes()).hexdigest()
    active_sha = hashlib.sha256(active.read_bytes()).hexdigest()
    receipts = tmp_path / "migrations" / "receipts"
    receipts.mkdir(parents=True)
    migration_id = "a" * 32
    (receipts / f"{migration_id}.json").write_text(json.dumps({
        "status": "committed", "target_installation_id": "new",
        "target_release_id": "0.2.1", "agent_id": "comic", "session_id": "task",
        "target_file_sha256_after": migrated_sha,
    }), encoding="utf-8")
    binding = tmp_path / "migrations" / "bindings" / hashlib.sha256(b"new").hexdigest() / f"{hashlib.sha256(b'task').hexdigest()}.json"
    binding.parent.mkdir(parents=True)
    binding.write_text(json.dumps({
        "contract": "workspace.state.binding/1",
        "installation_id": "new", "session_id": "task",
        "filename": migrated.name, "receipt_id": migration_id,
    }), encoding="utf-8")
    reconcile_args = dict(
        storage_root=tmp_path, grants=_grants(), installation_id="new",
        session_id="task", user_id="57", migration_id=migration_id,
        migrated_filename=migrated.name, active_filename=active.name,
    )
    preview = reconcile_shadowed_migration(**reconcile_args)
    assert preview["status"] == "preview"
    assert hashlib.sha256(active.read_bytes()).hexdigest() == active_sha
    result = reconcile_shadowed_migration(
        **reconcile_args, apply=True,
        expected_migrated_sha256=preview["migrated_sha256"],
        expected_active_sha256=preview["active_sha256"],
    )
    assert result["status"] == "committed"
    assert not migrated.exists()
    assert hashlib.sha256(active.read_bytes()).hexdigest() == migrated_sha
    archived = tmp_path / "migrations" / "shadowed" / result["repair_id"] / active.name
    assert hashlib.sha256(archived.read_bytes()).hexdigest() == active_sha
    assert json.loads(binding.read_text())["filename"] == active.name
    binding.write_text(json.dumps({
        "contract": "workspace.state.binding/1",
        "installation_id": "new", "session_id": "task",
        "filename": migrated.name, "receipt_id": migration_id,
    }), encoding="utf-8")
    active.write_text(active.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    current_sha = hashlib.sha256(active.read_bytes()).hexdigest()
    registered = bind_reconciled_state(
        storage_root=tmp_path, grants=_grants(), installation_id="new",
        session_id="task", user_id="57", repair_id=result["repair_id"],
        expected_state_sha256=current_sha,
    )
    assert registered["status"] == "registered"
    assert json.loads(binding.read_text())["filename"] == active.name


def test_reconcile_rejects_migration_receipt_mismatch(tmp_path):
    source = _write_state(tmp_path, "new", "task", "57", {"story": []})
    shadow = source.with_name("other.json")
    shadow.write_bytes(source.read_bytes())
    receipts = tmp_path / "migrations" / "receipts"
    receipts.mkdir(parents=True)
    (receipts / ("a" * 32 + ".json")).write_text(json.dumps({
        "status": "committed", "target_installation_id": "new",
        "target_release_id": "0.2.1", "agent_id": "comic", "session_id": "task",
        "target_file_sha256_after": "0" * 64,
    }), encoding="utf-8")
    with pytest.raises(StateMigrationError, match="differs from committed receipt"):
        reconcile_shadowed_migration(
            storage_root=tmp_path, grants=_grants(), installation_id="new",
            session_id="task", user_id="57", migration_id="a" * 32,
            migrated_filename="other.json", active_filename="work.json",
        )


def test_missing_target_requires_explicit_bootstrap(tmp_path):
    _write_state(tmp_path, "old", "task", "57", {"story": [{"version": "v1"}]})
    with pytest.raises(StateMigrationError, match="state directory missing"):
        migrate_empty_field(**_input(tmp_path))


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
