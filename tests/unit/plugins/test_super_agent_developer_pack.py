from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[3]
PLUGIN_ROOT = ROOT / "plugins" / "bundle" / "super-agent-support"
PACK_ROOT = PLUGIN_ROOT / "developer_pack"
PACK_CLI = PACK_ROOT / "dclaw_developer.py"


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_developer_pack_archive_is_complete_and_reproducible():
    archive = _module("developer_pack_archive_test", PACK_ROOT / "archive.py")
    first, metadata = archive.build_archive(PLUGIN_ROOT)
    second, repeated = archive.build_archive(PLUGIN_ROOT)
    assert first == second
    assert metadata == repeated
    assert metadata["version"] == "1.0.0"
    assert metadata["standard"] == {
        "id": "dclaw.super-agent-development",
        "version": "2.1",
    }
    assert metadata["devkit_version"] == "1.2.0"
    assert metadata["server_source_required"] is False
    assert metadata["sha256"] == hashlib.sha256(first).hexdigest()

    prefix = "dclaw-super-agent-developer-pack-1.0.0/"
    with zipfile.ZipFile(io.BytesIO(first)) as package:
        names = set(package.namelist())
        manifest = json.loads(package.read(prefix + "PACKAGE-MANIFEST.json"))
        checksums = package.read(prefix + "SHA256SUMS").decode("ascii")
    expected = {
        "README.md",
        "COMPATIBILITY.md",
        "UPGRADE.md",
        "SBOM.spdx.json",
        "dclaw_developer.py",
        "standard/super-agent-development-standard-v1.zh-CN.md",
        "devkit/dclaw_agent_devkit.py",
        "schemas/business-mcp-v1/request.schema.json",
        "sdk/python/dclaw_local_capability.py",
        "templates/project/agent/runtime.py",
        "templates/project/business-service/server.py",
        "templates/project/capability-pack/windows-x64/runner.py",
        "examples/minimal-local/example.json",
    }
    assert {prefix + name for name in expected} <= names
    assert manifest["version"] == "1.0.0"
    assert "devkit/wheelhouse/cryptography-46.0.3" in checksums
    assert not any("src/qwenpaw" in name or "tests/unit" in name for name in names)
    for path in list(PACK_ROOT.rglob("*.py")) + list(
        (PLUGIN_ROOT / "devkit").rglob("*.py")
    ):
        source = path.read_text(encoding="utf-8")
        assert "import qwenpaw" not in source
        assert "from qwenpaw" not in source

    for schema_path in list((PACK_ROOT / "schemas").rglob("*.json")) + list(
        (PACK_ROOT / "templates" / "project").rglob("*.schema.json")
    ):
        Draft202012Validator.check_schema(
            json.loads(schema_path.read_text(encoding="utf-8"))
        )


def test_doctor_and_offline_demo_build_a_verified_package(tmp_path):
    doctor = subprocess.run(
        [sys.executable, str(PACK_CLI), "doctor"],
        check=True,
        capture_output=True,
        text=True,
    )
    doctor_result = json.loads(doctor.stdout)
    assert doctor_result["status"] == "ok"
    assert doctor_result["wheelhouse"]["wheelhouse_files"] == 26

    workspace = tmp_path / "demo"
    completed = subprocess.run(
        [
            sys.executable,
            str(PACK_CLI),
            "demo",
            "--workspace",
            str(workspace),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["status"] == "sealed"
    assert result["verify"]["status"] == "valid"
    assert result["gate"]["behavior_cases"] == 1
    assert result["gate"]["local_helper"] == "required"
    assert result["local_capability"]["status"] == "succeeded"
    assert result["capability_verify"]["status"] == "valid"
    assert Path(result["package"]).is_file()
    assert Path(result["evidence"]).is_file()
    registration = json.loads(
        (workspace / "capability-pack" / "registration.json").read_text(
            encoding="utf-8"
        )
    )
    descriptor_schema = json.loads(
        (
            PLUGIN_ROOT
            / "schemas"
            / "capability-descriptor.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert not list(
        Draft202012Validator(descriptor_schema).iter_errors(
            registration["descriptor"]
        )
    )


def test_release_gate_rejects_placeholder_and_missing_behavior_evidence(tmp_path):
    cli = _module("developer_pack_cli_test", PACK_CLI)
    project = tmp_path / "agent"
    cli.initialize_project(project, "test-agent", "Test Agent", "none")
    with pytest.raises(cli.DeveloperPackError, match="signer_id"):
        cli.release_gate(project)

    manifest_path = project / "manifest.template.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["signer_id"] = "approved-test-signer"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(cli.DeveloperPackError, match="behavior baseline"):
        cli.release_gate(project)


def test_release_gate_rejects_unapproved_behavior_difference(tmp_path):
    cli = _module("developer_pack_cli_difference_test", PACK_CLI)
    project = tmp_path / "agent"
    cli.initialize_project(project, "test-agent", "Test Agent", "none")
    manifest_path = project / "manifest.template.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["signer_id"] = "approved-test-signer"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (project / "docs" / "SOURCE_BEHAVIOR_SPEC.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "verified",
                "cases": [
                    {
                        "id": "case-1",
                        "input": {},
                        "expected_steps": ["step"],
                        "expected_outcome": {"ok": True},
                        "evidence": ["source:test"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (project / "docs" / "PORTING_RECORD.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "example",
                "differences": [{"id": "diff-1", "approved": False}],
                "pending": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(cli.DeveloperPackError, match="unapproved behavior"):
        cli.release_gate(project)
