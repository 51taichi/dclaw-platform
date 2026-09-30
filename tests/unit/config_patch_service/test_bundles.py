from __future__ import annotations

import io
import json
import zipfile

from config_patch_service.audit import AuditService
from config_patch_service.bundles import WorkspaceBundleBuilder
from config_patch_service.capabilities import CapabilityCatalogService
from config_patch_service.releases import (
    ContentAddressedObjectStore,
    ReleaseRepository,
)

from .test_releases import aggregated_snapshot


def archive_files(archive: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(archive)) as opened:
        return {name: opened.read(name) for name in opened.namelist()}


def release_and_builder(
    database,
    settings,
    clock,
    *,
    profile="standard-2026.09",
    flow_digest="f" * 64,
):
    store = ContentAddressedObjectStore(settings.data_dir / "objects")
    audit = AuditService(database, clock=clock)
    repository = ReleaseRepository(
        database, object_store=store, audit=audit, clock=clock
    )
    release = repository.create_or_get_baseline(
        aggregated_snapshot(profile=profile, flow_digest=flow_digest),
        actor_token_id="token-a",
        source="initial_baseline"
        if flow_digest == "f" * 64
        else "external_baseline",
    )
    builder = WorkspaceBundleBuilder(
        object_store=store,
        capability_catalog=CapabilityCatalogService().load(),
    )
    return release, builder, store


def test_workspace_bundle_has_exact_contract_and_release_fingerprints(
    database, settings, clock
):
    release, builder, store = release_and_builder(database, settings, clock)

    built = builder.build(release)
    repeated = builder.build(release)
    files = archive_files(built.archive)

    assert built.archive == repeated.archive
    assert built.bundle_digest == repeated.bundle_digest
    assert sorted(files) == [
        "AGENTS.md",
        "agent/source.md",
        "change-plan.yaml",
        "customer-service/flow-machine.json",
        "customer-service/tag-schema.json",
        "dclaw-manifest.json",
        "knowledge/documents/doc-1/source.txt",
        "knowledge/knowledge-manifest.json",
        "platform/capability-catalog.json",
        "platform/coordinated-change-patterns.md",
        "platform/examples/cross-component-change.md",
        "platform/responsibility-matrix.md",
        "platform/runtime-mechanism.md",
    ]
    manifest = json.loads(files["dclaw-manifest.json"])
    assert manifest["schemaVersion"] == "customer-service-workspace.v1"
    assert manifest["botId"] == release.bot_id
    assert manifest["agentId"] == release.agent_id
    assert manifest["agentProfileId"] == release.agent_profile_id
    assert manifest["baseReleaseId"] == "R1"
    assert manifest["capabilityCatalogVersion"] == "2026.09.30"
    assert manifest["fingerprints"] == release.component_digests
    assert store.get(built.object_key) == built.archive


def test_standard_and_super_bundles_are_transparent_and_secret_free(
    database,
    settings,
    clock,
    tmp_path,
):
    standard, builder, _ = release_and_builder(database, settings, clock)
    super_release, _, _ = release_and_builder(
        database,
        settings,
        clock,
        profile="super-expert-2026.09",
        flow_digest="s" * 64,
    )

    standard_files = archive_files(builder.build(standard).archive)
    super_files = archive_files(builder.build(super_release).archive)

    assert standard_files.keys() == super_files.keys()
    standard_manifest = json.loads(standard_files["dclaw-manifest.json"])
    super_manifest = json.loads(super_files["dclaw-manifest.json"])
    assert standard_manifest["agentProfileId"] == "standard-2026.09"
    assert super_manifest["agentProfileId"] == "super-expert-2026.09"
    assert (
        standard_manifest["activeCapabilities"]
        != super_manifest["activeCapabilities"]
    )

    rendered = builder.build(super_release).archive.decode("latin1")
    for forbidden in (
        "signerPrivateKey",
        "runtimeSecret",
        "agent-api-secret-value",
        str(tmp_path),
        str(settings.data_dir),
    ):
        assert forbidden not in rendered
