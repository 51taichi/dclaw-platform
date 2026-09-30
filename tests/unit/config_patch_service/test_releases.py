from __future__ import annotations

import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor

from config_patch_service.audit import AuditService
from config_patch_service.models import (
    DclawSnapshotArchive,
    OmnichannelBotSnapshot,
)
from config_patch_service.releases import (
    AggregatedSnapshot,
    ContentAddressedObjectStore,
    ReleaseRepository,
)

from .test_upstream_clients import omni_snapshot


def dclaw_archive(agent_text: bytes = b"agent source") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("agent/source.md", agent_text)
        archive.writestr(
            "knowledge/documents/doc-1/source.txt", b"knowledge source"
        )
        archive.writestr(
            "knowledge/knowledge-manifest.json",
            json.dumps({"documents": []}, sort_keys=True),
        )
    return output.getvalue()


def aggregated_snapshot(
    *, flow_digest: str = "f" * 64, profile: str = "standard-2026.09"
):
    omni_value = omni_snapshot()
    omni_value["digests"]["flowMachine"] = flow_digest
    return AggregatedSnapshot.from_sources(
        omnichannel=OmnichannelBotSnapshot.model_validate(omni_value),
        dclaw=DclawSnapshotArchive(
            archive=dclaw_archive(),
            agent_id="agent-a",
            profile_id=profile,
            source_version="workspace",
            agent_digest="sha256:" + "a" * 64,
            knowledge_digest="sha256:" + "k" * 64,
        ),
    )


def repository(database, settings, clock):
    store = ContentAddressedObjectStore(settings.data_dir / "objects")
    audit = AuditService(database, clock=clock)
    return (
        ReleaseRepository(
            database, object_store=store, audit=audit, clock=clock
        ),
        store,
    )


def test_first_snapshot_creates_r1_and_same_snapshot_reuses_it(
    database,
    settings,
    clock,
):
    releases, store = repository(database, settings, clock)
    snapshot = aggregated_snapshot()

    first = releases.create_or_get_baseline(
        snapshot,
        actor_token_id="token-a",
        source="initial_baseline",
    )
    second = releases.create_or_get_baseline(
        snapshot,
        actor_token_id="token-a",
        source="initial_baseline",
    )

    assert first.release_id == "R1"
    assert second == first
    assert first.component_digests == {
        "agent": "sha256:" + "a" * 64,
        "knowledge": "sha256:" + "k" * 64,
        "flowMachine": "f" * 64,
        "tags": "t" * 64,
    }
    assert len(releases.list_for_bot("bot-a")) == 1
    assert not first.dclaw_snapshot_object_key.startswith("/")
    assert store.get(first.dclaw_snapshot_object_key) == snapshot.dclaw.archive


def test_concurrent_first_exports_leave_exactly_one_r1(
    database, settings, clock
):
    releases, _ = repository(database, settings, clock)
    snapshot = aggregated_snapshot()

    def create():
        return releases.create_or_get_baseline(
            snapshot,
            actor_token_id="token-concurrent",
            source="initial_baseline",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: create(), range(2)))

    assert [result.release_id for result in results] == ["R1", "R1"]
    assert len(releases.list_for_bot("bot-a")) == 1


def test_external_drift_creates_immutable_next_release_and_audit(
    database,
    settings,
    clock,
):
    releases, _ = repository(database, settings, clock)
    first = releases.create_or_get_baseline(
        aggregated_snapshot(),
        actor_token_id="token-a",
        source="initial_baseline",
    )
    changed = releases.create_or_get_baseline(
        aggregated_snapshot(flow_digest="z" * 64),
        actor_token_id="token-a",
        source="external_baseline",
    )

    assert first.release_id == "R1"
    assert changed.release_id == "R2"
    assert releases.get("bot-a", "R1") == first
    assert (
        releases.get("bot-a", "R1").component_digests["flowMachine"]
        == "f" * 64
    )
    assert changed.component_digests["flowMachine"] == "z" * 64
    with database.connect() as connection:
        events = connection.execute(
            """
            SELECT action, metadata_json
            FROM audit_events
            WHERE action = 'release.external_drift'
            """
        ).fetchall()
    assert len(events) == 1
    assert json.loads(events[0]["metadata_json"])["fromReleaseId"] == "R1"
    assert json.loads(events[0]["metadata_json"])["toReleaseId"] == "R2"
