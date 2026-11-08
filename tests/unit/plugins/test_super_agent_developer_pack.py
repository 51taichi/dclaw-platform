# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import venv
import zipfile

import pytest
from jsonschema import Draft202012Validator


ROOT = Path(__file__).parents[3]
PLUGIN_ROOT = ROOT / "plugins" / "bundle" / "super-agent-support"
PACK_ROOT = PLUGIN_ROOT / "developer_pack"
PACK_CLI = PACK_ROOT / "dclaw_developer.py"
PLAYBOOK_NAME = "super-agent-development-standard-v1.zh-CN.md"


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
    assert metadata["version"] == "1.10.14"
    assert metadata["standard"] == {
        "id": "dclaw.super-agent-development",
        "version": "2.38",
    }
    assert metadata["devkit_version"] == "1.9.7"
    assert metadata["server_source_required"] is False
    assert metadata["sha256"] == hashlib.sha256(first).hexdigest()

    prefix = "dclaw-super-agent-developer-pack-1.10.14/"
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
        "devkit/operation-catalog.json",
        "devkit/fixtures/business-identity/transport-cases.json",
        "schemas/business-mcp-v1/request.schema.json",
        "schemas/developer-pack-v1/capability-build.schema.json",
        "schemas/developer-pack-v1/resources-lock.schema.json",
        "schemas/developer-pack-v1/project.schema.json",
        "sdk/python/dclaw_local_capability.py",
        "templates/project/agent/runtime.py",
        "templates/project/business-service/server.py",
        "templates/project/capability-pack/windows-x64/runner.py",
        "templates/project/capability-pack/windows-x64/capability-build.json",
        "examples/minimal-local/example.json",
    }
    assert {prefix + name for name in expected} <= names
    assert manifest["version"] == "1.10.14"
    assert "devkit/wheelhouse/cryptography-46.0.3" in checksums
    assert not any(
        "src/qwenpaw" in name
        or "tests/unit" in name
        or "/._" in name
        or "/__MACOSX/" in name
        or name.endswith("/.DS_Store")
        for name in names
    )
    for path in list(PACK_ROOT.rglob("*.py")) + list(
        (PLUGIN_ROOT / "devkit").rglob("*.py"),
    ):
        source = path.read_text(encoding="utf-8")
        assert "import qwenpaw" not in source
        assert "from qwenpaw" not in source

    for schema_path in list((PACK_ROOT / "schemas").rglob("*.json")) + list(
        (PACK_ROOT / "templates" / "project").rglob("*.schema.json"),
    ):
        Draft202012Validator.check_schema(
            json.loads(schema_path.read_text(encoding="utf-8")),
        )


def test_developer_pack_archive_rejects_platform_metadata(tmp_path):
    archive = _module("developer_pack_archive_metadata", PACK_ROOT / "archive.py")
    ordinary = tmp_path / "README.md"
    ordinary.write_text("ok", encoding="utf-8")
    apple_double = tmp_path / "._README.md"
    apple_double.write_bytes(b"metadata")
    finder = tmp_path / ".DS_Store"
    finder.write_bytes(b"metadata")
    bytecode = tmp_path / "module.pyc"
    bytecode.write_bytes(b"metadata")
    macos = tmp_path / "__MACOSX" / "file"
    macos.parent.mkdir()
    macos.write_bytes(b"metadata")

    assert archive._is_publishable_file(ordinary)
    for path in (apple_double, finder, bytecode, macos):
        assert not archive._is_publishable_file(path)


def test_developer_pack_prefers_plugin_embedded_standard(tmp_path):
    archive = _module("developer_pack_embedded_standard", PACK_ROOT / "archive.py")
    repository = tmp_path / "repository"
    plugin_root = repository / "plugins" / "bundle" / "support"
    embedded = plugin_root / "developer_pack" / "standard" / PLAYBOOK_NAME
    image_standard = repository / "docs" / PLAYBOOK_NAME
    embedded.parent.mkdir(parents=True)
    image_standard.parent.mkdir(parents=True)
    (plugin_root / "devkit").mkdir(parents=True)
    embedded.write_text("当前版本：`2.12`\n", encoding="utf-8")
    image_standard.write_text("当前版本：`2.11`\n", encoding="utf-8")

    files = archive._files(plugin_root)

    assert files[f"standard/{PLAYBOOK_NAME}"] == embedded.read_bytes()


def test_upgrade_updates_devkit_version_and_immediately_validates(tmp_path):
    cli = _module("developer_pack_upgrade_test", PACK_CLI)
    project = tmp_path / "agent"
    cli.initialize_project(project, "test-agent", "Test Agent", "none")
    _make_release_ready(cli, project)
    metadata_path = project / "project.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["developer_pack_version"] = "1.5.1"
    metadata["standard"]["version"] = "2.8"
    metadata["devkit_version"] = "1.4.0"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    result = cli.upgrade_project(project, accept_standard=False)

    upgraded = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert upgraded["developer_pack_version"] == "1.10.14"
    assert upgraded["standard"]["version"] == "2.38"
    assert upgraded["devkit_version"] == "1.9.7"
    assert result["previous"]["devkit_version"] == "1.4.0"
    assert result["current"]["devkit_version"] == "1.9.7"
    assert cli.release_gate(project)["status"] == "valid"


def test_validate_rejects_stale_project_devkit_version(tmp_path):
    cli = _module("developer_pack_stale_devkit_test", PACK_CLI)
    project = tmp_path / "agent"
    cli.initialize_project(project, "test-agent", "Test Agent", "none")
    _make_release_ready(cli, project)
    metadata_path = project / "project.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["devkit_version"] = "1.4.0"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(cli.DeveloperPackError, match="DevKit version"):
        cli.release_gate(project)


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
            encoding="utf-8",
        ),
    )
    descriptor_schema = json.loads(
        (
            PLUGIN_ROOT / "schemas" / "capability-descriptor.schema.json"
        ).read_text(encoding="utf-8"),
    )
    assert not list(
        Draft202012Validator(descriptor_schema).iter_errors(
            registration["descriptor"],
        ),
    )


def test_release_gate_rejects_placeholder_and_missing_behavior_evidence(
    tmp_path,
):
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
                    },
                ],
            },
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
            },
        ),
        encoding="utf-8",
    )
    with pytest.raises(cli.DeveloperPackError, match="unapproved behavior"):
        cli.release_gate(project)


def _make_release_ready(cli, project: Path) -> None:
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
                        "expected_steps": ["execute"],
                        "expected_outcome": {"ok": True},
                        "evidence": ["tests"],
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    (project / "docs" / "PORTING_RECORD.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "test",
                "differences": [],
                "pending": [],
            },
        ),
        encoding="utf-8",
    )


def _release_ready_resource_lock() -> dict:
    return {
        "schema_version": 1,
        "status": "release-ready",
        "release_ready": True,
        "allowed_domains": ["downloads.deepmega.cn"],
        "resources": [
            {
                "resource_id": "runtime",
                "version": "1.0.0",
                "url": "https://downloads.deepmega.cn/resources/runtime.zip",
                "size_bytes": 1024,
                "sha256": "a" * 64,
                "unpacked_size_bytes": 2048,
                "target_path": "resources/runtime/1.0.0",
                "sbom_url": (
                    "https://downloads.deepmega.cn/resources/runtime.spdx.json"
                ),
                "sbom_sha256": "b" * 64,
                "license_spdx": "Apache-2.0",
                "license_evidence_url": (
                    "https://downloads.deepmega.cn/resources/runtime-license.txt"
                ),
                "license_evidence_sha256": "c" * 64,
                "cache_key": "runtime:1.0.0:sha256:" + "a" * 64,
                "rollback_version": "0.9.0",
                "status": "ready",
            },
        ],
    }


def _write_resource_lock(project: Path, value: dict) -> None:
    path = (
        project
        / "capability-pack"
        / "windows-x64"
        / "resources.lock.json"
    )
    path.write_text(json.dumps(value), encoding="utf-8")


def test_release_gate_rejects_unready_or_unhosted_resources(tmp_path):
    cli = _module("developer_pack_resource_failure_test", PACK_CLI)
    project = tmp_path / "agent"
    cli.initialize_project(project, "test-agent", "Test Agent", "required")
    _make_release_ready(cli, project)
    lock = _release_ready_resource_lock()
    lock["status"] = "release-blocked"
    lock["release_ready"] = False
    lock["resources"][0]["url"] = None
    lock["resources"][0]["license"] = {
        "spdx_id": "pending",
        "url": "https://developer.example.test/license.txt",
        "sha256": "c" * 64,
    }
    _write_resource_lock(project, lock)

    with pytest.raises(cli.DeveloperPackError, match="release-ready"):
        cli.release_gate(project)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda item: item.__setitem__("url", None), "URL is missing"),
        (
            lambda item: item.__setitem__(
                "url",
                "https://developer.example.test/runtime.zip",
            ),
            "non-production host",
        ),
        (
            lambda item: item.__setitem__(
                "url",
                "https://localhost/runtime.zip",
            ),
            "non-production host",
        ),
        (
            lambda item: item.__setitem__(
                "url",
                "https://downloads.deepmega.cn/tmp/runtime.zip",
            ),
            "temporary path",
        ),
        (lambda item: item.__setitem__("size_bytes", 0), "size is invalid"),
        (lambda item: item.pop("sbom_url"), "SBOM URL is missing"),
        (
            lambda item: item.__setitem__("license_spdx", "pending"),
            "license identifier is not release-ready",
        ),
        (
            lambda item: item.pop("target_path"),
            "target path must be a safe POSIX relative path",
        ),
        (lambda item: item.pop("cache_key"), "cache key is missing"),
        (
            lambda item: item.pop("rollback_version"),
            "rollback version is missing",
        ),
    ],
)
def test_release_gate_rejects_incomplete_resource_metadata(
    tmp_path,
    mutation,
    message,
):
    cli = _module("developer_pack_resource_metadata_test", PACK_CLI)
    project = tmp_path / "agent"
    cli.initialize_project(project, "test-agent", "Test Agent", "required")
    _make_release_ready(cli, project)
    lock = _release_ready_resource_lock()
    mutation(lock["resources"][0])
    _write_resource_lock(project, lock)

    with pytest.raises(cli.DeveloperPackError, match=message):
        cli.release_gate(project)


def test_release_gate_accepts_complete_resource_metadata(tmp_path):
    cli = _module("developer_pack_resource_success_test", PACK_CLI)
    project = tmp_path / "agent"
    cli.initialize_project(project, "test-agent", "Test Agent", "required")
    _make_release_ready(cli, project)
    _write_resource_lock(project, _release_ready_resource_lock())

    result = cli.release_gate(project)

    assert result["status"] == "valid"
    assert result["resources"] == 1


def test_secret_scan_ignores_generated_roots_but_scans_sources(tmp_path):
    cli = _module("developer_pack_secret_scan_scope_test", PACK_CLI)
    project = tmp_path / "agent"
    for name in (
        ".release-evidence",
        "release-evidence",
        "release",
        "releases",
        "artifacts",
        "build",
    ):
        generated = project / name / "target" / "capability-build"
        generated.mkdir(parents=True)
        generated.joinpath("vendored.py").write_text(
            'api_key = "0123456789abcdef"\n',
            encoding="utf-8",
        )

    assert cli._scan_secrets(project) == 0

    source = project / "agent" / "runtime.py"
    source.parent.mkdir()
    source.write_text('api_key = "0123456789abcdef"\n', encoding="utf-8")

    with pytest.raises(cli.DeveloperPackError, match="embedded secret"):
        cli._scan_secrets(project)


def test_secret_scan_allows_public_pem_but_rejects_private_pem(tmp_path):
    cli = _module("developer_pack_pem_scan_test", PACK_CLI)
    project = tmp_path / "agent"
    capability = project / "capability-pack" / "windows-x64"
    capability.mkdir(parents=True)
    capability.joinpath("runtime-release-public.pem").write_text(
        "-----BEGIN PUBLIC KEY-----\nZmFrZS1wdWJsaWMta2V5\n"
        "-----END PUBLIC KEY-----\n",
        encoding="ascii",
    )

    assert cli._scan_secrets(project) == 1

    capability.joinpath("embedded-private.pem").write_text(
        "-----BEGIN ENCRYPTED PRIVATE KEY-----\nZmFrZS1wcml2YXRlLWtleQ==\n"
        "-----END ENCRYPTED PRIVATE KEY-----\n",
        encoding="ascii",
    )

    with pytest.raises(cli.DeveloperPackError, match="embedded secret"):
        cli._scan_secrets(project)


def test_build_fails_before_writing_artifacts_when_resources_are_blocked(tmp_path):
    cli = _module("developer_pack_resource_build_order_test", PACK_CLI)
    project = tmp_path / "agent"
    cli.initialize_project(project, "test-agent", "Test Agent", "required")
    _make_release_ready(cli, project)
    lock = _release_ready_resource_lock()
    lock["release_ready"] = False
    _write_resource_lock(project, lock)
    private_key = tmp_path / "private.b64"
    public_key = tmp_path / "public.b64"
    cli._devkit_command(
        "keygen",
        "--private-key",
        str(private_key),
        "--public-key",
        str(public_key),
    )
    output = tmp_path / "release" / "agent.zip"

    with pytest.raises(cli.DeveloperPackError, match="release-ready"):
        cli.build_project(
            project,
            private_key,
            public_key,
            output,
            "https://downloads.deepmega.cn/capabilities/agent.zip",
        )

    assert not output.exists()
    assert not (
        project / "capability-pack" / "windows-x64" / "artifact.zip"
    ).exists()


def test_direct_capability_build_rejects_non_production_artifact_url(tmp_path):
    cli = _module("developer_pack_direct_resource_gate_test", PACK_CLI)
    project = tmp_path / "agent"
    cli.initialize_project(project, "test-agent", "Test Agent", "required")
    _make_release_ready(cli, project)
    private_key = tmp_path / "private.b64"
    public_key = tmp_path / "public.b64"
    cli._devkit_command(
        "keygen",
        "--private-key",
        str(private_key),
        "--public-key",
        str(public_key),
    )

    with pytest.raises(cli.DeveloperPackError, match="non-production host"):
        cli.build_local_capability(
            project,
            "https://developer.example.test/capability.zip",
            private_key,
        )

    assert not (
        project / "capability-pack" / "windows-x64" / "artifact.zip"
    ).exists()


def test_capability_build_manifest_packages_arbitrary_resources_deterministically(
    tmp_path,
):
    cli = _module("developer_pack_capability_members_test", PACK_CLI)
    project = tmp_path / "agent"
    cli.initialize_project(project, "test-agent", "Test Agent", "required")
    _make_release_ready(cli, project)
    root = project / "capability-pack" / "windows-x64"
    (root / "modules").mkdir()
    (root / "modules" / "worker.py").write_text(
        "VALUE = 1\n",
        encoding="utf-8",
    )
    (root / "runtime").mkdir()
    (root / "runtime" / "ffmpeg.exe").write_bytes(b"ffmpeg-test")
    build_manifest = json.loads(
        (root / "capability-build.json").read_text(encoding="utf-8"),
    )
    build_manifest["artifact"]["members"].extend(["modules", "runtime"])
    (root / "capability-build.json").write_text(
        json.dumps(build_manifest),
        encoding="utf-8",
    )
    private_key = tmp_path / "private.b64"
    public_key = tmp_path / "public.b64"
    cli._devkit_command(
        "keygen",
        "--private-key",
        str(private_key),
        "--public-key",
        str(public_key),
    )

    first = cli.build_local_capability(
        project,
        "https://downloads.deepmega.cn/capability.zip",
        private_key,
    )
    second = cli.build_local_capability(
        project,
        "https://downloads.deepmega.cn/capability.zip",
        private_key,
    )

    assert first["artifact_mode"] == "members"
    assert first["artifact_files"] == 6
    assert first["artifact_sha256"] == second["artifact_sha256"]
    with zipfile.ZipFile(root / "artifact.zip") as archive:
        names = set(archive.namelist())
        inventory = json.loads(archive.read("DCLAW-CAPABILITY-MANIFEST.json"))
    assert "modules/worker.py" in names
    assert "runtime/ffmpeg.exe" in names
    assert len(inventory["files"]) == 6
    assert all(item["sha256"] for item in inventory["files"])


def test_capability_build_imports_prebuilt_zip_and_rejects_unsafe_paths(
    tmp_path,
):
    cli = _module("developer_pack_prebuilt_test", PACK_CLI)
    project = tmp_path / "agent"
    cli.initialize_project(project, "test-agent", "Test Agent", "required")
    _make_release_ready(cli, project)
    private_key = tmp_path / "private.b64"
    public_key = tmp_path / "public.b64"
    cli._devkit_command(
        "keygen",
        "--private-key",
        str(private_key),
        "--public-key",
        str(public_key),
    )
    prebuilt = tmp_path / "prebuilt.zip"
    with zipfile.ZipFile(prebuilt, "w") as archive:
        archive.writestr("app/main.py", "print('ok')\n")
        archive.writestr("runtime/python.exe", b"python-test")
    expected = hashlib.sha256(prebuilt.read_bytes()).hexdigest()

    result = cli.build_local_capability(
        project,
        "https://downloads.deepmega.cn/prebuilt.zip",
        private_key,
        prebuilt,
    )

    assert result["artifact_mode"] == "prebuilt"
    assert result["artifact_files"] == 2
    assert result["artifact_sha256"] == expected

    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../escape.py", "bad")
    with pytest.raises(
        cli.DeveloperPackError,
        match="safe POSIX relative path",
    ):
        cli.build_local_capability(
            project,
            "https://downloads.deepmega.cn/unsafe.zip",
            private_key,
            unsafe,
        )


def test_pytest_adapter_records_actual_test_count_and_command(tmp_path):
    cli = _module("developer_pack_pytest_adapter_test", PACK_CLI)
    project = tmp_path / "agent"
    cli.initialize_project(project, "test-agent", "Test Agent", "none")
    _make_release_ready(cli, project)
    metadata_path = project / "project.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["tests"] = {
        "adapter": "pytest",
        "paths": ["tests"],
        "arguments": ["-q"],
    }
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    (project / "tests" / "test_more.py").write_text(
        "def test_one():\n    assert True\n\ndef test_two():\n    assert True\n",
        encoding="utf-8",
    )

    result = cli.run_tests(project)

    assert result["test_status"] == "passed"
    assert result["test_adapter"] == "pytest"
    assert result["tests"] == 3
    assert result["test_commands"][0][0] == "<python>"
    assert "--junitxml=<evidence.xml>" in result["test_commands"][0]


def test_project_virtual_environment_python_is_validated(tmp_path):
    cli = _module("developer_pack_venv_test", PACK_CLI)
    project = tmp_path / "agent"
    cli.initialize_project(project, "test-agent", "Test Agent", "none")
    environment = project / ".venv"
    venv.EnvBuilder(
        with_pip=False,
        symlinks=sys.platform != "win32",
    ).create(environment)
    relative = (
        ".venv/Scripts/python.exe"
        if sys.platform == "win32"
        else ".venv/bin/python"
    )
    metadata = {"tests": {"adapter": "unittest", "paths": ["tests"], "python": relative}}

    _adapter, executable, _paths, _arguments = cli._test_configuration(
        project,
        metadata,
    )

    assert Path(executable) == project / relative


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX venv contract")
def test_project_test_python_rejects_symlink_directory_and_wrapper(tmp_path):
    cli = _module("developer_pack_venv_rejection_test", PACK_CLI)
    project = tmp_path / "agent"
    cli.initialize_project(project, "test-agent", "Test Agent", "none")
    outside = tmp_path / "outside"
    venv.EnvBuilder(
        with_pip=False,
        symlinks=sys.platform != "win32",
    ).create(outside)
    (project / ".venv").symlink_to(outside, target_is_directory=True)
    linked = ".venv/bin/python"
    with pytest.raises(cli.DeveloperPackError, match="symbolic-link directory"):
        cli._test_configuration(
            project,
            {"tests": {"adapter": "unittest", "paths": ["tests"], "python": linked}},
        )

    wrapper_project = tmp_path / "wrapper-agent"
    cli.initialize_project(
        wrapper_project,
        "wrapper-agent",
        "Wrapper Agent",
        "none",
    )
    fake = wrapper_project / ".venv" / "bin"
    fake.mkdir(parents=True)
    (wrapper_project / ".venv" / "pyvenv.cfg").write_text(
        f"home = {Path(sys.executable).resolve().parent}\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / "python-wrapper"
    wrapper.write_text("#!/bin/sh\necho not-python\n", encoding="utf-8")
    wrapper.chmod(0o755)
    (fake / "python").symlink_to(wrapper)
    with pytest.raises(cli.DeveloperPackError, match="native Python executable"):
        cli._test_configuration(
            wrapper_project,
            {
                "tests": {
                    "adapter": "unittest",
                    "paths": ["tests"],
                    "python": ".venv/bin/python",
                },
            },
        )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX venv contract")
def test_project_test_python_rejects_nonstandard_and_project_escape(tmp_path):
    cli = _module("developer_pack_venv_escape_test", PACK_CLI)
    project = tmp_path / "agent"
    cli.initialize_project(project, "test-agent", "Test Agent", "none")
    with pytest.raises(cli.DeveloperPackError, match="must be .venv/bin/python"):
        cli._test_configuration(
            project,
            {
                "tests": {
                    "adapter": "unittest",
                    "paths": ["tests"],
                    "python": "venv/bin/python",
                },
            },
        )

    controlled = project / "controlled-python"
    controlled.write_bytes(Path(sys.executable).resolve().read_bytes())
    controlled.chmod(0o755)
    (project / ".venv" / "bin").mkdir(parents=True)
    (project / ".venv" / "bin" / "python").symlink_to(controlled)
    (project / ".venv" / "pyvenv.cfg").write_text(
        f"home = {controlled.parent}\nversion_info = 3.10\n",
        encoding="utf-8",
    )
    with pytest.raises(cli.DeveloperPackError, match="writable project target"):
        cli._test_configuration(
            project,
            {
                "tests": {
                    "adapter": "unittest",
                    "paths": ["tests"],
                    "python": ".venv/bin/python",
                },
            },
        )
