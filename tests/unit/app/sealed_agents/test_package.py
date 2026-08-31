from __future__ import annotations

import base64
import io
import json
import stat
import zipfile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from qwenpaw.app.sealed_agents.package import (
    SealedPackageError,
    SealedPackageManifest,
    build_signed_package_bytes,
    validate_sealed_package,
)


def _keypair():
    private = Ed25519PrivateKey.generate()
    return private, private.public_key()


def _files():
    return {
        "agent/agent.json": json.dumps(
            {"id": "luyu", "name": "陆羽", "description": "茶文化专家"},
        ).encode(),
        "agent/AGENTS.md": b"internal rules\nCANARY-LUYU-9F21",
        "agent/skills/tea/SKILL.md": b"---\nname: tea\n---\nTea skill",
        "public/description.md": "公开介绍".encode(),
    }


def _manifest(**overrides):
    value = {
        "schema_version": 1,
        "agent_id": "luyu",
        "name": "陆羽",
        "version": "1.0.0",
        "agent_type": "sealed",
        "scope": "global",
        "entrypoint": "agent/agent.json",
        "public_metadata": {"description": "茶文化专家"},
        "signer_id": "test-signer",
        "content_digest": f"sha256:{'0' * 64}",
    }
    value.update(overrides)
    return value


def test_valid_signed_package_is_verified_and_extracted(tmp_path):
    private, public = _keypair()
    package = build_signed_package_bytes(_manifest(), _files(), private)

    result = validate_sealed_package(
        package,
        trusted_signers={"test-signer": public},
        staging_root=tmp_path,
    )

    assert result.manifest.agent_id == "luyu"
    assert result.manifest.content_digest.startswith("sha256:")
    assert (result.extracted_root / "agent/AGENTS.md").read_text() == (
        "internal rules\nCANARY-LUYU-9F21"
    )
    assert "agent/AGENTS.md" not in result.public_metadata.model_dump_json()


def test_v1_manifest_without_runtime_keeps_standard_execution():
    manifest = SealedPackageManifest.model_validate(_manifest(schema_version=1))

    assert manifest.runtime is None


def test_v2_manifest_accepts_normalized_harness_contract():
    manifest = SealedPackageManifest.model_validate(
        _manifest(
            schema_version=2,
            runtime={
                "adapter": " sealed_harness ",
                "contract_version": " 1 ",
                "failure_policy": "fail_closed",
            },
        ),
    )
    manifest.validate_supported_contract()

    assert manifest.runtime is not None
    assert manifest.runtime.adapter == "sealed_harness"
    assert manifest.runtime.contract_version == "1"


@pytest.mark.parametrize(
    "runtime",
    [
        {
            "adapter": "agent.runtime:Adapter",
            "contract_version": "1",
            "failure_policy": "fail_closed",
        },
        {
            "adapter": "sealed_harness",
            "contract_version": "1",
            "failure_policy": "fallback",
        },
    ],
)
def test_runtime_declaration_rejects_code_paths_and_fallback(runtime):
    with pytest.raises(ValidationError):
        SealedPackageManifest.model_validate(
            _manifest(schema_version=2, runtime=runtime),
        )


def test_v1_manifest_cannot_declare_runtime():
    manifest = SealedPackageManifest.model_validate(
        _manifest(
            schema_version=1,
            runtime={
                "adapter": "sealed_harness",
                "contract_version": "1",
                "failure_policy": "fail_closed",
            },
        ),
    )

    with pytest.raises(ValueError, match="schema version 1"):
        manifest.validate_supported_contract()


def test_tampered_package_is_rejected(tmp_path):
    private, public = _keypair()
    package = build_signed_package_bytes(_manifest(), _files(), private)
    source = zipfile.ZipFile(io.BytesIO(package))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "agent/AGENTS.md":
                data = b"tampered"
            target.writestr(info, data)

    with pytest.raises(SealedPackageError, match="digest"):
        validate_sealed_package(
            output.getvalue(),
            trusted_signers={"test-signer": public},
            staging_root=tmp_path,
        )


def test_unknown_signer_is_rejected(tmp_path):
    private, _ = _keypair()
    package = build_signed_package_bytes(_manifest(), _files(), private)

    with pytest.raises(SealedPackageError, match="signer"):
        validate_sealed_package(
            package,
            trusted_signers={},
            staging_root=tmp_path,
        )


@pytest.mark.parametrize(
    "member_name",
    ["../escape", "/absolute", "agent/../../escape"],
)
def test_unsafe_paths_are_rejected_before_extraction(tmp_path, member_name):
    private, public = _keypair()
    package = build_signed_package_bytes(_manifest(), _files(), private)
    source = zipfile.ZipFile(io.BytesIO(package))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        target.writestr(member_name, b"escape")

    with pytest.raises(SealedPackageError, match="path"):
        validate_sealed_package(
            output.getvalue(),
            trusted_signers={"test-signer": public},
            staging_root=tmp_path,
        )


def test_symlink_is_rejected(tmp_path):
    private, public = _keypair()
    package = build_signed_package_bytes(_manifest(), _files(), private)
    source = zipfile.ZipFile(io.BytesIO(package))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        link = zipfile.ZipInfo("agent/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        target.writestr(link, b"AGENTS.md")

    with pytest.raises(SealedPackageError, match="regular files"):
        validate_sealed_package(
            output.getvalue(),
            trusted_signers={"test-signer": public},
            staging_root=tmp_path,
        )


def test_standard_or_non_global_manifest_is_rejected(tmp_path):
    private, _ = _keypair()

    with pytest.raises(SealedPackageError, match="manifest"):
        build_signed_package_bytes(
            _manifest(agent_type="standard", scope="tenant"),
            _files(),
            private,
        )


def test_invalid_signature_is_rejected(tmp_path):
    private, public = _keypair()
    package = build_signed_package_bytes(_manifest(), _files(), private)
    source = zipfile.ZipFile(io.BytesIO(package))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "signature.json":
                signature = json.loads(data)
                signature["signature"] = base64.b64encode(b"x" * 64).decode()
                data = json.dumps(signature).encode()
            target.writestr(info, data)

    with pytest.raises(SealedPackageError, match="signature"):
        validate_sealed_package(
            output.getvalue(),
            trusted_signers={"test-signer": public},
            staging_root=tmp_path,
        )
