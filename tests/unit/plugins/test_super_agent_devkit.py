# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import zipfile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator, ValidationError

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


def test_publish_upload_uses_authenticated_https_multipart(
    tmp_path, monkeypatch, capsys,
):
    module = _devkit()
    archive = tmp_path / "agent.zip"
    archive.write_bytes(b"signed package")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"release_id":"release-1","state":"active"}'

    def upload(request, timeout):
        assert timeout == 3600
        assert request.full_url == (
            "https://dclaw.example.test/api/user/"
            "super-expert-publishing/releases"
        )
        assert request.get_method() == "POST"
        assert request.get_header("Authorization") == "Bearer test-token"
        assert request.get_header("Content-type").startswith(
            "multipart/form-data; boundary=dclaw-"
        )
        assert b"signed package" in request.data
        assert b'name="file"' in request.data
        return Response()

    monkeypatch.setattr(module, "urlopen", upload)
    args = argparse.Namespace(
        base_url="https://dclaw.example.test", access_token="test-token",
        publish_command="upload", package=archive,
    )
    module._command_publish(args)
    assert json.loads(capsys.readouterr().out)["release_id"] == "release-1"

    args.base_url = "http://dclaw.example.test"
    with pytest.raises(module.DevKitError, match="HTTPS"):
        module._command_publish(args)


def test_component_registry_upload_streams_to_object_storage(
    tmp_path, monkeypatch, capsys,
):
    module = _devkit()
    archive = tmp_path / "component.zip"
    archive.write_bytes(b"component archive")
    calls = []

    def component_request(method, url, *, access_token, body=None):
        calls.append((method, url, body))
        if url.endswith("/uploads"):
            assert body["size_bytes"] == archive.stat().st_size
            assert body["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
            return {
                "upload_id": "a" * 32,
                "upload": {
                    "method": "PUT",
                    "url": "https://objects.example.test/component.zip?signature=secret",
                    "headers": {"Content-Type": "application/zip", "Content-MD5": "x"},
                },
            }
        return {"status": "verified", "artifact_url": "https://objects.example.test/component.zip"}

    class UploadResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    def upload(request, timeout):
        assert request.get_method() == "PUT"
        assert request.headers["Content-length"] == str(archive.stat().st_size)
        assert request.data.read() == archive.read_bytes()
        return UploadResponse()

    monkeypatch.setattr(module, "_component_request", component_request)
    monkeypatch.setattr(module, "urlopen", upload)
    module._command_component_registry(argparse.Namespace(
        base_url="https://dclaw.example.test", access_token="test-token",
        component_command="upload", file=archive, component_id="ffmpeg",
        platform="windows-x64", component_version="7.1",
    ))
    assert [call[0] for call in calls] == ["POST", "POST"]
    assert calls[1][1].endswith("/" + "a" * 32 + "/complete")
    assert json.loads(capsys.readouterr().out)["status"] == "verified"


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
    assert result["devkit_version"] == "1.9.3"
    assert result["dependency_mode"] == "bundled-wheelhouse"
    assert result["cryptography_version"] == "46.0.3"
    assert "schemas/super-expert-manifest.schema.json" in result["schemas"]
    assert (
        "schemas/local-execution-v1/tool-call.schema.json" in result["schemas"]
    )
    assert (
        "schemas/super-agent-support-v1/public-component-descriptor.schema.json"
        in result["schemas"]
    )
    assert result["operation_catalog"] == "operation-catalog.json"
    assert len(result["operation_catalog_sha256"]) == 64
    assert result["transport_fixture"] == (
        "fixtures/business-identity/transport-cases.json"
    )
    assert len(result["transport_fixture_sha256"]) == 64
    assert result["component_export_fixture"] == (
        "fixtures/public-components/component-export-cases.json"
    )
    assert len(result["component_export_fixture_sha256"]) == 64


def test_component_export_contract_fixture_and_schema():
    schema = json.loads(
        (
            DEVKIT_ROOT
            / "schemas"
            / "super-agent-support-v1"
            / "capability-descriptor.schema.json"
        ).read_text(encoding="utf-8"),
    )
    fixture = json.loads(
        (
            DEVKIT_ROOT
            / "fixtures"
            / "public-components"
            / "component-export-cases.json"
        ).read_text(encoding="utf-8"),
    )
    Draft202012Validator.check_schema(schema)
    export_schema = dict(schema["properties"]["component_exports"])
    export_schema["$defs"] = schema["$defs"]
    validator = Draft202012Validator(export_schema)
    validator.validate(fixture["positive"][0]["component_exports"])
    with pytest.raises(ValidationError):
        validator.validate(
            fixture["negative"][1]["component_exports"],
        )


def test_business_identity_operation_catalog_is_complete_and_consistent():
    catalog = json.loads(
        (DEVKIT_ROOT / "operation-catalog.json").read_text(encoding="utf-8"),
    )
    fixture = json.loads(
        (
            DEVKIT_ROOT
            / "fixtures"
            / "business-identity"
            / "transport-cases.json"
        ).read_text(encoding="utf-8"),
    )

    assert catalog["owner"] == "dclaw.super-agent-support"
    assert catalog["minimum_plugin_version"] == "1.17.0"
    gateway = catalog["local_capability_gateway"]
    assert gateway == {
        "owner": "dclaw-platform",
        "endpoint_path": "/api/super-agent-support/mcp/",
        "transport": "streamable-http",
        "jsonrpc_version": "2.0",
        "session_mode": "stateless",
        "mcp_session_id_required": False,
        "agent_raw_jsonrpc_allowed": False,
        "host_sequence": [
            "initialize",
            "notifications/initialized",
            "tools/list",
            "tools/call",
        ],
        "request_headers": {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    }
    assert catalog["platform_injected_arguments"] == ["dclaw_session_token"]

    operations = {item["client_key"]: item for item in catalog["operations"]}
    assert set(operations) == {
        "business_identity.issue",
        "business_identity.outbound",
        "agent_outbound.request",
        "agent_outbound.stream",
        "resource.upload.create",
        "resource.upload.complete",
        "resource.read",
        "resource.revoke",
    }
    assert operations["business_identity.issue"]["tool_name"] == (
        "business_service_identity_issue"
    )
    assert operations["business_identity.issue"]["must_precede"] == (
        "business_identity.outbound"
    )
    assert operations["business_identity.outbound"]["tool_name"] == (
        "business_service_outbound_request"
    )
    assert operations["business_identity.outbound"]["requires_binding_from"] == (
        "business_identity.issue"
    )
    assert operations["agent_outbound.request"]["tool_name"] == (
        "agent_outbound_request"
    )
    assert operations["agent_outbound.request"]["capability_id"] == (
        "agent.outbound/1"
    )
    assert operations["agent_outbound.stream"]["capability_id"] == (
        "agent.outbound.stream/1"
    )
    assert operations["resource.upload.create"]["output_schema"].endswith(
        "upload-create-response.schema.json"
    )
    assert operations["resource.revoke"]["tool_name"] == (
        "agent_resource_revoke"
    )

    for operation in operations.values():
        for key in ("input_schema", "output_schema"):
            assert (DEVKIT_ROOT / operation[key]).is_file()

    upload_target_schema = json.loads(
        (
            DEVKIT_ROOT
            / operations["resource.upload.create"]["output_schema"]
        ).read_text(encoding="utf-8"),
    )
    upload_target = {
        "resource_ref": "res_" + "a" * 32,
        "status": "pending",
        "mime_type": "image/jpeg",
        "max_size_bytes": 1024,
        "expires_at": 1,
        "upload": {
            "url": "https://objects.example/upload",
            "method": "PUT",
            "headers": {"Content-Type": "image/jpeg"},
            "allowed_domains": ["objects.example"],
            "max_size_bytes": 1024,
        },
    }
    Draft202012Validator(upload_target_schema).validate(upload_target)
    with pytest.raises(ValidationError):
        Draft202012Validator(upload_target_schema).validate(
            {
                **upload_target,
                "upload": {
                    **upload_target["upload"],
                    "url": "http://objects.example/upload",
                },
            },
        )
    with pytest.raises(ValidationError):
        Draft202012Validator(upload_target_schema).validate(
            {**upload_target, "upload": {**upload_target["upload"], "Authorization": "forbidden"}},
        )
    assert (DEVKIT_ROOT / catalog["stable_error_schema"]).is_file()

    outbound_schema = json.loads(
        (DEVKIT_ROOT / operations["business_identity.outbound"]["input_schema"])
        .read_text(encoding="utf-8"),
    )
    transport = outbound_schema["x-dclaw-transport"]
    controlled = catalog["controlled_outbound"]
    assert transport["agent_authorization_header"] == "forbidden"
    assert controlled["agent_authorization_allowed"] is False
    assert transport["platform_authorization_header"] == "Authorization"
    assert transport["platform_authorization_cardinality"] == 1
    assert controlled["authorization_cardinality"] == 1
    assert transport["request_body"] == (
        "zero-or-one-of-json_body-or-text_body"
    )
    assert controlled["request_body"] == transport["request_body"]
    assert fixture["positive"] and fixture["negative"]

    validator = Draft202012Validator(outbound_schema)
    base = {
        "binding_ref": "bir_" + "a" * 32,
        "method": "POST",
        "url": "https://service.example/v1/resource",
    }
    validator.validate(base)
    validator.validate({**base, "json_body": {}})
    validator.validate({**base, "text_body": ""})
    with pytest.raises(ValidationError):
        validator.validate({**base, "json_body": {}, "text_body": ""})


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
    assert result["devkit_version"] == "1.9.3"
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
        if item["group"] not in {
            "local_execution",
            "business_identity",
            "agent_outbound",
            "resource_exchange",
        }
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


def test_devkit_signs_and_validates_state_continuity_contract(tmp_path):
    devkit = _devkit()
    _, private_path, public_path = _key_files(tmp_path)
    source = tmp_path / "agent"
    shutil.copytree(FIXTURE / "agent", source)
    contract = {
        "contract": "workspace.state.continuity/1",
        "format_id": "generic.v1",
        "schema_version": 1,
        "filename_template": "work-{identity_sha256_24}.json",
    }
    descriptor = source / "state-contract.json"
    descriptor.write_text(json.dumps(contract), encoding="utf-8")
    package = devkit.build_package(
        source, FIXTURE / "manifest.template.json", private_path,
    )
    archive = tmp_path / "release.zip"
    archive.write_bytes(package)
    assert devkit.verify_package(archive, public_path)["agent_id"] == "generic-orchestration"
    with zipfile.ZipFile(io.BytesIO(package)) as sealed:
        assert json.loads(sealed.read("agent/state-contract.json")) == contract
    contract["filename_template"] = "../unsafe.json"
    descriptor.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(devkit.DevKitError, match="state continuity contract is invalid"):
        devkit.build_package(
            source, FIXTURE / "manifest.template.json", private_path,
        )


def test_devkit_excludes_mutable_python_caches_from_signed_payload(tmp_path):
    devkit = _devkit()
    source = tmp_path / "agent"
    source.mkdir()
    (source / "runtime.py").write_text("pass\n", encoding="utf-8")
    cache = source / "__pycache__"
    cache.mkdir()
    (cache / "runtime.cpython-311.pyc").write_bytes(b"compiled")
    (source / "other.pyc").write_bytes(b"compiled")

    assert devkit._collect_source(source) == {"agent/runtime.py": b"pass\n"}


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


def test_business_identity_transport_rejects_ambiguous_authorization():
    verifier = _business_identity_verifier()
    assertion = "header.payload.signature"
    assert verifier.extract_bearer_assertion(
        [f"Bearer {assertion}"],
    ) == assertion
    for values in (
        [],
        [f"Bearer {assertion}", f"Bearer {assertion}"],
        [f"Bearer {assertion}, Bearer {assertion}"],
        ["Basic abc"],
        ["Bearer "],
    ):
        with pytest.raises(
            verifier.BusinessIdentityVerificationError,
            match="BUSINESS_IDENTITY.ASSERTION_INVALID",
        ):
            verifier.extract_bearer_assertion(values)

    fixture = json.loads(
        (
            DEVKIT_ROOT
            / "fixtures"
            / "business-identity"
            / "transport-cases.json"
        ).read_text(encoding="utf-8"),
    )
    assert {case["name"] for case in fixture["positive"]} >= {
        "platform-single-bearer-and-no-body",
    }
    assert {case["name"] for case in fixture["negative"]} >= {
        "missing-authorization",
        "duplicate-authorization",
        "combined-multi-value",
        "non-bearer",
        "empty-bearer",
    }
