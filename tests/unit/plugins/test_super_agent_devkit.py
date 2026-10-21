from __future__ import annotations

import base64
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

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
    assert result["devkit_version"] == "1.0.0"
    assert "schemas/super-expert-manifest.schema.json" in result["schemas"]
    assert (
        "schemas/local-execution-v1/tool-call.schema.json" in result["schemas"]
    )


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
        if item["capability_id"] != "local.execution.session/1"
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
