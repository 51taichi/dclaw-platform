from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app.sealed_agents.models import (
    RuntimeValidationRecord,
    SealedAgentRecord,
    SealedReleaseRecord,
)
from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry
from qwenpaw.app.sealed_agents.service import (
    SealedAgentReleaseError,
    SealedAgentService,
)
from qwenpaw.app.super_experts.grants import (
    SuperExpertGrantError,
    SuperExpertGrantRepository,
)


CAPABILITIES = (
    ("workspace.turn.orchestrate/1", "1"),
    ("agent.execute", "1"),
    ("session.context", "1"),
    ("runtime.trace", "1"),
    ("runtime.complete", "1"),
    ("runtime.fail", "1"),
)


def _release(**overrides):
    values = {
        "release_id": "release-1",
        "version": "1.0.0",
        "content_digest": f"sha256:{'1' * 64}",
        "signer_id": "official",
        "package_type": "super_expert",
        "capability_digest": f"sha256:{'2' * 64}",
        "declared_capabilities": CAPABILITIES,
        "orchestration_capability_id": "workspace.turn.orchestrate/1",
        "orchestration_contract_version": "1",
        "orchestration_entrypoint": "runtime.py:create_runtime",
        "orchestration_required_host_capabilities": tuple(
            capability for capability, _version in CAPABILITIES[1:]
        ),
    }
    values.update(overrides)
    return SealedReleaseRecord(**values)


def test_preview_and_accept_persist_the_complete_immutable_manifest(tmp_path):
    repository = SuperExpertGrantRepository(tmp_path)
    preview = repository.preview("agent-1", _release(), tenant_id="tenant-a")

    grant = repository.grant_installation(
        preview,
        administrator_id="admin-1",
    )

    assert grant.capabilities == CAPABILITIES
    assert grant.package_digest == f"sha256:{'1' * 64}"
    assert grant.capability_digest == f"sha256:{'2' * 64}"
    assert repository.get(grant.installation_id) == grant


def test_new_execute_contract_can_be_granted_without_changing_legacy_grants(
    tmp_path,
):
    repository = SuperExpertGrantRepository(tmp_path)
    capabilities = tuple(
        (capability, "2" if capability == "agent.execute" else version)
        for capability, version in CAPABILITIES
    )
    preview = repository.preview(
        "agent-v2",
        _release(declared_capabilities=capabilities),
        tenant_id="tenant-a",
    )

    assert ("agent.execute", "2") in preview.capabilities
    assert ("agent.execute", "1") not in preview.capabilities


def test_cancel_preview_does_not_create_an_installation(tmp_path):
    repository = SuperExpertGrantRepository(tmp_path)
    preview = repository.preview("agent-1", _release(), tenant_id="tenant-a")

    repository.cancel(preview)

    assert repository.list_grants() == []


def test_ordinary_release_cannot_receive_platform_capabilities(tmp_path):
    repository = SuperExpertGrantRepository(tmp_path)

    with pytest.raises(SuperExpertGrantError, match="super expert"):
        repository.preview(
            "agent-1",
            _release(
                package_type="sealed_agent",
                capability_digest=None,
                declared_capabilities=(),
                orchestration_capability_id=None,
                orchestration_contract_version=None,
            ),
            tenant_id="tenant-a",
        )


def test_preview_rejects_missing_or_incompatible_platform_capability(tmp_path):
    repository = SuperExpertGrantRepository(tmp_path)

    with pytest.raises(SuperExpertGrantError, match="unavailable"):
        repository.preview(
            "agent-1",
            _release(
                declared_capabilities=(*CAPABILITIES, ("card.create", "99")),
            ),
            tenant_id="tenant-a",
        )


def test_authorization_is_bound_to_tenant_installation_and_version(tmp_path):
    repository = SuperExpertGrantRepository(tmp_path)
    grant = repository.grant_installation(
        repository.preview("agent-1", _release(), tenant_id="tenant-a"),
        administrator_id="admin-1",
    )

    allowed = repository.authorize_capability(
        grant.installation_id,
        "runtime.complete",
        "1",
        tenant_id="tenant-a",
    )
    wrong_tenant = repository.authorize_capability(
        grant.installation_id,
        "runtime.complete",
        "1",
        tenant_id="tenant-b",
    )
    wrong_version = repository.authorize_capability(
        grant.installation_id,
        "runtime.complete",
        "2",
        tenant_id="tenant-a",
    )

    assert allowed.allowed is True
    assert wrong_tenant.allowed is False
    assert wrong_version.allowed is False


def test_grant_api_cannot_accept_a_requested_subset(tmp_path):
    repository = SuperExpertGrantRepository(tmp_path)
    preview = repository.preview("agent-1", _release(), tenant_id="tenant-a")

    with pytest.raises(TypeError):
        repository.grant_installation(
            preview,
            administrator_id="admin-1",
            capabilities=(("runtime.complete", "1"),),
        )


def test_release_grant_lookup_is_tenant_and_digest_bound(tmp_path):
    repository = SuperExpertGrantRepository(tmp_path)
    release = _release()
    repository.grant_installation(
        repository.preview("agent-1", release, tenant_id="tenant-a"),
        administrator_id="admin-1",
    )

    assert repository.is_release_granted(
        "agent-1",
        release,
        tenant_id="tenant-a",
    )
    assert not repository.is_release_granted(
        "agent-1",
        release,
        tenant_id="tenant-b",
    )
    assert not repository.is_release_granted(
        "agent-1",
        release.model_copy(update={"capability_digest": f"sha256:{'3' * 64}"}),
        tenant_id="tenant-a",
    )


def test_super_expert_activation_requires_the_exact_tenant_grant(tmp_path):
    grant_repository = SuperExpertGrantRepository(tmp_path / "grants")
    registry = SealedAgentRegistry(tmp_path / "registry")
    release = _release(
        runtime_validation=RuntimeValidationRecord(
            status="valid",
            adapter="standard",
            contract_version="1",
        ),
    )
    registry.upsert_agent(
        SealedAgentRecord(
            agent_id="agent-1",
            name="Agent",
            releases=[release],
        ),
    )
    service = SealedAgentService(
        root=tmp_path / "releases",
        registry=registry,
        trusted_signers={},
        package_type_handlers={
            "super_expert": SimpleNamespace(
                requires_installation_grant=True,
                is_release_granted=grant_repository.is_release_granted,
            ),
        },
    )

    with pytest.raises(SealedAgentReleaseError, match="authorization"):
        service.activate("agent-1", release.release_id, tenant_id="tenant-a")
