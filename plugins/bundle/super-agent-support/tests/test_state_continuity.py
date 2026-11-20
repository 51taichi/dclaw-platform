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
from super_agent.aigc_binding import (
    compatible_installations, read_developer_binding, resolve_existing_binding,
)
from super_agent.aigc_tools import _identity


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


def test_aigc_binding_resolves_only_one_owned_task_through_committed_chain(tmp_path):
    sealed, storage, record, repository, grants, _ = setup_chain(tmp_path)
    resume(sealed, storage, record, repository, grants[1])
    record.active_release_id = "release-2"
    resume(sealed, storage, record, repository, grants[2])
    scope = dict(
        storage_root=storage, grants=repository, agent_id="comic",
        tenant_id="tenant", installation_id="installation-2",
        release_id="release-2", session_id="task", user_id="user",
    )
    lineage = compatible_installations(**scope)
    assert lineage == frozenset({
        "installation-0", "installation-1", "installation-2",
    })
    material_id = "material-1"
    binding = SimpleNamespace(
        installation_id="installation-0", conversation_id="task",
        agent_task_id="content-" + _identity(
            "installation-0", "task", "production",
        ),
        content_revision=1, material_task_id=material_id, canvas_id="canvas-1",
    )
    task = SimpleNamespace(binding=binding, status=SimpleNamespace(value="ACCEPTED"))
    canvas = SimpleNamespace(id="canvas-1", meta={
        "owner_user_id": "user", "super_expert_material_task_id": material_id,
    })
    adapter = SimpleNamespace(workflow_context=lambda **_: (canvas, []))
    request = dict(
        tasks=(task,), adapter=adapter, user_id="user",
        conversation_id="task", allowed_installations=lineage,
    )
    found = resolve_existing_binding(**request, task_key="production", content_revision=1)
    assert found["status"] == "found"
    assert found["material_task_id"] == material_id
    assert resolve_existing_binding(**request) == found
    assert resolve_existing_binding(**request, task_key="other")["status"] == "not_found"
    assert resolve_existing_binding(**{**request, "user_id": "other"})["status"] == "not_found"
    assert resolve_existing_binding(**{**request, "tasks": (task, task)})["status"] == "ambiguous"
    with pytest.raises(continuity.StateContinuityError):
        compatible_installations(**{**scope, "tenant_id": "other"})
    with pytest.raises(continuity.StateContinuityError):
        compatible_installations(**{**scope, "user_id": "other"})
    developer_args = dict(
        storage_root=storage, grants=repository,
        task_repository=SimpleNamespace(
            list_for_conversations=lambda _: (task,),
        ),
        event_repository=SimpleNamespace(
            list_for_session=lambda **_: (
                SimpleNamespace(event_type="aigc.task.created", material_task_id=material_id),
            ),
        ),
        adapter=adapter,
        owner_resolver=lambda _: {
            "agent_id": "comic", "tenant_id": "tenant",
            "session_id": "task", "user_id": "user",
        },
        agent_id="comic", tenant_id="tenant",
        installation_id="installation-2", release_id="release-2",
        session_id="task",
    )
    developer_result = read_developer_binding(**developer_args)
    assert developer_result["contract"] == "developer.aigc.binding.lookup/1"
    assert developer_result["material_task_id"] == material_id
    assert developer_result["created_event_persisted"] is True
    assert developer_result["current_workspace_references_task"] is False
    assert read_developer_binding(
        **{**developer_args, "owner_resolver": lambda _: None},
    )["status"] == "not_found"
    target_file = continuity._only_state_file(
        continuity._state_dir(storage, "installation-2", "task"),
    )
    target_state = json.loads(target_file.read_text())
    target_state["recovered_material_task_id"] = material_id
    target_file.write_text(json.dumps(target_state))
    assert compatible_installations(**scope) == lineage
    assert read_developer_binding(**developer_args)[
        "current_workspace_references_task"
    ] is True
    receipt_path = continuity._receipt_path(storage, "installation-2", "task")
    receipt = json.loads(receipt_path.read_text())
    receipt["status"] = "prepared"
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(continuity.StateContinuityError):
        compatible_installations(**scope)


def test_retired_source_does_not_block_activation_or_create_empty_state(tmp_path):
    sealed, storage, record, repository, grants, source_file = setup_chain(tmp_path)
    original = source_file.read_bytes()
    record.releases = record.releases[1:]
    record.active_release_id = "release-2"
    (sealed / "releases" / "comic" / "release-0" / "agent" / "workflow.py").unlink()

    preview = continuity.preview_activation_continuity(
        storage_root=storage, sealed_root=sealed, grants=repository,
        record=record, target_grant=grants[2],
    )

    assert preview["status"] == "ready"
    assert preview["checked_tasks"] == 1
    result = resume(sealed, storage, record, repository, grants[2])
    assert result["status"] == "committed"
    assert result["source_release_id"] == "release-0"
    assert source_file.read_bytes() == original
    target_file = continuity._only_state_file(
        continuity._state_dir(storage, "installation-2", "task"),
    )
    target = json.loads(target_file.read_text(encoding="utf-8"))
    assert target["revisions"] == REVISIONS
    assert target["identity"] == {
        "installation_id": "installation-2",
        "user_id": "user",
        "session_id": "task",
    }


def test_retired_source_still_requires_target_schema_compatibility(tmp_path):
    sealed, storage, record, repository, grants, source_file = setup_chain(tmp_path)
    state = json.loads(source_file.read_text(encoding="utf-8"))
    state["schema_version"] = 2
    source_file.write_text(json.dumps(state), encoding="utf-8")
    record.releases = record.releases[1:]
    record.active_release_id = "release-2"

    with pytest.raises(
        continuity.StateContinuityError,
        match="state_schema_incompatible",
    ):
        resume(sealed, storage, record, repository, grants[2])
    assert not continuity._state_dir(storage, "installation-2", "task").exists()


def test_unbound_legacy_auxiliary_json_is_not_workspace_state(tmp_path):
    sealed, storage, record, repository, grants, source_file = setup_chain(tmp_path)
    auxiliary = source_file.with_name("interaction-catalog-v1.json")
    auxiliary.write_text(json.dumps({
        "catalog_version": "interaction.components/1",
        "components": [],
        "answer_schema": {},
    }), encoding="utf-8")
    source_file.unlink()
    record.releases = record.releases[1:]
    record.active_release_id = "release-2"

    preview = continuity.preview_activation_continuity(
        storage_root=storage, sealed_root=sealed, grants=repository,
        record=record, target_grant=grants[2],
    )
    result = resume(sealed, storage, record, repository, grants[2])

    assert preview == {
        "contract": continuity.CONTRACT,
        "status": "ready",
        "checked_tasks": 0,
    }
    assert result == {
        "contract": continuity.CONTRACT,
        "status": "new_or_existing",
    }
    assert not continuity._state_dir(storage, "installation-2", "task").exists()


def test_bound_legacy_auxiliary_json_fails_activation_preflight(tmp_path):
    sealed, storage, record, repository, grants, source_file = setup_chain(tmp_path)
    auxiliary = source_file.with_name("interaction-catalog-v1.json")
    auxiliary.write_text(json.dumps({
        "catalog_version": "interaction.components/1",
        "components": [],
        "answer_schema": {},
    }), encoding="utf-8")
    source_file.unlink()
    continuity._state_binding_path(
        storage, "installation-0", "task",
    ).parent.mkdir(parents=True)
    continuity._state_binding_path(
        storage, "installation-0", "task",
    ).write_text(json.dumps({
        "contract": "workspace.state.binding/1",
        "installation_id": "installation-0",
        "session_id": "task",
        "filename": auxiliary.name,
    }), encoding="utf-8")
    record.releases = record.releases[1:]
    record.active_release_id = "release-2"

    with pytest.raises(
        continuity.StateContinuityError,
        match="state_scope_conflict",
    ):
        continuity.preview_activation_continuity(
            storage_root=storage, sealed_root=sealed, grants=repository,
            record=record, target_grant=grants[2],
        )
    with pytest.raises(
        continuity.StateContinuityError,
        match="state_scope_conflict",
    ):
        resume(sealed, storage, record, repository, grants[2])


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


def test_empty_legacy_scope_is_not_a_committed_task(tmp_path):
    sealed, storage, record, repository, grants, source_file = setup_chain(tmp_path)
    empty_task = continuity._state_dir(storage, "installation-1", "task")
    empty_task.mkdir(parents=True)
    empty_other = continuity._state_dir(storage, "installation-1", "other-task")
    empty_other.mkdir(parents=True)
    record.active_release_id = "release-2"
    before = source_file.read_bytes()

    def preflight():
        return continuity.preview_activation_continuity(
            storage_root=storage, sealed_root=sealed, grants=repository,
            record=record, target_grant=grants[2],
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(lambda _: preflight(), range(4)))
    assert all(item["checked_tasks"] == 1 for item in outcomes)
    assert all(item["status"] == "ready" for item in outcomes)
    preview = resume(sealed, storage, record, repository, grants[2], apply=False)
    assert preview["source_installation_id"] == "installation-0"
    assert source_file.read_bytes() == before
    assert not continuity._state_dir(storage, "installation-2", "task").exists()


def test_empty_target_scope_can_receive_verified_state(tmp_path):
    sealed, storage, record, repository, grants, source_file = setup_chain(tmp_path)
    target_dir = continuity._state_dir(storage, "installation-1", "task")
    target_dir.mkdir(parents=True)
    before = source_file.read_bytes()
    assert resume(sealed, storage, record, repository, grants[1], apply=False)["status"] == "preview"
    first = resume(sealed, storage, record, repository, grants[1])
    assert first["status"] == "committed"
    assert resume(sealed, storage, record, repository, grants[1])["status"] == "already_migrated"
    assert source_file.read_bytes() == before
    assert json.loads(continuity._only_state_file(target_dir).read_text())["revisions"] == REVISIONS


def test_empty_target_scope_recovers_after_interrupted_promotion(tmp_path, monkeypatch):
    sealed, storage, record, repository, grants, source_file = setup_chain(tmp_path)
    target_dir = continuity._state_dir(storage, "installation-1", "task")
    target_dir.mkdir(parents=True)
    before = source_file.read_bytes()
    original_replace = continuity.os.replace
    failed = False

    def fail_promotion(source, destination):
        nonlocal failed
        if not failed and Path(destination) == target_dir:
            failed = True
            raise OSError("promotion interrupted")
        return original_replace(source, destination)

    monkeypatch.setattr(continuity.os, "replace", fail_promotion)
    with pytest.raises(OSError, match="promotion interrupted"):
        resume(sealed, storage, record, repository, grants[1])
    assert not list(target_dir.iterdir())
    assert source_file.read_bytes() == before
    assert resume(sealed, storage, record, repository, grants[1])["status"] == "committed"
    assert json.loads(continuity._only_state_file(target_dir).read_text())["revisions"] == REVISIONS


def test_empty_scope_does_not_hide_conflicts_or_wrong_binding(tmp_path):
    sealed, storage, record, repository, grants, source_file = setup_chain(tmp_path)
    legacy_dir = continuity._state_dir(storage, "installation-0", "other-task")
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "unexpected.txt").write_text("unexpected")
    with pytest.raises(continuity.StateContinuityError, match="state_scope_conflict"):
        continuity.preview_activation_continuity(
            storage_root=storage, sealed_root=sealed, grants=repository,
            record=record, target_grant=grants[1],
        )
    (legacy_dir / "unexpected.txt").unlink()
    target_dir = continuity._state_dir(storage, "installation-1", "task")
    target_dir.mkdir(parents=True)
    continuity._state_binding_path(storage, "installation-1", "task").parent.mkdir(parents=True)
    continuity._state_binding_path(storage, "installation-1", "task").write_text("{}")
    with pytest.raises(continuity.StateContinuityError, match="state_scope_conflict"):
        resume(sealed, storage, record, repository, grants[1])
    assert source_file.is_file()


def test_empty_legacy_scope_with_binding_fails_closed(tmp_path):
    sealed, storage, record, repository, grants, _ = setup_chain(tmp_path)
    empty_dir = continuity._state_dir(storage, "installation-1", "other-task")
    empty_dir.mkdir(parents=True)
    binding = continuity._state_binding_path(storage, "installation-1", "other-task")
    binding.parent.mkdir(parents=True)
    binding.write_text("{}")
    record.active_release_id = "release-2"
    with pytest.raises(continuity.StateContinuityError, match="state_scope_conflict"):
        continuity.preview_activation_continuity(
            storage_root=storage, sealed_root=sealed, grants=repository,
            record=record, target_grant=grants[2],
        )
    with pytest.raises(continuity.StateContinuityError, match="state_scope_conflict"):
        continuity.ensure_state_continuity(
            storage_root=storage, sealed_root=sealed, grants=repository,
            record=record, target_grant=grants[2],
            session_id="other-task", user_id="user", apply=False,
        )


def test_empty_target_without_source_rejects_stale_binding(tmp_path):
    sealed, storage, record, repository, grants, source_file = setup_chain(tmp_path)
    source_file.unlink()
    target_dir = continuity._state_dir(storage, "installation-1", "task")
    target_dir.mkdir(parents=True)
    assert resume(sealed, storage, record, repository, grants[1])["status"] == "new_or_existing"
    binding = continuity._state_binding_path(storage, "installation-1", "task")
    binding.parent.mkdir(parents=True)
    binding.write_text("{}")
    with pytest.raises(continuity.StateContinuityError, match="state_scope_conflict"):
        resume(sealed, storage, record, repository, grants[1])


def test_symlinked_installation_scope_fails_closed(tmp_path):
    sealed, storage, record, repository, grants, _ = setup_chain(tmp_path)
    installation = storage / "state" / continuity._scope_key("installation-1")
    installation.symlink_to(storage / "state" / continuity._scope_key("installation-0"))
    with pytest.raises(continuity.StateContinuityError, match="state_scope_conflict"):
        continuity.preview_activation_continuity(
            storage_root=storage, sealed_root=sealed, grants=repository,
            record=record, target_grant=grants[2],
        )


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
