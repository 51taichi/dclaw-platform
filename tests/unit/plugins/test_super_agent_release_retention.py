from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

from qwenpaw.app.sealed_agents.models import SealedAgentRecord, SealedReleaseRecord
from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry
from qwenpaw.app.sealed_agents.service import SealedAgentService
from qwenpaw.bundled_plugins import load_bundled_plugin_module


retention = load_bundled_plugin_module(
    "dclaw.super-agent-support", "super-agent-support",
    "super_agent.release_retention",
)


def _service(tmp_path, *, count: int, active: int | None = None):
    registry = SealedAgentRegistry(tmp_path)
    releases = []
    for number in range(count):
        release_id = f"release-{number}"
        root = tmp_path / "releases" / "comic" / release_id
        root.mkdir(parents=True)
        (root / "payload").write_text(str(number))
        releases.append(SealedReleaseRecord(
            release_id=release_id,
            version=f"1.0.{number}",
            content_digest="sha256:" + f"{number:064x}",
            signer_id="developer",
            package_type="super_expert_public",
            state="active" if number == active else "superseded",
            installed_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
            + timedelta(days=number),
        ))
    registry.upsert_agent(SealedAgentRecord(
        agent_id="comic", name="Comic", releases=releases,
        active_release_id=f"release-{active}" if active is not None else None,
    ))
    service = SealedAgentService(
        root=tmp_path, registry=registry, trusted_signers={},
    )
    return service


def test_retains_five_newest_and_preserves_task_state(tmp_path):
    service = _service(tmp_path, count=7, active=6)
    state = tmp_path / "workspace_runtime_state" / "task.json"
    state.parent.mkdir()
    state.write_text("customer state")

    retention.retain_releases(service, "comic", "release-6")

    record = service.get_agent("comic")
    assert [item.release_id for item in record.releases] == [
        "release-2", "release-3", "release-4", "release-5", "release-6",
    ]
    assert record.active_release_id == "release-6"
    assert not (tmp_path / "releases/comic/release-0").exists()
    assert not (tmp_path / "releases/comic/release-1").exists()
    assert state.read_text() == "customer state"
    retention.retain_releases(service, "comic", "release-6")
    assert len(service.get_agent("comic").releases) == 5


def test_active_older_release_occupies_one_of_five_slots(tmp_path):
    service = _service(tmp_path, count=7, active=0)

    retention.retain_releases(service, "comic", "release-6")

    record = service.get_agent("comic")
    assert {item.release_id for item in record.releases} == {
        "release-0", "release-3", "release-4", "release-5", "release-6",
    }
    assert (tmp_path / "releases/comic/release-0").is_dir()
    assert not (tmp_path / "releases/comic/release-2").exists()


def test_failed_delete_is_retried_from_journal(tmp_path, monkeypatch):
    service = _service(tmp_path, count=6, active=5)
    original = retention.shutil.rmtree

    def fail_once(path):
        monkeypatch.setattr(retention.shutil, "rmtree", original)
        raise OSError("disk busy")

    monkeypatch.setattr(retention.shutil, "rmtree", fail_once)
    retention.retain_releases(service, "comic", "release-5")
    assert len(service.get_agent("comic").releases) == 5
    assert (tmp_path / "releases/comic/release-0").is_dir()

    retention.retain_releases(service, "comic", "release-5")
    assert not (tmp_path / "releases/comic/release-0").exists()


def test_unrelated_sealed_package_is_untouched(tmp_path):
    service = _service(tmp_path, count=6, active=5)
    record = service.get_agent("comic")
    ordinary = record.releases[0].model_copy(update={"package_type": "sealed_agent"})
    service.registry.upsert_agent(record.model_copy(update={
        "releases": [ordinary, *record.releases[1:]],
    }))

    try:
        retention.retain_releases(service, "comic", "release-5")
    except ValueError as exc:
        assert "mixed package" in str(exc)
    else:
        raise AssertionError("mixed package history must fail closed")
    assert len(service.get_agent("comic").releases) == 6


def test_startup_reconciles_existing_history(tmp_path):
    service = _service(tmp_path, count=8, active=7)

    retention.reconcile_release_retention(service)

    assert len(service.get_agent("comic").releases) == 5
    assert not (tmp_path / "releases/comic/release-0").exists()


def test_concurrent_cleanup_is_idempotent(tmp_path):
    service = _service(tmp_path, count=8, active=7)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(
            lambda _index: retention.retain_releases(
                service, "comic", "release-7",
            ),
            range(8),
        ))

    assert len(service.get_agent("comic").releases) == 5
    assert not retention._journal_path(tmp_path, "comic").exists()
