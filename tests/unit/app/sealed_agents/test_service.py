from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from qwenpaw.app.sealed_agents.package import build_signed_package_bytes
from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry
from qwenpaw.app.sealed_agents.service import (
    SealedAgentReleaseError,
    SealedAgentService,
)


def _package(
    private,
    *,
    version="1.0.0",
    agent_id="luyu",
    schema_version=1,
    runtime=None,
):
    manifest = {
        "schema_version": schema_version,
        "agent_id": agent_id,
        "name": "陆羽",
        "version": version,
        "agent_type": "sealed",
        "scope": "global",
        "entrypoint": "agent/agent.json",
        "public_metadata": {"description": "茶文化专家"},
        "signer_id": "publisher",
    }
    if runtime is not None:
        manifest["runtime"] = runtime
    files = {
        "agent/agent.json": json.dumps(
            {"id": agent_id, "name": "陆羽", "description": "internal"},
        ).encode(),
        "agent/AGENTS.md": b"private",
    }
    return build_signed_package_bytes(manifest, files, private)


def _service(tmp_path, public):
    return SealedAgentService(
        root=tmp_path,
        registry=SealedAgentRegistry(tmp_path),
        trusted_signers={"publisher": public},
    )


def test_install_creates_ready_immutable_release_without_activating(tmp_path):
    private = Ed25519PrivateKey.generate()
    service = _service(tmp_path, private.public_key())
    release = service.install(_package(private))
    agent = service.get_agent("luyu")
    assert release.state == "ready"
    assert agent.active_release_id is None
    assert len(agent.releases) == 1
    release_root = service.release_root("luyu", release.release_id)
    assert (release_root / "agent/AGENTS.md").read_bytes() == b"private"
    assert release.entrypoint == "agent/agent.json"
    assert release.runtime_adapter is None
    assert release.runtime_contract_version is None
    assert release.runtime_failure_policy is None


def test_install_persists_signed_runtime_contract(tmp_path):
    private = Ed25519PrivateKey.generate()
    service = _service(tmp_path, private.public_key())
    release = service.install(
        _package(
            private,
            schema_version=2,
            runtime={
                "adapter": "sealed_harness",
                "contract_version": "1",
                "failure_policy": "fail_closed",
            },
        ),
    )
    assert release.entrypoint == "agent/agent.json"
    assert release.runtime_adapter == "sealed_harness"
    assert release.runtime_contract_version == "1"
    assert release.runtime_failure_policy == "fail_closed"


def test_install_accepts_generic_entrypoint_runtime_contract(tmp_path):
    private = Ed25519PrivateKey.generate()
    service = _service(tmp_path, private.public_key())
    release = service.install(
        _package(
            private,
            schema_version=2,
            runtime={
                "adapter": "sealed_entrypoint",
                "contract_version": "1",
                "failure_policy": "fail_closed",
            },
        ),
    )
    assert release.runtime_adapter == "sealed_entrypoint"
    assert release.runtime_contract_version == "1"


@pytest.mark.asyncio
async def test_historical_adapter_is_validated_as_standard_workspace(tmp_path):
    private = Ed25519PrivateKey.generate()
    service = _service(tmp_path, private.public_key())
    release = service.install(
        _package(
            private,
            schema_version=2,
            runtime={
                "adapter": "sealed_entrypoint",
                "contract_version": "1",
                "failure_policy": "fail_closed",
            },
        ),
    )
    result = await service.validate_release_runtime("luyu", release.release_id)
    assert result.status == "valid"
    assert result.adapter == "standard"
    assert result.contract_version == "1"


@pytest.mark.asyncio
async def test_validation_never_constructs_legacy_runtime(tmp_path, monkeypatch):
    private = Ed25519PrivateKey.generate()
    service = _service(tmp_path, private.public_key())
    release = service.install(
        _package(
            private,
            schema_version=2,
            runtime={
                "adapter": "sealed_harness",
                "contract_version": "1",
                "failure_policy": "fail_closed",
            },
        ),
    )
    import qwenpaw.app.sealed_agents.service as service_module

    def fail_legacy_runtime(*_args, **_kwargs):
        pytest.fail("legacy sealed runtime must not run")

    monkeypatch.setattr(
        service_module,
        "SealedEntrypointProcess",
        fail_legacy_runtime,
        raising=False,
    )
    monkeypatch.setattr(
        service_module,
        "HarnessProcess",
        fail_legacy_runtime,
        raising=False,
    )
    result = await service.validate_release_runtime("luyu", release.release_id)
    assert result.status == "valid"
    assert result.adapter == "standard"


@pytest.mark.asyncio
async def test_runtime_validation_is_persisted_before_activation(tmp_path):
    private = Ed25519PrivateKey.generate()
    service = _service(tmp_path, private.public_key())
    release = service.install(
        _package(
            private,
            schema_version=2,
            runtime={
                "adapter": "sealed_harness",
                "contract_version": "1",
                "failure_policy": "fail_closed",
            },
        ),
    )
    result = await service.validate_release_runtime("luyu", release.release_id)
    assert result.status == "valid"
    assert result.adapter == "standard"
    stored = service.get_agent("luyu")
    assert stored is not None
    assert stored.releases[0].runtime_validation == result
    assert stored.active_release_id is None
    active = service.activate("luyu", release.release_id)
    assert active.active_release_id == release.release_id


@pytest.mark.asyncio
async def test_failed_runtime_validation_preserves_previous_active_release(tmp_path):
    private = Ed25519PrivateKey.generate()
    service = _service(tmp_path, private.public_key())
    previous = service.install(_package(private, version="1.0.0"))
    previous_validation = await service.validate_release_runtime(
        "luyu",
        previous.release_id,
    )
    assert previous_validation.status == "valid"
    service.activate("luyu", previous.release_id)
    candidate = service.install(
        _package(
            private,
            version="1.1.0",
            schema_version=2,
            runtime={
                "adapter": "sealed_harness",
                "contract_version": "1",
                "failure_policy": "fail_closed",
            },
        ),
    )
    candidate_config = (
        service.release_root("luyu", candidate.release_id)
        / "agent"
        / "agent.json"
    )
    candidate_config.write_text("{", encoding="utf-8")
    result = await service.validate_release_runtime("luyu", candidate.release_id)
    assert result.status == "invalid"
    assert result.adapter == "standard"
    assert result.error_code == "agent_config_invalid"
    assert service.get_agent("luyu").active_release_id == previous.release_id
    with pytest.raises(SealedAgentReleaseError, match="runtime validation"):
        service.activate("luyu", candidate.release_id)


@pytest.mark.asyncio
async def test_activate_switches_release_metadata_after_validation(tmp_path):
    private = Ed25519PrivateKey.generate()
    service = _service(tmp_path, private.public_key())
    release = service.install(_package(private))
    validation = await service.validate_release_runtime(
        "luyu",
        release.release_id,
    )
    active = service.activate("luyu", release.release_id)
    assert validation.status == "valid"
    assert active.active_release_id == release.release_id
    assert active.active_release.state == "active"


def test_duplicate_and_downgrade_versions_are_rejected(tmp_path):
    private = Ed25519PrivateKey.generate()
    service = _service(tmp_path, private.public_key())
    service.install(_package(private, version="2.0.0"))
    with pytest.raises(SealedAgentReleaseError, match="version"):
        service.install(_package(private, version="2.0.0"))
    with pytest.raises(SealedAgentReleaseError, match="version"):
        service.install(_package(private, version="1.9.0"))


def test_agents_are_optional_and_failures_are_isolated(tmp_path):
    private = Ed25519PrivateKey.generate()
    service = _service(tmp_path, private.public_key())
    assert service.list_agents() == []
    service.install(_package(private, agent_id="luyu"))
    service.install(_package(private, agent_id="tea-master"))
    service.disable("luyu")
    assert service.get_agent("luyu").enabled is False
    assert service.get_agent("tea-master").enabled is True


@pytest.mark.asyncio
async def test_uploaded_avatar_survives_release_upgrade_and_registry_reload(tmp_path):
    private = Ed25519PrivateKey.generate()
    service = _service(tmp_path, private.public_key())
    service.install(_package(private))
    current = service.get_agent("luyu")
    service.registry.upsert_agent(
        current.model_copy(
            update={
                "avatar": "data:image/png;base64,test",
                "banner_image": "data:image/webp;base64,banner",
            }
        )
    )
    release = service.install(_package(private, version="2.0.0"))
    await service.validate_release_runtime("luyu", release.release_id)
    service.activate("luyu", release.release_id)
    assert (
        SealedAgentRegistry(tmp_path).get_agent("luyu").banner_image
        == "data:image/webp;base64,banner"
    )
    assert (
        SealedAgentRegistry(tmp_path).get_agent("luyu").avatar
        == "data:image/png;base64,test"
    )
