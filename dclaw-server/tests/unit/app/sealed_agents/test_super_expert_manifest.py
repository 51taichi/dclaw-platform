from __future__ import annotations

import pytest

from qwenpaw.app.sealed_agents.package import (
    CapabilityDeclaration,
    SealedPackageManifest,
)
from qwenpaw.app.sealed_agents.models import SealedReleaseRecord
from qwenpaw.app.sealed_agents.signing import SuperExpertTrustStore
from qwenpaw.app.super_experts.capabilities import (
    CapabilityManifestError,
    PLATFORM_CAPABILITY_CATALOG_V1,
    compute_capability_set_digest,
    validate_super_expert_manifest,
)


def test_aigc_capability_inventory_is_an_authorized_read_only_capability():
    definition = PLATFORM_CAPABILITY_CATALOG_V1["aigc.capabilities.list/1"]

    assert definition.contract_version == "1"
    assert definition.group == "aigc"
    assert definition.dependencies == ()


def test_workflow_capabilities_require_discovery_before_creation():
    discovery = PLATFORM_CAPABILITY_CATALOG_V1[
        "aigc.workflow.capabilities.list/1"
    ]
    creation = PLATFORM_CAPABILITY_CATALOG_V1["aigc.workflow.create/1"]

    assert discovery.contract_version == "1"
    assert discovery.group == "aigc"
    assert discovery.dependencies == ()
    assert creation.contract_version == "1"
    assert creation.group == "aigc"
    assert creation.dependencies == ("aigc.workflow.capabilities.list/1",)


def test_interaction_capabilities_require_discovery_and_create_before_mutation():
    discovery = PLATFORM_CAPABILITY_CATALOG_V1[
        "interaction.capabilities.list/1"
    ]
    creation = PLATFORM_CAPABILITY_CATALOG_V1["interaction.card.create/1"]
    cancellation = PLATFORM_CAPABILITY_CATALOG_V1["interaction.card.cancel/1"]

    assert discovery.contract_version == "1"
    assert discovery.group == "interaction"
    assert discovery.dependencies == ()
    assert creation.group == "interaction"
    assert creation.dependencies == ("interaction.capabilities.list/1",)
    assert cancellation.group == "interaction"
    assert cancellation.dependencies == ("interaction.card.create/1",)


HOST_CAPABILITIES = (
    {"capability_id": "agent.execute", "contract_version": "1"},
    {"capability_id": "session.context", "contract_version": "1"},
    {"capability_id": "runtime.trace", "contract_version": "1"},
    {"capability_id": "runtime.complete", "contract_version": "1"},
    {"capability_id": "runtime.fail", "contract_version": "1"},
)


def _manifest(*, signer_id: str = "official", capabilities=None, **overrides):
    declarations = tuple(
        capabilities
        or (
            {
                "capability_id": "workspace.turn.orchestrate/1",
                "contract_version": "1",
            },
            *HOST_CAPABILITIES,
            {"capability_id": "card.create", "contract_version": "1"},
            {"capability_id": "aigc.task.create", "contract_version": "1"},
        ),
    )
    value = {
        "schema_version": 3,
        "agent_id": "generic-super-expert",
        "name": "Generic Super Expert",
        "version": "1.0.0",
        "agent_type": "sealed",
        "scope": "global",
        "entrypoint": "agent/agent.json",
        "package_type": "super_expert",
        "orchestration": {
            "capability_id": "workspace.turn.orchestrate/1",
            "contract_version": "1",
            "entrypoint": "runtime.py:create_runtime",
            "required_host_capabilities": [
                item["capability_id"] for item in HOST_CAPABILITIES
            ],
        },
        "platform_contract_versions": {
            "runtime": "1",
            "runtime_host": "1",
            "card": "1",
            "aigc": "1",
        },
        "capabilities": declarations,
        "signer_id": signer_id,
        "content_digest": f"sha256:{'0' * 64}",
    }
    value.update(overrides)
    value["capability_digest"] = compute_capability_set_digest(value)
    return SealedPackageManifest.model_validate(value)


def test_official_package_with_complete_declared_set_is_valid():
    manifest = _manifest()

    validated = validate_super_expert_manifest(
        manifest,
        SuperExpertTrustStore(official_signer_ids=frozenset({"official"})),
    )

    assert validated.package_type == "super_expert"
    assert validated.orchestration.capability_id == "workspace.turn.orchestrate/1"


def test_different_complete_capability_sets_do_not_use_one_global_list():
    runtime_only = _manifest(capabilities=(
        {
            "capability_id": "workspace.turn.orchestrate/1",
            "contract_version": "1",
        },
        *HOST_CAPABILITIES,
    ))
    trust = SuperExpertTrustStore(official_signer_ids=frozenset({"official"}))

    assert validate_super_expert_manifest(runtime_only, trust) == runtime_only


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.model_copy(update={"signer_id": "user"}), "official"),
        (
            lambda value: value.model_copy(
                update={
                    "capabilities": tuple(
                        item
                        for item in value.capabilities
                        if item.capability_id != "runtime.complete"
                    ),
                },
            ),
            "digest|dependency",
        ),
        (
            lambda value: value.model_copy(
                update={
                    "capabilities": (
                        *value.capabilities,
                        CapabilityDeclaration(
                            capability_id="unknown.capability",
                            contract_version="1",
                        ),
                    ),
                },
            ),
            "unknown|digest",
        ),
        (
            lambda value: value.model_copy(
                update={
                    "platform_contract_versions": {
                        **value.platform_contract_versions,
                        "runtime": "99",
                    },
                },
            ),
            "digest|version",
        ),
    ],
)
def test_invalid_or_partially_represented_manifest_fails_closed(mutate, message):
    manifest = mutate(_manifest())

    with pytest.raises(CapabilityManifestError, match=message):
        validate_super_expert_manifest(
            manifest,
            SuperExpertTrustStore(official_signer_ids=frozenset({"official"})),
        )


def test_missing_dependency_is_rejected_even_with_matching_digest():
    payload = _manifest().model_dump(mode="json")
    payload["capabilities"] = [
        item
        for item in payload["capabilities"]
        if item["capability_id"] != "runtime.complete"
    ]
    payload["capability_digest"] = compute_capability_set_digest(payload)
    manifest = SealedPackageManifest.model_validate(payload)

    with pytest.raises(CapabilityManifestError, match="dependency"):
        validate_super_expert_manifest(
            manifest,
            SuperExpertTrustStore(official_signer_ids=frozenset({"official"})),
        )


def test_unknown_capability_is_rejected_even_with_matching_digest():
    payload = _manifest().model_dump(mode="json")
    payload["capabilities"].append(
        CapabilityDeclaration(
            capability_id="unknown.capability",
            contract_version="1",
        ).model_dump(mode="json"),
    )
    payload["capability_digest"] = compute_capability_set_digest(payload)
    manifest = SealedPackageManifest.model_validate(payload)

    with pytest.raises(CapabilityManifestError, match="unknown"):
        validate_super_expert_manifest(
            manifest,
            SuperExpertTrustStore(official_signer_ids=frozenset({"official"})),
        )


def test_release_record_can_persist_the_exact_signed_capability_identity():
    manifest = _manifest()
    release = SealedReleaseRecord(
        release_id="release-1",
        version=manifest.version,
        content_digest=manifest.content_digest,
        signer_id=manifest.signer_id,
        package_type=manifest.package_type,
        capability_digest=manifest.capability_digest,
        declared_capabilities=tuple(
            (item.capability_id, item.contract_version)
            for item in manifest.capabilities
        ),
        orchestration_capability_id=manifest.orchestration.capability_id,
        orchestration_contract_version=manifest.orchestration.contract_version,
    )

    assert release.capability_digest == manifest.capability_digest
    assert ("workspace.turn.orchestrate/1", "1") in release.declared_capabilities
