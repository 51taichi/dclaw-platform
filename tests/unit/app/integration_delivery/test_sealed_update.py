from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from qwenpaw.app.integration_delivery.sealed_update import (
    SealedDeliveryError,
    apply_sealed_agent_source,
    restore_sealed_agent_source,
)
from qwenpaw.app.integration_delivery.update import parse_delivery_bundle
from qwenpaw.app.integration_delivery.archive import (
    build_deterministic_archive,
    deterministic_digest,
)
from qwenpaw.app.super_experts.capabilities import compute_capability_set_digest


def _bundle(agent_id: str = "a_service") -> bytes:
    agent_files = {
        "agent/AGENTS.md": b"# Updated\n",
        "agent/agent.json": json.dumps(
            {"id": agent_id, "name": "Updated"},
            separators=(",", ":"),
        ).encode(),
    }
    knowledge_files = {
        "knowledge/knowledge-manifest.json": b'{"documents":[]}',
    }
    component = {
        "agentDigest": deterministic_digest(agent_files),
        "agentId": agent_id,
        "agentProfileId": "sealed-2026.09",
        "knowledgeBaseId": "kb-1",
        "knowledgeDigest": deterministic_digest(knowledge_files),
        "sourceVersion": "1.2.3",
    }
    return build_deterministic_archive(
        {
            **agent_files,
            **knowledge_files,
            "dclaw-component.json": json.dumps(
                component, separators=(",", ":"), sort_keys=True
            ).encode(),
        }
    )


def _manifest(package_type: str) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema_version": 2 if package_type == "sealed_agent" else 3,
        "agent_id": "a_service",
        "name": "Service",
        "version": "1.2.3",
        "agent_type": "sealed",
        "scope": "global",
        "entrypoint": "agent/agent.json",
        "public_metadata": {"description": "kept", "tags": ["support"]},
        "runtime": {
            "adapter": "standard",
            "contract_version": "1",
            "failure_policy": "fail_closed",
        },
        "package_type": package_type,
        "platform_contract_versions": {"cards": "1"},
        "signer_id": "old-signer",
        "content_digest": "sha256:" + "1" * 64,
    }
    if package_type == "super_expert":
        manifest.update(
            {
                "capabilities": [
                    {"capability_id": "card.create", "contract_version": "1"}
                ],
                "capability_digest": "sha256:" + "2" * 64,
                "orchestration": {
                    "capability_id": "workspace.turn.orchestrate/1",
                    "contract_version": "1",
                    "entrypoint": "agent/orchestrator.py:run",
                    "required_host_capabilities": ["agent.execute"],
                },
            }
        )
        manifest["capability_digest"] = compute_capability_set_digest(manifest)
    return manifest


class _SealedService:
    def __init__(self, root: Path, public_key, package_type: str) -> None:
        self.root = root
        self.trusted_signers = {"delivery": public_key}
        self.super_expert_trust_store = SimpleNamespace(
            is_official=lambda signer_id: signer_id == "delivery"
        )
        self.old_release = SimpleNamespace(
            release_id="release-old",
            version="1.2.3",
            package_type=package_type,
        )
        self.record = SimpleNamespace(
            active_release=self.old_release,
            active_release_id="release-old",
            releases=[self.old_release],
            enabled=True,
        )
        self.installed_manifest = None
        self.activated: list[str] = []
        release_root = root / "releases/a_service/release-old"
        (release_root / "agent").mkdir(parents=True)
        (release_root / "manifest.json").write_text(
            json.dumps(_manifest(package_type)), encoding="utf-8"
        )

    def get_agent(self, agent_id: str):
        assert agent_id == "a_service"
        return self.record

    def release_root(self, agent_id: str, release_id: str) -> Path:
        return self.root / "releases" / agent_id / release_id

    def install(self, package: bytes):
        output = self.root / "candidate.zip"
        output.write_bytes(package)
        with zipfile.ZipFile(output) as archive:
            self.installed_manifest = json.loads(archive.read("manifest.json"))
        release = SimpleNamespace(
            release_id="release-new",
            version=self.installed_manifest["version"],
            package_type=self.installed_manifest["package_type"],
        )
        self.record.releases.append(release)
        return release

    async def validate_release_runtime(self, agent_id: str, release_id: str):
        return SimpleNamespace(status="valid")

    def prepare_runtime_workspace(self, agent_id: str, release_id: str) -> Path:
        target = self.root / "runtime_workspaces" / agent_id / release_id / "agent"
        target.mkdir(parents=True, exist_ok=True)
        (target / "agent.json").write_text(
            '{"id":"a_service"}', encoding="utf-8"
        )
        return target

    def grant_installation(self, agent_id, release_id, **kwargs):
        return None

    def activate(self, agent_id: str, release_id: str, **kwargs):
        self.activated.append(release_id)
        self.record.active_release_id = release_id
        return self.record


def _signer(path: Path, private: Ed25519PrivateKey) -> None:
    raw = private.private_bytes_raw()
    path.write_text(
        json.dumps(
            {
                "signerId": "delivery",
                "privateKey": base64.b64encode(raw).decode(),
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("package_type", ["sealed_agent", "super_expert"])
def test_sealed_update_preserves_declarations_and_can_restore(
    tmp_path: Path,
    package_type: str,
) -> None:
    private = Ed25519PrivateKey.generate()
    signer = tmp_path / "signer.json"
    _signer(signer, private)
    service = _SealedService(tmp_path / "sealed", private.public_key(), package_type)

    receipt = apply_sealed_agent_source(
        parse_delivery_bundle("a_service", _bundle()),
        "operation-sealed",
        service=service,
        signer_path=signer,
        activate_runtime=lambda release_id: service.activate(
            "a_service", release_id
        ),
    )

    assert service.installed_manifest["version"] == "1.2.4"
    assert service.installed_manifest["package_type"] == package_type
    assert service.installed_manifest["public_metadata"]["description"] == "kept"
    if package_type == "super_expert":
        assert service.installed_manifest["capabilities"] == _manifest(package_type)[
            "capabilities"
        ]
    assert service.activated == ["release-new"]

    restore_sealed_agent_source(
        receipt,
        service=service,
        activate_runtime=lambda release_id: service.activate(
            "a_service", release_id
        ),
    )
    assert service.activated == ["release-new", "release-old"]


def test_sealed_update_rejects_missing_signing_material(tmp_path: Path) -> None:
    private = Ed25519PrivateKey.generate()
    service = _SealedService(tmp_path / "sealed", private.public_key(), "sealed_agent")

    with pytest.raises(SealedDeliveryError, match="signing material"):
        apply_sealed_agent_source(
            parse_delivery_bundle("a_service", _bundle()),
            "operation-sealed",
            service=service,
            signer_path=tmp_path / "missing.json",
        )

    assert service.activated == []


def test_sealed_update_rejects_signer_public_key_mismatch(tmp_path: Path) -> None:
    private = Ed25519PrivateKey.generate()
    signer = tmp_path / "signer.json"
    _signer(signer, private)
    service = _SealedService(
        tmp_path / "sealed",
        Ed25519PrivateKey.generate().public_key(),
        "sealed_agent",
    )

    with pytest.raises(SealedDeliveryError, match="trusted signer"):
        apply_sealed_agent_source(
            parse_delivery_bundle("a_service", _bundle()),
            "operation-sealed",
            service=service,
            signer_path=signer,
        )

    assert service.activated == []
