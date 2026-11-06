from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from qwenpaw.app.sealed_agents.package import inspect_extracted_payload
from super_agent import state_continuity as continuity


CONTRACT = continuity.StateContract(
    contract=continuity.CONTRACT,
    format_id="comic.v1",
    schema_version=1,
    filename_template="work-{identity_sha256_24}.json",
)
REVISIONS = {
    "story": [{"version": "v1", "content": "story"}],
    "script": [{"version": f"v{n}", "content": f"script {n}"} for n in range(1, 4)],
    "design": [{"version": f"v{n}", "based_on": {"script": "v3"}} for n in range(1, 4)],
    "storyboard": [],
}


def setup_chain(tmp_path: Path, *, descriptor: bool = True):
    sealed = tmp_path / "sealed"
    storage = tmp_path / "storage"
    storage.mkdir()
    releases = []
    grants = []
    for number in range(3):
        release_id = f"release-{number}"
        release_root = sealed / "releases" / "comic" / release_id / "agent"
        release_root.mkdir(parents=True)
        (release_root / "workflow.py").write_text("STATE_SCHEMA = 1\n")
        if descriptor:
            (release_root / "state-contract.json").write_text(
                CONTRACT.model_dump_json(), encoding="utf-8",
            )
        digest, _ = inspect_extracted_payload(release_root.parent)
        releases.append(SimpleNamespace(
            release_id=release_id, content_digest=digest,
            version=f"0.2.{number}", signer_id="developer.one",
            package_type="super_expert",
        ))
        grants.append(SimpleNamespace(
            installation_id=f"installation-{number}", release_id=release_id,
            package_digest=digest, package_version=f"0.2.{number}",
            agent_id="comic", tenant_id="tenant",
            granted_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=number),
        ))
    record = SimpleNamespace(agent_id="comic", active_release_id="release-1", releases=releases)
    repository = SimpleNamespace(list_grants=lambda: grants, get=lambda ident: next(
        (grant for grant in grants if grant.installation_id == ident), None,
    ))
    identity = {"installation_id": "installation-0", "user_id": "user", "session_id": "task"}
    source_dir = continuity._state_dir(storage, "installation-0", "task")
    source_dir.mkdir(parents=True)
    source_file = source_dir / continuity._filename(CONTRACT, identity)
    original = {
        "schema_version": 1, "identity": identity, "revisions": REVISIONS,
        "pending_cards": [], "confirmed": {}, "processed_interactions": [],
    }
    source_file.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
    return sealed, storage, record, repository, grants, source_file


def resume(sealed, storage, record, repository, target, *, apply=True):
    return continuity.ensure_state_continuity(
        storage_root=storage, sealed_root=sealed,
        grants=repository, record=record, target_grant=target,
        session_id="task", user_id="user", apply=apply,
    )


def test_continuous_two_upgrades_are_atomic_and_idempotent(tmp_path):
    sealed, storage, record, repository, grants, source_file = setup_chain(tmp_path)
    before = source_file.read_bytes()
    preview = resume(sealed, storage, record, repository, grants[1], apply=False)
    assert preview["status"] == "preview"
    first = resume(sealed, storage, record, repository, grants[1])
    assert first["status"] == "committed"
    assert resume(sealed, storage, record, repository, grants[1])["status"] == "already_migrated"
    record.active_release_id = "release-2"
    second = resume(sealed, storage, record, repository, grants[2])
    assert second["source_installation_id"] == "installation-1"
    assert second["content_sha256"] == first["content_sha256"]
    assert source_file.read_bytes() == before
    target_file = continuity._only_state_file(continuity._state_dir(storage, "installation-2", "task"))
    target = json.loads(target_file.read_text(encoding="utf-8"))
    assert target["revisions"] == REVISIONS
    assert target["identity"]["installation_id"] == "installation-2"


def test_activation_preflight_checks_existing_task_before_release_switch(tmp_path):
    sealed, storage, record, repository, grants, source_file = setup_chain(tmp_path)
    record.active_release_id = grants[0].release_id
    source_file.parent.with_suffix(".lock").write_text("")
    before = source_file.read_bytes()
    preview = continuity.preview_activation_continuity(
        storage_root=storage, sealed_root=sealed, grants=repository,
        record=record, target_grant=grants[1],
    )
    assert preview == {
        "contract": continuity.CONTRACT, "status": "ready", "checked_tasks": 1,
    }
    assert record.active_release_id == grants[0].release_id
    assert source_file.read_bytes() == before
    assert not continuity._state_dir(storage, "installation-1", "task").exists()

    descriptor = sealed / "releases" / "comic" / "release-1" / "agent" / "state-contract.json"
    descriptor.write_text(
        CONTRACT.model_copy(update={"schema_version": 2}).model_dump_json(),
        encoding="utf-8",
    )
    digest, _ = inspect_extracted_payload(descriptor.parent.parent)
    record.releases[1].content_digest = digest
    grants[1].package_digest = digest
    with pytest.raises(continuity.StateContinuityError, match="state_schema_incompatible"):
        continuity.preview_activation_continuity(
            storage_root=storage, sealed_root=sealed, grants=repository,
            record=record, target_grant=grants[1],
        )
    assert record.active_release_id == grants[0].release_id
    assert source_file.read_bytes() == before


def test_activation_preflight_accepts_attested_legacy_source(tmp_path):
    sealed, storage, record, repository, grants, source_file = setup_chain(tmp_path)
    record.active_release_id = grants[0].release_id
    old_descriptor = (
        sealed / "releases" / "comic" / "release-0"
        / "agent" / "state-contract.json"
    )
    old_descriptor.unlink()
    old_release_root = old_descriptor.parent.parent
    old_digest, _ = inspect_extracted_payload(old_release_root)
    record.releases[0].content_digest = old_digest
    grants[0].package_digest = old_digest
    evidence = old_release_root / "agent" / "workflow.py"
    continuity._write_json(storage / continuity._REGISTRY, {
        "schema_version": 1,
        "contracts": [{
            "agent_id": "comic", "release_id": "release-0",
            "content_digest": old_digest, "signer_id": "developer.one",
            "evidence_module": "agent/workflow.py",
            "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            "state_contract": CONTRACT.model_dump(),
        }],
    })
    before = source_file.read_bytes()
    assert continuity.preview_activation_continuity(
        storage_root=storage, sealed_root=sealed, grants=repository,
        record=record, target_grant=grants[1],
    )["checked_tasks"] == 1
    assert source_file.read_bytes() == before
    assert not continuity._state_dir(storage, "installation-1", "task").exists()


def test_concurrent_resume_commits_once(tmp_path):
    sealed, storage, record, repository, grants, _ = setup_chain(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(
            lambda _: resume(sealed, storage, record, repository, grants[1]),
            range(4),
        ))
    assert sorted(item["status"] for item in outcomes) == [
        "already_migrated", "already_migrated", "already_migrated", "committed",
    ]


def test_incompatible_contract_and_existing_target_fail_closed(tmp_path):
    sealed, storage, record, repository, grants, _ = setup_chain(tmp_path)
    descriptor = sealed / "releases" / "comic" / "release-1" / "agent" / "state-contract.json"
    incompatible = CONTRACT.model_copy(update={"schema_version": 2})
    descriptor.write_text(incompatible.model_dump_json(), encoding="utf-8")
    with pytest.raises(continuity.StateContinuityError, match="state_release_integrity_failed"):
        resume(sealed, storage, record, repository, grants[1])
    digest, _ = inspect_extracted_payload(descriptor.parent.parent)
    record.releases[1].content_digest = digest
    grants[1].package_digest = digest
    with pytest.raises(continuity.StateContinuityError, match="state_schema_incompatible"):
        resume(sealed, storage, record, repository, grants[1])
    descriptor.write_text(CONTRACT.model_dump_json(), encoding="utf-8")
    digest, _ = inspect_extracted_payload(descriptor.parent.parent)
    record.releases[1].content_digest = digest
    grants[1].package_digest = digest
    target_dir = continuity._state_dir(storage, "installation-1", "task")
    target_dir.mkdir(parents=True)
    identity = {"installation_id": "installation-1", "user_id": "user", "session_id": "task"}
    (target_dir / continuity._filename(CONTRACT, identity)).write_text(json.dumps({
        "schema_version": 1, "identity": identity,
        "revisions": {key: [] for key in REVISIONS},
    }))
    with pytest.raises(continuity.StateContinuityError, match="state_target_conflict"):
        resume(sealed, storage, record, repository, grants[1])


def test_interrupted_promotion_recovers_without_losing_source(tmp_path, monkeypatch):
    sealed, storage, record, repository, grants, source_file = setup_chain(tmp_path)
    before = hashlib.sha256(source_file.read_bytes()).hexdigest()
    original_bind = continuity._bind_state_file
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("interrupted")
        return original_bind(*args, **kwargs)

    monkeypatch.setattr(continuity, "_bind_state_file", fail_once)
    with pytest.raises(OSError, match="interrupted"):
        resume(sealed, storage, record, repository, grants[1])
    assert hashlib.sha256(source_file.read_bytes()).hexdigest() == before
    recovered = resume(sealed, storage, record, repository, grants[1])
    assert recovered["status"] == "already_migrated"
    assert continuity._binding_matches(storage, "installation-1", "task", recovered["target_filename"])


def test_interrupted_before_promotion_retries_prepared_receipt(tmp_path, monkeypatch):
    sealed, storage, record, repository, grants, source_file = setup_chain(tmp_path)
    original_replace = continuity.os.replace
    failed = False

    def fail_promotion(source, destination):
        nonlocal failed
        if not failed and str(destination).endswith(continuity._scope_key("task")):
            failed = True
            raise OSError("promotion interrupted")
        return original_replace(source, destination)

    monkeypatch.setattr(continuity.os, "replace", fail_promotion)
    with pytest.raises(OSError, match="promotion interrupted"):
        resume(sealed, storage, record, repository, grants[1])
    assert continuity._receipt_path(storage, "installation-1", "task").is_file()
    assert not continuity._state_dir(storage, "installation-1", "task").exists()
    assert json.loads(source_file.read_text())["revisions"] == REVISIONS
    assert resume(sealed, storage, record, repository, grants[1])["status"] == "committed"


def test_cross_tenant_or_user_state_cannot_be_imported(tmp_path):
    sealed, storage, record, repository, grants, _ = setup_chain(tmp_path)
    grants[1].tenant_id = "other"
    assert resume(sealed, storage, record, repository, grants[1])["status"] == "new_or_existing"
    grants[1].tenant_id = "tenant"
    with pytest.raises(continuity.StateContinuityError, match="state_filename_incompatible"):
        continuity.ensure_state_continuity(
            storage_root=storage, sealed_root=sealed, grants=repository,
            record=record, target_grant=grants[1], session_id="task",
            user_id="other-user",
        )


def test_operator_apply_rejects_stale_preview(tmp_path):
    sealed, storage, record, repository, grants, _ = setup_chain(tmp_path)
    preview = resume(sealed, storage, record, repository, grants[1], apply=False)
    with pytest.raises(continuity.StateContinuityError, match="state_source_changed"):
        continuity.ensure_state_continuity(
            storage_root=storage, sealed_root=sealed, grants=repository,
            record=record, target_grant=grants[1], session_id="task",
            user_id="user", expected_source_installation_id="installation-0",
            expected_source_file_sha256="0" * 64,
        )
    assert not continuity._state_dir(storage, "installation-1", "task").exists()
    assert continuity.ensure_state_continuity(
        storage_root=storage, sealed_root=sealed, grants=repository,
        record=record, target_grant=grants[1], session_id="task",
        user_id="user", expected_source_installation_id="installation-0",
        expected_source_file_sha256=preview["source_file_sha256"],
        expected_target_release_id="release-1",
    )["status"] == "committed"


def test_legacy_registration_requires_identical_signed_evidence(tmp_path):
    sealed, storage, record, repository, grants, _ = setup_chain(tmp_path, descriptor=False)
    preview = continuity.register_legacy_pair(
        storage_root=storage, sealed_root=sealed, record=record,
        source_release_id="release-0", target_release_id="release-1",
        evidence_module="agent/workflow.py", contract=CONTRACT,
    )
    with pytest.raises(continuity.StateContinuityError, match="state_evidence_changed"):
        continuity.register_legacy_pair(
            storage_root=storage, sealed_root=sealed, record=record,
            source_release_id="release-0", target_release_id="release-1",
            evidence_module="agent/workflow.py", contract=CONTRACT, apply=True,
        )
    continuity.register_legacy_pair(
        storage_root=storage, sealed_root=sealed, record=record,
        source_release_id="release-0", target_release_id="release-1",
        evidence_module="agent/workflow.py", contract=CONTRACT, apply=True,
        expected_source_digest=preview["source_content_digest"],
        expected_target_digest=preview["target_content_digest"],
        expected_evidence_sha256=preview["evidence_sha256"],
    )
    assert resume(sealed, storage, record, repository, grants[1])["status"] == "committed"
