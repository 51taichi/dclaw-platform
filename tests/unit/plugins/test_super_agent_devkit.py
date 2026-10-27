# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import zipfile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator

from qwenpaw.app.sealed_agents.package import (
    build_signed_package_bytes,
    validate_sealed_package,
)
from qwenpaw.app.super_experts.capabilities import (
    PLATFORM_CAPABILITY_CATALOG_V1,
    compute_capability_set_digest,
)


ROOT = Path(__file__).parents[3]
PLUGIN_ROOT = ROOT / "plugins" / "bundle" / "super-agent-support"
DEVKIT_ROOT = PLUGIN_ROOT / "devkit"
DEVKIT_SCRIPT = DEVKIT_ROOT / "dclaw_agent_devkit.py"
FIXTURE = (
    ROOT / "tests" / "fixtures" / "super_expert" / "generic-orchestration-v1"
)


def _devkit():
    spec = importlib.util.spec_from_file_location(
        "standalone_dclaw_agent_devkit",
        DEVKIT_SCRIPT,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _business_identity_verifier():
    path = DEVKIT_ROOT / "business_identity_verifier.py"
    spec = importlib.util.spec_from_file_location(
        "standalone_business_identity_verifier",
        path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _business_assertion(private_key, *, jti: str, now: int):
    def encode(value):
        raw = (
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            if isinstance(value, dict)
            else value
        )
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    header = {"alg": "EdDSA", "kid": "key-1", "typ": "JWT"}
    payload = {
        "iss": "https://dclaw.deepmega.cn/business-identity",
        "aud": "https://service.deepmega.cn/v1",
        "sub": "urn:dclaw:installation:" + "a" * 64,
        "jti": jti,
        "iat": now,
        "nbf": now,
        "exp": now + 120,
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "session_id": "session-1",
        "agent_id": "agent-1",
        "release_id": "release-1",
        "installation_id": "install-1",
        "invocation_id": "invocation-1",
        "service_id": "service-1",
        "scopes": ["orders.read"],
    }
    signing_input = f"{encode(header)}.{encode(payload)}"
    signature = private_key.sign(signing_input.encode("ascii"))
    return f"{signing_input}.{encode(signature)}", payload


def _key_files(tmp_path: Path) -> tuple[Ed25519PrivateKey, Path, Path]:
    private = Ed25519PrivateKey.generate()
    private_path = tmp_path / "private.b64"
    public_path = tmp_path / "public.b64"
    private_path.write_text(
        base64.b64encode(
            private.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            ),
        ).decode("ascii"),
        encoding="utf-8",
    )
    public_path.write_text(
        base64.b64encode(
            private.public_key().public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            ),
        ).decode("ascii"),
        encoding="utf-8",
    )
    return private, private_path, public_path


def test_devkit_has_no_server_source_import_and_runs_standalone():
    source = DEVKIT_SCRIPT.read_text(encoding="utf-8")
    assert "import qwenpaw" not in source
    assert "from qwenpaw" not in source

    completed = subprocess.run(
        [sys.executable, str(DEVKIT_SCRIPT), "contracts"],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["status"] == "ok"
    assert result["devkit_version"] == "1.4.0"
    assert result["dependency_mode"] == "bundled-wheelhouse"
    assert result["cryptography_version"] == "46.0.3"
    assert "schemas/super-expert-manifest.schema.json" in result["schemas"]
    assert (
        "schemas/local-execution-v1/tool-call.schema.json" in result["schemas"]
    )


def test_devkit_bundles_and_verifies_locked_encryption_dependencies():
    devkit = _devkit()
    completed = subprocess.run(
        [
            sys.executable,
            str(DEVKIT_SCRIPT),
            "doctor",
            "--wheelhouse-only",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["status"] == "ok"
    assert result["devkit_version"] == "1.4.0"
    assert result["wheelhouse_verified"] is True
    assert result["wheelhouse_files"] == 26

    checksum_digests = {
        line.split("  ", 1)[0]
        for line in (DEVKIT_ROOT / "CHECKSUMS.sha256")
        .read_text(encoding="ascii")
        .splitlines()
        if line
    }
    lock_text = (DEVKIT_ROOT / "requirements.lock").read_text(
        encoding="utf-8",
    )
    lock_digests = {
        match.group(1)
        for match in re.finditer(
            r"--hash=sha256:([0-9a-f]{64})",
            lock_text,
        )
    }
    assert checksum_digests == lock_digests
    for line in (
        (DEVKIT_ROOT / "CHECKSUMS.sha256")
        .read_text(
            encoding="ascii",
        )
        .splitlines()
    ):
        digest, relative = line.split("  ", 1)
        actual = hashlib.sha256((DEVKIT_ROOT / relative).read_bytes())
        assert actual.hexdigest() == digest
    assert devkit._verify_wheelhouse() == 26


def test_devkit_catalog_and_digest_match_platform_contract():
    devkit = _devkit()
    catalog = json.loads(
        (DEVKIT_ROOT / "capability-catalog.json").read_text(encoding="utf-8"),
    )
    devkit_core = {
        item["capability_id"]: (
            item["contract_version"],
            item["group"],
            tuple(item["dependencies"]),
        )
        for item in catalog["capabilities"]
        if item["group"] not in {"local_execution", "business_identity"}
    }
    server_core = {
        capability_id: (
            item.contract_version,
            item.group,
            item.dependencies,
        )
        for capability_id, item in PLATFORM_CAPABILITY_CATALOG_V1.items()
    }
    assert devkit_core == server_core

    manifest = json.loads(
        (FIXTURE / "manifest.template.json").read_text(encoding="utf-8"),
    )
    digest = devkit.compute_capability_digest(manifest)
    assert digest == compute_capability_set_digest(manifest)
    manifest["capability_digest"] = digest
    devkit.validate_manifest(manifest, require_content_digest=False)


def test_required_local_helper_preflight_requires_local_session():
    devkit = _devkit()
    manifest = json.loads(
        (FIXTURE / "manifest.template.json").read_text(encoding="utf-8"),
    )
    manifest["platform_contract_versions"]["local_execution"] = "1"
    manifest["capabilities"].append(
        {
            "capability_id": "local.environment.preflight/1",
            "contract_version": "1",
        },
    )
    manifest["capability_digest"] = devkit.compute_capability_digest(manifest)

    with pytest.raises(
        devkit.DevKitError,
        match="missing capability dependency: local.execution.session/1",
    ):
        devkit.validate_manifest(manifest, require_content_digest=False)

    manifest["capabilities"].append(
        {
            "capability_id": "local.execution.session/1",
            "contract_version": "1",
        },
    )
    manifest["capability_digest"] = devkit.compute_capability_digest(manifest)

    devkit.validate_manifest(manifest, require_content_digest=False)


def test_devkit_build_is_accepted_and_matches_server_package(tmp_path):
    devkit = _devkit()
    private, private_path, public_path = _key_files(tmp_path)
    manifest_path = FIXTURE / "manifest.template.json"
    devkit_package = devkit.build_package(
        FIXTURE / "agent",
        manifest_path,
        private_path,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["capability_digest"] = compute_capability_set_digest(manifest)
    agent_root = FIXTURE / "agent"
    files = {
        f"agent/{path.relative_to(agent_root).as_posix()}": path.read_bytes()
        for path in agent_root.rglob("*")
        if path.is_file()
    }
    server_package = build_signed_package_bytes(manifest, files, private)

    with zipfile.ZipFile(io.BytesIO(devkit_package)) as devkit_zip:
        with zipfile.ZipFile(io.BytesIO(server_package)) as server_zip:
            assert devkit_zip.read("manifest.json") == server_zip.read(
                "manifest.json",
            )
            assert devkit_zip.read("signature.json") == server_zip.read(
                "signature.json",
            )

    validated = validate_sealed_package(
        devkit_package,
        trusted_signers={"official-test": private.public_key()},
        staging_root=tmp_path / "staging",
    )
    assert validated.manifest.agent_id == "generic-orchestration"
    package_path = tmp_path / "release.zip"
    package_path.write_bytes(devkit_package)
    verified = devkit.verify_package(package_path, public_path)
    assert verified["agent_id"] == "generic-orchestration"


def test_devkit_copies_canonical_local_execution_schemas():
    canonical = ROOT / "docs" / "contracts" / "local-execution" / "v1"
    bundled = DEVKIT_ROOT / "schemas" / "local-execution-v1"
    for name in (
        "error-envelope.schema.json",
        "tool-call.schema.json",
        "tool-response.schema.json",
    ):
        assert (bundled / name).read_bytes() == (canonical / name).read_bytes()


def test_devkit_schemas_are_valid_and_plugin_contracts_are_canonical():
    for path in (DEVKIT_ROOT / "schemas").rglob("*.json"):
        Draft202012Validator.check_schema(
            json.loads(path.read_text(encoding="utf-8")),
        )

    canonical = PLUGIN_ROOT / "schemas"
    bundled = DEVKIT_ROOT / "schemas" / "super-agent-support-v1"
    for name in (
        "capability-descriptor.schema.json",
        "credential-binding.schema.json",
        "device-message.schema.json",
    ):
        assert (bundled / name).read_bytes() == (canonical / name).read_bytes()


def test_business_identity_offline_verifier_persists_jti_and_blocks_replay(
    tmp_path,
):
    verifier = _business_identity_verifier()
    private_key = Ed25519PrivateKey.generate()
    public = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    jwks = {
        "issuer": "https://dclaw.deepmega.cn/business-identity",
        "keys": [
            {
                "kty": "OKP",
                "crv": "Ed25519",
                "alg": "EdDSA",
                "use": "sig",
                "kid": "key-1",
                "x": base64.urlsafe_b64encode(public)
                .rstrip(b"=")
                .decode("ascii"),
                "status": "active",
            },
        ],
    }
    now = int(time.time())
    assertion, expected = _business_assertion(
        private_key,
        jti="jti-offline-1",
        now=now,
    )
    cache = verifier.SQLiteJtiReplayCache(tmp_path / "replay.sqlite3")
    kwargs = {
        "jwks": jwks,
        "expected_issuer": expected["iss"],
        "expected_audience": expected["aud"],
        "expected_installation_id": expected["installation_id"],
        "expected_release_id": expected["release_id"],
        "expected_agent_id": expected["agent_id"],
        "expected_service_id": expected["service_id"],
        "required_scopes": ["orders.read"],
        "replay_cache": cache,
        "now": now,
    }
    for override in (
        {"expected_agent_id": "agent-2"},
        {"expected_service_id": "service-2"},
        {"required_scopes": ["orders.write"]},
    ):
        with pytest.raises(
            verifier.BusinessIdentityVerificationError,
            match="BUSINESS_IDENTITY.ASSERTION_INVALID",
        ):
            verifier.verify_business_identity_assertion(
                assertion,
                **{**kwargs, **override},
            )
    assert verifier.verify_business_identity_assertion(
        assertion,
        **kwargs,
    )["jti"] == "jti-offline-1"
    with pytest.raises(
        verifier.BusinessIdentityVerificationError,
        match="BUSINESS_IDENTITY.ASSERTION_REPLAYED",
    ):
        verifier.verify_business_identity_assertion(assertion, **kwargs)
    with sqlite3.connect(cache.path) as db:
        retain_until = db.execute(
            "SELECT retain_until FROM business_identity_consumed_jti",
        ).fetchone()[0]
    assert retain_until == expected["exp"] + 30

    concurrent_assertion, expected = _business_assertion(
        private_key,
        jti="jti-offline-2",
        now=now,
    )

    def verify_once():
        try:
            verifier.verify_business_identity_assertion(
                concurrent_assertion,
                **{**kwargs, "replay_cache": cache},
            )
            return "verified"
        except verifier.BusinessIdentityVerificationError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: verify_once(), range(2)))
    assert sorted(results) == [
        "BUSINESS_IDENTITY.ASSERTION_REPLAYED",
        "verified",
    ]
    fixture = json.loads(
        (
            DEVKIT_ROOT
            / "fixtures"
            / "business-identity"
            / "replay-cases.json"
        ).read_text(encoding="utf-8"),
    )
    assert fixture["retention_rule"] == (
        "persist each accepted (issuer,jti) until exp + clock_skew"
    )
