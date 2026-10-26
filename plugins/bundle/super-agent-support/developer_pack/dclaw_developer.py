#!/usr/bin/env python3
"""Offline project workflow for the DClaw Super Agent developer pack."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile


PACK_VERSION = "1.0.0"
STANDARD_ID = "dclaw.super-agent-development"
STANDARD_VERSION = "2.1"
DEVKIT_VERSION = "1.2.0"
PROJECT_SCHEMA_VERSION = 1
LOCAL_SESSION = "local.execution.session/1"
LOCAL_PREFLIGHT = "local.environment.preflight/1"
SECRET_FILE_NAMES = {".env", ".env.local", "id_rsa", "id_ed25519"}
SECRET_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
        r"\s*[:=]\s*['\"]?(?!\$\{|<|replace|change_me|example|test)"
        r"[A-Za-z0-9+/=_-]{16,}"
    ),
)


class DeveloperPackError(ValueError):
    """A deterministic developer-facing validation failure."""


def _root() -> Path:
    return Path(__file__).resolve().parent


def _devkit_root() -> Path:
    candidates = (_root() / "devkit", _root().parent / "devkit")
    for candidate in candidates:
        if (candidate / "dclaw_agent_devkit.py").is_file():
            return candidate
    raise DeveloperPackError("bundled DevKit is missing")


def _standard_path() -> Path:
    candidates = (
        _root() / "standard" / "super-agent-development-standard-v1.zh-CN.md",
        _root().parents[3]
        / "docs"
        / "super-agent-development-standard-v1.zh-CN.md",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise DeveloperPackError("development standard is missing")


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DeveloperPackError(f"invalid JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise DeveloperPackError(f"JSON root must be an object: {path}")
    return value


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _json_result(**values: object) -> None:
    print(json.dumps(values, ensure_ascii=False, sort_keys=True))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _devkit():
    path = _devkit_root() / "dclaw_agent_devkit.py"
    spec = importlib.util.spec_from_file_location("dclaw_embedded_devkit", path)
    if spec is None or spec.loader is None:
        raise DeveloperPackError("cannot load bundled DevKit")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.DEVKIT_VERSION != DEVKIT_VERSION:
        raise DeveloperPackError("bundled DevKit version mismatch")
    return module


def _run(args: list[str], *, cwd: Path | None = None) -> dict:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        detail = completed.stdout.strip() or completed.stderr.strip()
        raise DeveloperPackError(
            f"command failed ({completed.returncode}): {' '.join(args)}: {detail}"
        )
    output = completed.stdout.strip()
    if not output:
        return {"status": "ok"}
    try:
        value = json.loads(output.splitlines()[-1])
    except json.JSONDecodeError:
        return {"status": "ok", "output": output}
    return value if isinstance(value, dict) else {"status": "ok"}


def _standard_version() -> str:
    text = _standard_path().read_text(encoding="utf-8")
    match = re.search(r"^当前版本：`([^`]+)`", text, re.MULTILINE)
    if not match:
        raise DeveloperPackError("standard version marker is missing")
    return match.group(1)


def _project_paths(project: Path) -> tuple[Path, Path]:
    project = project.resolve()
    return project / "project.json", project / "manifest.template.json"


def _project(project: Path) -> tuple[Path, dict, Path, dict]:
    project = project.resolve()
    project_path, manifest_path = _project_paths(project)
    return project, _read_json(project_path), manifest_path, _read_json(manifest_path)


def _capability_ids(manifest: dict) -> list[str]:
    values = manifest.get("capabilities")
    if not isinstance(values, list):
        raise DeveloperPackError("manifest capabilities must be a list")
    try:
        return [str(item["capability_id"]) for item in values]
    except (KeyError, TypeError) as exc:
        raise DeveloperPackError("manifest capability declaration is invalid") from exc


def _validate_evidence(project: Path) -> dict:
    baseline = _read_json(project / "docs" / "SOURCE_BEHAVIOR_SPEC.json")
    differences = _read_json(project / "docs" / "PORTING_RECORD.json")
    cases = baseline.get("cases")
    if baseline.get("status") != "verified" or not isinstance(cases, list) or not cases:
        raise DeveloperPackError("behavior baseline is missing or not verified")
    required = {"id", "input", "expected_steps", "expected_outcome", "evidence"}
    for case in cases:
        if not isinstance(case, dict) or not required.issubset(case):
            raise DeveloperPackError("behavior baseline case is incomplete")
        if not case["expected_steps"] or not case["evidence"]:
            raise DeveloperPackError("behavior baseline case lacks steps or evidence")
    items = differences.get("differences")
    if not isinstance(items, list):
        raise DeveloperPackError("behavior differences list is missing")
    for item in items:
        if not isinstance(item, dict) or item.get("approved") is not True:
            raise DeveloperPackError("unapproved behavior difference blocks release")
        if not str(item.get("approval_reference", "")).strip():
            raise DeveloperPackError("behavior difference approval reference is missing")
    if differences.get("pending"):
        raise DeveloperPackError("pending behavior differences block release")
    return {"behavior_cases": len(cases), "approved_differences": len(items)}


def _scan_secrets(project: Path) -> int:
    scanned = 0
    ignored = {".git", ".venv", "release", "release-evidence", "__pycache__"}
    for path in sorted(project.rglob("*")):
        if not path.is_file() or any(part in ignored for part in path.parts):
            continue
        if path.name in SECRET_FILE_NAMES or path.suffix.lower() in SECRET_SUFFIXES:
            raise DeveloperPackError(f"secret-like file blocks release: {path}")
        if path.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        scanned += 1
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                raise DeveloperPackError(f"possible embedded secret blocks release: {path}")
    return scanned


def _validate_dependencies(project: Path, mode: str) -> int:
    lock = _read_json(project / "capability-pack" / "dependencies.lock.json")
    dependencies = lock.get("dependencies")
    if not isinstance(dependencies, list):
        raise DeveloperPackError("local dependency lock is invalid")
    for item in dependencies:
        if not isinstance(item, dict):
            raise DeveloperPackError("local dependency entry is invalid")
        required = {"id", "version", "sha256", "license"}
        if not required.issubset(item):
            raise DeveloperPackError("local dependency entry is incomplete")
        if not re.fullmatch(r"[0-9a-f]{64}", str(item["sha256"])):
            raise DeveloperPackError("local dependency SHA-256 is invalid")
    if mode != "none":
        for relative in (
            "capability-pack/windows-x64/runner.py",
            "capability-pack/windows-x64/input.schema.json",
            "capability-pack/windows-x64/result.schema.json",
            "capability-pack/windows-x64/checkpoint.schema.json",
            "capability-pack/windows-x64/descriptor.template.json",
        ):
            if not (project / relative).is_file():
                raise DeveloperPackError(f"required local capability file is missing: {relative}")
    return len(dependencies)


def _materialize_descriptor(project: Path) -> None:
    root = project / "capability-pack" / "windows-x64"
    descriptor_path = root / "descriptor.template.json"
    descriptor = _read_json(descriptor_path)
    for name in ("input", "result", "checkpoint"):
        schema_path = root / f"{name}.schema.json"
        schema = _read_json(schema_path)
        descriptor["schemas"][name] = {
            "path": schema_path.name,
            "sha256": _sha256(schema_path),
            "document": schema,
        }
    _write_json(descriptor_path, descriptor)


def _validate_local_schemas(project: Path, mode: str) -> int:
    root = project / "capability-pack" / "windows-x64"
    descriptor = _read_json(root / "descriptor.template.json")
    if mode == "none":
        return 0
    required = {
        "descriptor_version",
        "contract_version",
        "capability_id",
        "package_id",
        "package_version",
        "artifact",
        "entrypoint",
        "schemas",
        "permissions",
        "limits",
        "semantics",
    }
    if not required.issubset(descriptor):
        raise DeveloperPackError("local capability descriptor is incomplete")
    if descriptor.get("implementation_status") != "release":
        raise DeveloperPackError("local capability descriptor is not a release")
    artifact_path = root / "artifact.zip"
    artifact = descriptor.get("artifact")
    if not artifact_path.is_file() or not isinstance(artifact, dict):
        raise DeveloperPackError("signed local capability artifact is missing")
    if (
        artifact.get("sha256") != _sha256(artifact_path)
        or artifact.get("size_bytes") != artifact_path.stat().st_size
        or not str(artifact.get("url", "")).startswith("https://")
        or str(artifact.get("url", "")).endswith(".invalid/")
        or ".invalid/" in str(artifact.get("url", ""))
    ):
        raise DeveloperPackError("local capability artifact metadata is incomplete")
    schemas = descriptor.get("schemas")
    if not isinstance(schemas, dict):
        raise DeveloperPackError("local capability schemas are missing")
    for name in ("input", "result", "checkpoint"):
        entry = schemas.get(name)
        if not isinstance(entry, dict):
            raise DeveloperPackError(f"local {name} schema declaration is missing")
        path = root / str(entry.get("path", ""))
        document = _read_json(path)
        if entry.get("sha256") != _sha256(path) or entry.get("document") != document:
            raise DeveloperPackError(f"local {name} schema digest or document mismatch")
        if (
            document.get("type") != "object"
            or document.get("additionalProperties") is not False
        ):
            raise DeveloperPackError(f"local {name} schema must be a closed object")
    registration_path = project / "capability-pack" / "registration.json"
    registration = _read_json(registration_path)
    if registration.get("descriptor") != descriptor:
        raise DeveloperPackError("signed local capability descriptor is stale")
    manifest = _read_json(project / "manifest.template.json")
    if (
        registration.get("signer_id") != manifest.get("signer_id")
        or not registration.get("signature")
    ):
        raise DeveloperPackError("local capability signature is missing")
    return 3


def build_local_capability(
    project_path: Path,
    artifact_url: str,
    private_key_path: Path,
) -> dict:
    project, _metadata, _manifest_path, manifest = _project(project_path)
    if not re.fullmatch(r"https://[^\s]+", artifact_url):
        raise DeveloperPackError("capability artifact URL must use HTTPS")
    root = project / "capability-pack" / "windows-x64"
    _materialize_descriptor(project)
    artifact_path = root / "artifact.zip"
    members = (
        "runner.py",
        "input.schema.json",
        "result.schema.json",
        "checkpoint.schema.json",
    )
    with zipfile.ZipFile(
        artifact_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for name in members:
            source = root / name
            if not source.is_file():
                raise DeveloperPackError(f"local capability source is missing: {name}")
            info = zipfile.ZipInfo(name, (2026, 10, 26, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes())
    descriptor_path = root / "descriptor.template.json"
    descriptor = _read_json(descriptor_path)
    descriptor["artifact"] = {
        "url": artifact_url,
        "sha256": _sha256(artifact_path),
        "size_bytes": artifact_path.stat().st_size,
    }
    _write_json(descriptor_path, descriptor)
    devkit = _devkit()
    signature = base64.b64encode(
        devkit._load_private_key(private_key_path.resolve()).sign(
            devkit._canonical_json(descriptor)
        )
    ).decode("ascii")
    registration = {
        "descriptor": descriptor,
        "signer_id": manifest["signer_id"],
        "signature": signature,
    }
    registration_path = project / "capability-pack" / "registration.json"
    _write_json(registration_path, registration)
    return {
        "status": "built",
        "artifact": str(artifact_path),
        "artifact_sha256": descriptor["artifact"]["sha256"],
        "registration": str(registration_path),
        "signer_id": manifest["signer_id"],
    }


def verify_local_capability(project_path: Path, public_key_path: Path) -> dict:
    project, metadata, _manifest_path, _manifest = _project(project_path)
    if metadata.get("local_helper") == "none":
        return {"status": "not-required"}
    registration = _read_json(project / "capability-pack" / "registration.json")
    descriptor = registration["descriptor"]
    try:
        signature = base64.b64decode(registration["signature"], validate=True)
        _devkit()._load_public_key(public_key_path.resolve()).verify(
            signature,
            _devkit()._canonical_json(descriptor),
        )
    except Exception as exc:
        raise DeveloperPackError("local capability signature is invalid") from exc
    return {
        "status": "valid",
        "capability_id": descriptor["capability_id"],
        "package_version": descriptor["package_version"],
        "signer_id": registration["signer_id"],
    }


def release_gate(project_path: Path) -> dict:
    project, metadata, manifest_path, manifest = _project(project_path)
    if metadata.get("schema_version") != PROJECT_SCHEMA_VERSION:
        raise DeveloperPackError("project schema version is unsupported")
    if metadata.get("standard") != {
        "id": STANDARD_ID,
        "version": STANDARD_VERSION,
    }:
        raise DeveloperPackError("project has not adopted the current standard")
    if metadata.get("developer_pack_version") != PACK_VERSION:
        raise DeveloperPackError("project developer pack version is not current")
    if _standard_version() != STANDARD_VERSION:
        raise DeveloperPackError("developer pack and standard versions do not match")
    declared = _capability_ids(manifest)
    expected = metadata.get("declared_platform_capabilities")
    if declared != expected:
        raise DeveloperPackError("manifest capability declarations exceed project record")
    if len(declared) != len(set(declared)):
        raise DeveloperPackError("manifest contains duplicate capabilities")
    if str(manifest.get("signer_id", "")).startswith("replace-"):
        raise DeveloperPackError("approved signer_id is not configured")
    mode = metadata.get("local_helper")
    if mode not in {"none", "optional", "required"}:
        raise DeveloperPackError("local_helper must be none, optional, or required")
    local = {item for item in declared if item.startswith("local.")}
    expected_local = {
        "none": set(),
        "optional": {LOCAL_SESSION},
        "required": {LOCAL_SESSION, LOCAL_PREFLIGHT},
    }[mode]
    if local != expected_local:
        raise DeveloperPackError("local helper declaration does not match capability set")
    devkit = _devkit()
    manifest["capability_digest"] = devkit.compute_capability_digest(manifest)
    devkit.validate_manifest(manifest, require_content_digest=False)
    devkit.validate_workspace(project / "agent", manifest)
    evidence = _validate_evidence(project)
    dependencies = _validate_dependencies(project, mode)
    schemas = _validate_local_schemas(project, mode)
    scanned = _scan_secrets(project)
    return {
        "status": "valid",
        "project": str(project),
        "agent_id": manifest["agent_id"],
        "version": manifest["version"],
        "local_helper": mode,
        "capabilities": len(declared),
        "dependencies": dependencies,
        "local_schemas": schemas,
        "secret_scan_files": scanned,
        **evidence,
    }


def run_tests(project_path: Path) -> dict:
    gate = release_gate(project_path)
    project = project_path.resolve()
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise DeveloperPackError(
            "project tests failed: " + (completed.stderr or completed.stdout).strip()
        )
    count = len(re.findall(r"^test_.*\.\.\. ok$", completed.stderr, re.MULTILINE))
    if count < 1:
        raise DeveloperPackError("project test suite did not execute any tests")
    return {**gate, "tests": count, "test_status": "passed"}


def _replace_tree(root: Path, replacements: dict[str, str]) -> None:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix in {".png", ".zip"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        for source, target in replacements.items():
            text = text.replace(source, target)
        path.write_text(text, encoding="utf-8")


def initialize_project(target: Path, agent_id: str, name: str, mode: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", agent_id):
        raise DeveloperPackError("agent_id is invalid")
    if target.exists():
        raise DeveloperPackError(f"target already exists: {target}")
    template = _root() / "templates" / "project"
    shutil.copytree(template, target)
    _replace_tree(target, {"{{AGENT_ID}}": agent_id, "{{AGENT_NAME}}": name})
    metadata = _read_json(target / "project.json")
    manifest = _read_json(target / "manifest.template.json")
    capabilities = manifest["capabilities"]
    if mode in {"optional", "required"}:
        capabilities.append(
            {"capability_id": LOCAL_SESSION, "contract_version": "1"}
        )
        manifest["platform_contract_versions"]["local_execution"] = "1"
    if mode == "required":
        capabilities.append(
            {"capability_id": LOCAL_PREFLIGHT, "contract_version": "1"}
        )
    metadata["local_helper"] = mode
    metadata["declared_platform_capabilities"] = [
        item["capability_id"] for item in capabilities
    ]
    manifest["capability_digest"] = _devkit().compute_capability_digest(manifest)
    _write_json(target / "project.json", metadata)
    _write_json(target / "manifest.template.json", manifest)
    _materialize_descriptor(target)
    _write_json(
        target / ".dclaw" / "developer-pack.json",
        {
            "developer_pack_version": PACK_VERSION,
            "standard_version": STANDARD_VERSION,
            "devkit_version": DEVKIT_VERSION,
        },
    )
    return {"status": "initialized", "project": str(target.resolve()), "local_helper": mode}


def _devkit_command(*args: str) -> dict:
    return _run([sys.executable, str(_devkit_root() / "dclaw_agent_devkit.py"), *args])


def build_project(
    project_path: Path,
    private_key: Path,
    public_key: Path,
    output: Path,
    capability_artifact_url: str | None = None,
) -> dict:
    project_metadata = _read_json(project_path.resolve() / "project.json")
    capability_build = None
    if project_metadata.get("local_helper") != "none":
        if not capability_artifact_url:
            raise DeveloperPackError(
                "--capability-artifact-url is required for local helper releases"
            )
        capability_build = build_local_capability(
            project_path,
            capability_artifact_url,
            private_key,
        )
    test_result = run_tests(project_path)
    project, _metadata, manifest_path, manifest = _project(project_path)
    _devkit_command("digest", "--manifest", str(manifest_path), "--write")
    validation = _devkit_command(
        "validate", "--source", str(project / "agent"), "--manifest", str(manifest_path)
    )
    build = _devkit_command(
        "build",
        "--source",
        str(project / "agent"),
        "--manifest",
        str(manifest_path),
        "--private-key",
        str(private_key.resolve()),
        "--output",
        str(output.resolve()),
    )
    verification = _devkit_command(
        "verify",
        "--package",
        str(output.resolve()),
        "--public-key",
        str(public_key.resolve()),
    )
    capability_verification = verify_local_capability(project, public_key)
    package_sha256 = _sha256(output.resolve())
    checksum = output.with_suffix(output.suffix + ".sha256")
    checksum.write_text(f"{package_sha256}  {output.name}\n", encoding="ascii")
    evidence = {
        "status": "sealed",
        "developer_pack_version": PACK_VERSION,
        "standard_version": STANDARD_VERSION,
        "devkit_version": DEVKIT_VERSION,
        "agent_id": manifest["agent_id"],
        "agent_version": manifest["version"],
        "package": str(output.resolve()),
        "package_sha256": package_sha256,
        "checksum": str(checksum.resolve()),
        "gate": test_result,
        "validate": validation,
        "build": build,
        "verify": verification,
        "capability_build": capability_build,
        "capability_verify": capability_verification,
        "states": {
            "source_complete": True,
            "sealed": True,
            "uploaded": False,
            "granted": False,
            "active": False,
            "e2e_verified": False,
        },
    }
    evidence_path = project / "release-evidence" / f"{manifest['version']}.json"
    _write_json(evidence_path, evidence)
    evidence["evidence"] = str(evidence_path)
    return evidence


def upgrade_project(project_path: Path, accept_standard: bool) -> dict:
    project, metadata, _manifest_path, _manifest = _project(project_path)
    current_standard = str(metadata.get("standard", {}).get("version", "0"))
    current_major = current_standard.split(".", 1)[0]
    target_major = STANDARD_VERSION.split(".", 1)[0]
    if current_major != target_major and not accept_standard:
        raise DeveloperPackError(
            "major standard upgrade requires --accept-standard after reviewing UPGRADE.md"
        )
    previous = {
        "developer_pack_version": metadata.get("developer_pack_version"),
        "standard_version": current_standard,
    }
    metadata["developer_pack_version"] = PACK_VERSION
    metadata["standard"] = {"id": STANDARD_ID, "version": STANDARD_VERSION}
    _write_json(project / "project.json", metadata)
    record = {
        "previous": previous,
        "current": {
            "developer_pack_version": PACK_VERSION,
            "standard_version": STANDARD_VERSION,
            "devkit_version": DEVKIT_VERSION,
        },
        "business_source_modified": False,
        "rollback": "restore project.json and use the previous developer pack ZIP",
    }
    _write_json(project / ".dclaw" / "developer-pack.json", record)
    return {"status": "upgraded", "project": str(project), **record}


def demo(workspace: Path) -> dict:
    workspace = workspace.resolve()
    if workspace.exists():
        raise DeveloperPackError(f"demo workspace already exists: {workspace}")
    initialize_project(
        workspace,
        "example-local-agent",
        "Example Local Agent",
        "required",
    )
    manifest = _read_json(workspace / "manifest.template.json")
    manifest["signer_id"] = "example-test-signer"
    _write_json(workspace / "manifest.template.json", manifest)
    _write_json(
        workspace / "docs" / "SOURCE_BEHAVIOR_SPEC.json",
        {
            "schema_version": 1,
            "status": "verified",
            "cases": [
                {
                    "id": "uppercase-local-output",
                    "input": {"text": "dclaw local capability"},
                    "expected_steps": [
                        "Agent accepts the request",
                        "local capability writes the transformed output",
                        "Agent accepts the technical result",
                    ],
                    "expected_outcome": {"output_text": "DCLAW LOCAL CAPABILITY"},
                    "evidence": ["tests/test_runtime.py", "offline demo result.txt"],
                }
            ],
        },
    )
    _write_json(
        workspace / "docs" / "PORTING_RECORD.json",
        {
            "schema_version": 1,
            "source": "from-scratch developer-pack example",
            "differences": [],
            "pending": [],
        },
    )
    keys = workspace / ".demo-keys"
    private_key = keys / "private.b64"
    public_key = keys / "public.b64"
    _devkit_command(
        "keygen",
        "--private-key",
        str(private_key),
        "--public-key",
        str(public_key),
    )
    capability = _run(
        [sys.executable, "capability-pack/windows-x64/runner.py"], cwd=workspace
    )
    output = workspace / "release" / "example-local-agent-0.1.0.zip"
    result = build_project(
        workspace,
        private_key,
        public_key,
        output,
        "https://developer.example.test/capabilities/example-local-agent-0.1.0.zip",
    )
    result["local_capability"] = capability
    result["demo_workspace"] = str(workspace)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dclaw-developer")
    parser.add_argument("--version", action="version", version=PACK_VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("info")
    init = commands.add_parser("init")
    init.add_argument("--target", type=Path, required=True)
    init.add_argument("--agent-id", required=True)
    init.add_argument("--name", required=True)
    init.add_argument(
        "--local-helper", choices=("none", "optional", "required"), default="none"
    )
    validate = commands.add_parser("validate")
    validate.add_argument("--project", type=Path, required=True)
    test = commands.add_parser("test")
    test.add_argument("--project", type=Path, required=True)
    keygen = commands.add_parser("keygen")
    keygen.add_argument("--private-key", type=Path, required=True)
    keygen.add_argument("--public-key", type=Path, required=True)
    build = commands.add_parser("build")
    build.add_argument("--project", type=Path, required=True)
    build.add_argument("--private-key", type=Path, required=True)
    build.add_argument("--public-key", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--capability-artifact-url")
    capability = commands.add_parser("capability-build")
    capability.add_argument("--project", type=Path, required=True)
    capability.add_argument("--private-key", type=Path, required=True)
    capability.add_argument("--artifact-url", required=True)
    upgrade = commands.add_parser("upgrade")
    upgrade.add_argument("--project", type=Path, required=True)
    upgrade.add_argument("--accept-standard", action="store_true")
    demo_parser = commands.add_parser("demo")
    demo_parser.add_argument("--workspace", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "doctor":
            wheelhouse = _devkit_command("doctor", "--wheelhouse-only")
            contracts = _devkit_command("contracts")
            result = {
                "status": "ok",
                "developer_pack_version": PACK_VERSION,
                "standard_version": _standard_version(),
                "devkit": contracts,
                "wheelhouse": wheelhouse,
                "server_source_required": False,
            }
        elif args.command == "info":
            result = {
                "status": "ok",
                "developer_pack_version": PACK_VERSION,
                "standard": {"id": STANDARD_ID, "version": _standard_version()},
                "devkit_version": DEVKIT_VERSION,
            }
        elif args.command == "init":
            result = initialize_project(
                args.target, args.agent_id, args.name, args.local_helper
            )
        elif args.command == "validate":
            result = release_gate(args.project)
        elif args.command == "test":
            result = run_tests(args.project)
        elif args.command == "keygen":
            result = _devkit_command(
                "keygen",
                "--private-key",
                str(args.private_key),
                "--public-key",
                str(args.public_key),
            )
        elif args.command == "build":
            result = build_project(
                args.project,
                args.private_key,
                args.public_key,
                args.output,
                args.capability_artifact_url,
            )
        elif args.command == "capability-build":
            result = build_local_capability(
                args.project, args.artifact_url, args.private_key
            )
        elif args.command == "upgrade":
            result = upgrade_project(args.project, args.accept_standard)
        else:
            result = demo(args.workspace)
        _json_result(**result)
        return 0
    except (
        DeveloperPackError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
        ImportError,
    ) as exc:
        _json_result(status="invalid", error=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
