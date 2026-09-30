from __future__ import annotations

import io
import hashlib
import json
import struct
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


def _digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for path, content in sorted(files.items()):
        encoded = path.encode()
        digest.update(struct.pack(">Q", len(encoded)))
        digest.update(encoded)
        digest.update(struct.pack(">Q", len(content)))
        digest.update(content)
    return "sha256:" + digest.hexdigest()


def dclaw_archive(
    agent_text: bytes = b"agent source",
    *,
    agent_id: str = "agent-a",
    profile_id: str = "standard-2026.09",
    source_version: str = "workspace",
) -> bytes:
    agent_files = {"agent/source.md": agent_text}
    knowledge_files = {
        "knowledge/documents/doc-1/source.txt": b"knowledge source",
        "knowledge/knowledge-manifest.json": json.dumps(
            {"documents": []}, sort_keys=True
        ).encode(),
    }
    component = {
        "agentDigest": _digest(agent_files),
        "agentId": agent_id,
        "agentProfileId": profile_id,
        "knowledgeBaseId": "kb-a",
        "knowledgeDigest": _digest(knowledge_files),
        "sourceVersion": source_version,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path, content in {**agent_files, **knowledge_files}.items():
            archive.writestr(path, content)
        archive.writestr("dclaw-component.json", json.dumps(component))
    return output.getvalue()


def aggregated_snapshot(
    *, flow_digest: str = "f" * 64, profile: str = "standard-2026.09"
):
    omni_value = omni_snapshot()
    omni_value["digests"]["flowMachine"] = flow_digest
    archive = dclaw_archive(profile_id=profile)
    with zipfile.ZipFile(io.BytesIO(archive)) as opened:
        component = json.loads(opened.read("dclaw-component.json"))
    return AggregatedSnapshot.from_sources(
        omnichannel=OmnichannelBotSnapshot.model_validate(omni_value),
        dclaw=DclawSnapshotArchive(
            archive=archive,
            agent_id="agent-a",
            profile_id=profile,
            source_version="workspace",
            agent_digest=component["agentDigest"],
            knowledge_digest=component["knowledgeDigest"],
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
        "agent": snapshot.dclaw.agent_digest,
        "knowledge": snapshot.dclaw.knowledge_digest,
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


def test_concurrent_different_snapshots_allow_only_one_cas_success(
    database, settings, clock
):
    releases, _ = repository(database, settings, clock)
    snapshots = [
        aggregated_snapshot(flow_digest="x" * 64),
        aggregated_snapshot(flow_digest="y" * 64),
    ]

    def create(snapshot):
        return releases.create_or_get_baseline(
            snapshot,
            actor_token_id="token-concurrent",
            source="initial_baseline",
            expected_previous_snapshot_digest=None,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create, snapshot) for snapshot in snapshots]
    outcomes = []
    for future in futures:
        try:
            outcomes.append(future.result().release_id)
        except Exception as exc:  # asserted below by stable domain type
            outcomes.append(type(exc).__name__)

    assert sorted(outcomes) == ["R1", "ReleaseConflictError"]
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
