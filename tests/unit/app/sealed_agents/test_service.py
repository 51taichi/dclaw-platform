from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from qwenpaw.app.sealed_agents.entrypoint_protocol import RuntimeReady
from qwenpaw.app.sealed_agents.models import RuntimeValidationRecord
from qwenpaw.app.sealed_agents.package import build_signed_package_bytes
from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry
from qwenpaw.app.sealed_agents.runtime import PinnedSealedRuntime
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


def _service(tmp_path, public, *, reload_agent=None, runtime_validator=None):
    return SealedAgentService(
        root=tmp_path,
        registry=SealedAgentRegistry(tmp_path),
        trusted_signers={"publisher": public},
        reload_agent=reload_agent,
        runtime_validator=runtime_validator,
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
async def test_default_runtime_validation_uses_generic_entrypoint_protocol(
    tmp_path,
    monkeypatch,
):
    private = Ed25519PrivateKey.generate()
    service = _service(tmp_path, private.public_key())
    release_root = tmp_path / "release"
    (release_root / "agent").mkdir(parents=True)
    (release_root / "agent/runtime.py").write_text("# fixture")
    pinned = PinnedSealedRuntime(
        agent_id="sealed",
        release_id="release-1",
        version="1.0.0",
        content_digest=f"sha256:{'a' * 64}",
        release_root=release_root,
        entrypoint="agent/runtime.py",
        adapter_key=("sealed_entrypoint", "1"),
        failure_policy="fail_closed",
    )

    class FakeProcess:
        def __init__(self, received, session_root):
            assert received == pinned
            assert session_root.name == "runtime-validation"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def handshake(self):
            return RuntimeReady(
                type="runtime.ready",
                protocol_version="1",
                invocation_id="runtime-validation",
                message_id="handshake",
                adapter="sealed_entrypoint",
                contract_version="1",
            )

    monkeypatch.setattr(
        "qwenpaw.app.sealed_agents.service.SealedEntrypointProcess",
        FakeProcess,
    )

    result = await service._validate_pinned_runtime(pinned)

    assert result.status == "valid"
    assert result.adapter == "sealed_entrypoint"


def test_activate_switches_atomically_after_reload_succeeds(tmp_path):
    private = Ed25519PrivateKey.generate()
    reloads = []
    service = _service(
        tmp_path,
        private.public_key(),
        reload_agent=lambda agent_id, path: reloads.append((agent_id, path)),
    )
    release = service.install(_package(private))

    active = service.activate("luyu", release.release_id)

    assert active.active_release_id == release.release_id
    assert active.active_release.state == "active"
    assert reloads[0][0] == "luyu"
    assert reloads[0][1].name == "agent"


@pytest.mark.asyncio
async def test_runtime_validation_is_persisted_before_activation(tmp_path):
    private = Ed25519PrivateKey.generate()

    async def validate(pinned):
        assert pinned.adapter_key == ("sealed_harness", "1")
        return RuntimeValidationRecord(
            status="valid",
            adapter="sealed_harness",
            contract_version="1",
        )

    service = _service(
        tmp_path,
        private.public_key(),
        runtime_validator=validate,
    )
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
    stored = service.get_agent("luyu")
    assert stored is not None
    assert stored.releases[0].runtime_validation == result
    assert stored.active_release_id is None

    active = service.activate("luyu", release.release_id)
    assert active.active_release_id == release.release_id


@pytest.mark.asyncio
async def test_failed_runtime_validation_preserves_previous_active_release(tmp_path):
    private = Ed25519PrivateKey.generate()

    async def validate(pinned):
        if pinned.adapter_key == ("sealed_harness", "1"):
            return RuntimeValidationRecord(
                status="invalid",
                adapter="sealed_harness",
                contract_version="1",
                error_code="handshake_mismatch",
            )
        return RuntimeValidationRecord(
            status="valid",
            adapter="standard",
            contract_version="1",
        )

    service = _service(
        tmp_path,
        private.public_key(),
        runtime_validator=validate,
    )
    previous = service.install(_package(private, version="1.0.0"))
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

    result = await service.validate_release_runtime("luyu", candidate.release_id)

    assert result.status == "invalid"
    assert service.get_agent("luyu").active_release_id == previous.release_id
    with pytest.raises(SealedAgentReleaseError, match="runtime validation"):
        service.activate("luyu", candidate.release_id)


def test_failed_reload_preserves_previous_active_release(tmp_path):
    private = Ed25519PrivateKey.generate()
    service = _service(tmp_path, private.public_key())
    first = service.install(_package(private, version="1.0.0"))
    service.activate("luyu", first.release_id)
    service._reload_agent = lambda agent_id, path: (_ for _ in ()).throw(
        RuntimeError("private path must not escape"),
    )
    second = service.install(_package(private, version="1.1.0"))

    with pytest.raises(SealedAgentReleaseError) as exc_info:
        service.activate("luyu", second.release_id)

    assert str(exc_info.value) == "sealed agent activation failed"
    assert service.get_agent("luyu").active_release_id == first.release_id


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
