#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone DClaw Super Agent development, validation, and sealing CLI."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import platform
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import sys
import unicodedata
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
import zipfile


DEVKIT_VERSION = "1.9.14"
CRYPTOGRAPHY_VERSION = "46.0.3"
SUPPORTED_PYTHON = ">=3.10,<3.14"
SUPPORTED_PLATFORMS = {
    ("darwin", "arm64"): "macos-arm64",
    ("darwin", "x86_64"): "macos-x86_64",
    ("linux", "aarch64"): "linux-glibc-aarch64",
    ("linux", "x86_64"): "linux-glibc-x86_64",
    ("windows", "amd64"): "windows-x86_64",
    ("windows", "x86_64"): "windows-x86_64",
}
MAX_PACKAGE_BYTES = 200 * 1024 * 1024
MAX_EXPANDED_BYTES = 400 * 1024 * 1024
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_MEMBERS = 4096
MAX_COMPRESSION_RATIO = 200
HOST_CAPABILITIES = {
    "agent.execute",
    "session.context",
    "runtime.trace",
    "runtime.complete",
    "runtime.fail",
}
MANIFEST_FIELDS = {
    "schema_version",
    "agent_id",
    "name",
    "version",
    "agent_type",
    "scope",
    "entrypoint",
    "public_metadata",
    "runtime",
    "package_type",
    "orchestration",
    "platform_contract_versions",
    "capabilities",
    "capability_digest",
    "signer_id",
    "content_digest",
}


class DevKitError(ValueError):
    pass


def _root() -> Path:
    return Path(__file__).resolve().parent


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DevKitError(f"invalid JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise DevKitError(f"JSON root must be an object: {path}")
    return value


def _development_platform() -> str:
    if not ((3, 10) <= sys.version_info[:2] < (3, 14)):
        raise DevKitError(
            f"unsupported Python {platform.python_version()}; "
            f"expected {SUPPORTED_PYTHON}",
        )
    system = platform.system().lower()
    machine = platform.machine().lower()
    platform_id = SUPPORTED_PLATFORMS.get((system, machine))
    if platform_id is None:
        raise DevKitError(
            f"unsupported development platform: {system}-{machine}",
        )
    if system == "linux" and platform.libc_ver()[0].lower() != "glibc":
        raise DevKitError("Linux DevKit wheels require glibc")
    return platform_id


def _verify_wheelhouse() -> int:
    checksum_path = _root() / "CHECKSUMS.sha256"
    wheelhouse = _root() / "wheelhouse"
    try:
        lines = checksum_path.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise DevKitError("missing or invalid CHECKSUMS.sha256") from exc
    expected: dict[str, str] = {}
    for line in lines:
        if not line.strip():
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            raise DevKitError("invalid CHECKSUMS.sha256 entry")
        relative = PurePosixPath(parts[1])
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.parts[:1] != ("wheelhouse",)
            or relative.suffix != ".whl"
        ):
            raise DevKitError("invalid wheelhouse checksum path")
        name = relative.as_posix()
        if name in expected:
            raise DevKitError(f"duplicate wheelhouse checksum: {name}")
        expected[name] = parts[0]
    actual = {
        path.relative_to(_root()).as_posix()
        for path in wheelhouse.glob("*.whl")
        if path.is_file()
    }
    if not expected or actual != set(expected):
        raise DevKitError("wheelhouse contents do not match CHECKSUMS.sha256")
    for name, digest in expected.items():
        if hashlib.sha256((_root() / name).read_bytes()).hexdigest() != digest:
            raise DevKitError(f"wheelhouse checksum mismatch: {name}")
    return len(expected)


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _canonical_json(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _normalize_member_path(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value.replace("\\", "/"))
    path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise DevKitError("unsafe package path")
    return path.as_posix()


def _payload_digest(files: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    normalized: list[tuple[bytes, bytes]] = []
    seen: set[str] = set()
    for raw_path, data in files.items():
        path = _normalize_member_path(raw_path)
        if path in {"manifest.json", "signature.json"}:
            continue
        if path in seen:
            raise DevKitError("duplicate normalized package path")
        seen.add(path)
        normalized.append((path.encode("utf-8"), data))
    for path_bytes, data in sorted(normalized, key=lambda item: item[0]):
        digest.update(struct.pack(">Q", len(path_bytes)))
        digest.update(path_bytes)
        digest.update(struct.pack(">Q", len(data)))
        digest.update(data)
    return f"sha256:{digest.hexdigest()}"


def compute_capability_digest(manifest: dict) -> str:
    declarations = [
        {
            "capability_id": item["capability_id"],
            "contract_version": item["contract_version"],
        }
        for item in manifest.get("capabilities", [])
    ]
    authority = {
        "package_type": manifest.get("package_type"),
        "orchestration": manifest.get("orchestration"),
        "platform_contract_versions": manifest.get(
            "platform_contract_versions",
            {},
        ),
        "capabilities": sorted(
            declarations,
            key=lambda item: item["capability_id"],
        ),
    }
    return f"sha256:{hashlib.sha256(_canonical_json(authority)).hexdigest()}"


def _catalog() -> dict[str, dict]:
    payload = _read_json(_root() / "capability-catalog.json")
    return {item["capability_id"]: item for item in payload["capabilities"]}


def _require_string(
    value: object,
    field: str,
    pattern: str | None = None,
) -> str:
    if not isinstance(value, str) or not value:
        raise DevKitError(f"manifest field is invalid: {field}")
    if pattern and re.fullmatch(pattern, value) is None:
        raise DevKitError(f"manifest field is invalid: {field}")
    return value


def _validate_public_metadata(metadata: object) -> None:
    if metadata is None:
        return
    if not isinstance(metadata, dict) or set(metadata) - {
        "description",
        "icon",
        "tags",
    }:
        raise DevKitError("manifest field is invalid: public_metadata")
    description = metadata.get("description", "")
    icon = metadata.get("icon")
    tags = metadata.get("tags", [])
    valid_description = (
        isinstance(description, str) and len(description) <= 2000
    )
    valid_icon = icon is None or isinstance(icon, str)
    valid_tags = (
        isinstance(tags, list)
        and len(tags) <= 50
        and all(isinstance(tag, str) for tag in tags)
    )
    if not all((valid_description, valid_icon, valid_tags)):
        raise DevKitError("manifest field is invalid: public_metadata")


def _validate_runtime(runtime: object) -> None:
    if runtime is None:
        return
    if not isinstance(runtime, dict) or set(runtime) - {
        "adapter",
        "contract_version",
        "failure_policy",
    }:
        raise DevKitError("manifest field is invalid: runtime")
    _require_string(
        runtime.get("adapter"),
        "runtime.adapter",
        r"[a-z][a-z0-9_]{0,63}",
    )
    _require_string(
        runtime.get("contract_version"),
        "runtime.contract_version",
        r"[1-9][0-9]{0,7}",
    )
    if runtime.get("failure_policy", "fail_closed") != "fail_closed":
        raise DevKitError("manifest field is invalid: runtime.failure_policy")


def _validate_orchestration(orchestration: object) -> dict:
    if not isinstance(orchestration, dict) or set(orchestration) != {
        "capability_id",
        "contract_version",
        "entrypoint",
        "required_host_capabilities",
    }:
        raise DevKitError("manifest orchestration declaration is invalid")
    if (
        orchestration["capability_id"] != "workspace.turn.orchestrate/1"
        or orchestration["contract_version"] != "1"
    ):
        raise DevKitError("manifest orchestration declaration is invalid")
    _require_string(
        orchestration["entrypoint"],
        "orchestration.entrypoint",
        r"[A-Za-z0-9_./-]+\.py:[A-Za-z_][A-Za-z0-9_]*",
    )
    host = orchestration["required_host_capabilities"]
    if (
        not isinstance(host, list)
        or len(host) != len(set(host))
        or set(host) != HOST_CAPABILITIES
    ):
        raise DevKitError("required host capability set is incomplete")
    return orchestration


def _validate_capability_declarations(
    manifest: dict,
    orchestration: dict,
) -> None:
    versions = manifest.get("platform_contract_versions")
    if not isinstance(versions, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in versions.items()
    ):
        raise DevKitError("platform contract versions are invalid")
    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise DevKitError("capability declarations are missing")
    catalog = _catalog()
    declared: dict[str, dict] = {}
    for item in capabilities:
        _add_capability_declaration(item, catalog, declared)
    _validate_capability_dependencies(declared, versions)
    if orchestration["capability_id"] not in declared:
        raise DevKitError("orchestration capability is not declared")
    missing_host = HOST_CAPABILITIES - set(declared)
    if missing_host:
        raise DevKitError(
            f"missing host capability declaration: {sorted(missing_host)[0]}",
        )
    capability_digest = manifest.get("capability_digest")
    if capability_digest != compute_capability_digest(manifest):
        raise DevKitError("capability digest mismatch")


def _add_capability_declaration(
    item: object,
    catalog: dict[str, dict],
    declared: dict[str, dict],
) -> None:
    if not isinstance(item, dict) or set(item) != {
        "capability_id",
        "contract_version",
    }:
        raise DevKitError("invalid capability declaration")
    capability_id = _require_string(
        item.get("capability_id"),
        "capability_id",
        r"[a-z][a-z0-9_.-]*(?:/[1-9][0-9]*)?",
    )
    if capability_id in declared:
        raise DevKitError("duplicate capability declaration")
    definition = catalog.get(capability_id)
    if definition is None:
        raise DevKitError(f"unknown capability: {capability_id}")
    if item.get("contract_version") != definition["contract_version"]:
        raise DevKitError(f"unsupported capability version: {capability_id}")
    declared[capability_id] = definition


def _validate_capability_dependencies(
    declared: dict[str, dict],
    versions: dict,
) -> None:
    for definition in declared.values():
        for dependency in definition["dependencies"]:
            if dependency not in declared:
                raise DevKitError(
                    f"missing capability dependency: {dependency}",
                )
        group = definition["group"]
        if versions.get(group) != "1":
            raise DevKitError(
                f"unsupported platform contract version: {group}",
            )


def validate_manifest(manifest: dict, *, require_content_digest: bool) -> None:
    extra = set(manifest) - MANIFEST_FIELDS
    if extra:
        raise DevKitError(f"unknown manifest field: {sorted(extra)[0]}")
    expected = {
        "schema_version": 3,
        "agent_type": "sealed",
        "scope": "global",
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise DevKitError(f"manifest field is invalid: {key}")
    if manifest.get("package_type") not in {
        "super_expert", "super_expert_public",
    }:
        raise DevKitError("manifest field is invalid: package_type")
    _require_string(
        manifest.get("agent_id"),
        "agent_id",
        r"[A-Za-z0-9_-]{1,128}",
    )
    name = _require_string(manifest.get("name"), "name")
    if len(name) > 200:
        raise DevKitError("manifest field is invalid: name")
    _require_string(
        manifest.get("version"),
        "version",
        r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?",
    )
    entrypoint = _require_string(manifest.get("entrypoint"), "entrypoint")
    if not _normalize_member_path(entrypoint).startswith("agent/"):
        raise DevKitError("entrypoint must be inside agent/")
    _require_string(
        manifest.get("signer_id"),
        "signer_id",
        r"[A-Za-z0-9_.-]{1,128}",
    )
    _validate_public_metadata(manifest.get("public_metadata"))
    _validate_runtime(manifest.get("runtime"))
    orchestration = _validate_orchestration(manifest.get("orchestration"))
    _validate_capability_declarations(manifest, orchestration)
    content_digest = manifest.get("content_digest")
    if require_content_digest:
        if (
            not isinstance(content_digest, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", content_digest) is None
        ):
            raise DevKitError("content digest is invalid")
    elif content_digest is not None:
        raise DevKitError(
            "content_digest must not be present in the source manifest",
        )


def validate_workspace(source: Path, manifest: dict) -> dict:
    try:
        root = source.resolve(strict=True)
    except OSError as exc:
        raise DevKitError("workspace_missing") from exc
    if not root.is_dir():
        raise DevKitError("workspace_missing")
    config_path = root / "agent.json"
    if config_path.is_symlink():
        raise DevKitError("unsafe_agent_config")
    try:
        config_resolved = config_path.resolve(strict=True)
    except OSError as exc:
        raise DevKitError("agent_config_missing") from exc
    if (
        not config_resolved.is_relative_to(root)
        or not config_resolved.is_file()
    ):
        raise DevKitError("unsafe_agent_config")
    config = _read_json(config_resolved)
    if not isinstance(config.get("id"), str) or not isinstance(
        config.get("name"),
        str,
    ):
        raise DevKitError("agent_config_invalid")
    if config["id"] != manifest["agent_id"]:
        raise DevKitError("agent_id_mismatch")
    orchestration = config.get("orchestration")
    if (
        not isinstance(orchestration, dict)
        or orchestration.get("enabled") is not True
    ):
        raise DevKitError("agent orchestration is not enabled")
    if orchestration.get("contract_version", "1") != "1":
        raise DevKitError("agent orchestration contract is unsupported")
    if (
        orchestration.get("entrypoint")
        != manifest["orchestration"]["entrypoint"]
    ):
        raise DevKitError("orchestration entrypoint mismatch")
    required = orchestration.get("required_host_capabilities")
    if (
        not isinstance(required, list)
        or len(required) != len(set(required))
        or set(required) != HOST_CAPABILITIES
    ):
        raise DevKitError("required host capability set is incomplete")
    module_path = orchestration["entrypoint"].split(":", 1)[0]
    runtime_path = (root / module_path).resolve()
    if not runtime_path.is_relative_to(root) or not runtime_path.is_file():
        raise DevKitError("orchestration entrypoint file is missing")
    contract_path = root / "state-contract.json"
    if contract_path.exists() or contract_path.is_symlink():
        if contract_path.is_symlink() or not contract_path.is_file():
            raise DevKitError("state continuity contract is unsafe")
        _validate_state_contract(contract_path.read_bytes())
    return config


def _validate_state_contract(data: bytes) -> None:
    try:
        value = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DevKitError("state continuity contract is invalid") from exc
    placeholder = "{identity_sha256_24}"
    if not isinstance(value, dict) or set(value) != {
        "contract", "format_id", "schema_version", "filename_template",
    }:
        raise DevKitError("state continuity contract is invalid")
    filename = value["filename_template"]
    if (
        value["contract"] != "workspace.state.continuity/1"
        or not isinstance(value["format_id"], str)
        or re.fullmatch(r"[a-z][a-z0-9_.-]{0,127}", value["format_id"]) is None
        or type(value["schema_version"]) is not int
        or value["schema_version"] < 1
        or not isinstance(filename, str)
        or filename.count(placeholder) != 1
        or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,126}\.json",
            filename.replace(placeholder, "x" * 24),
        ) is None
    ):
        raise DevKitError("state continuity contract is invalid")


def _collect_source(source: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for path in source.rglob("*"):
        relative_path = path.relative_to(source)
        if (
            any(part in {"__pycache__", ".git", ".venv"} for part in relative_path.parts)
            or path.suffix == ".pyc"
            or path.name == ".DS_Store"
        ):
            continue
        if path.is_symlink():
            raise DevKitError(f"workspace contains a symlink: {path.name}")
        if path.is_file():
            relative = relative_path.as_posix()
            data = path.read_bytes()
            if len(data) > MAX_FILE_BYTES:
                raise DevKitError(
                    f"workspace file exceeds size limit: {relative}",
                )
            files[f"agent/{relative}"] = data
    if len(files) > MAX_MEMBERS - 2:
        raise DevKitError("workspace contains too many files")
    return files


def _load_private_key(path: Path):
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        raw = base64.b64decode(
            path.read_text(encoding="utf-8").strip(),
            validate=True,
        )
        return Ed25519PrivateKey.from_private_bytes(raw)
    except ImportError as exc:
        raise DevKitError("install requirements.txt before signing") from exc
    except (OSError, ValueError) as exc:
        raise DevKitError("invalid Ed25519 private key") from exc


def _load_public_key(path: Path):
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )

        raw = base64.b64decode(
            path.read_text(encoding="utf-8").strip(),
            validate=True,
        )
        return Ed25519PublicKey.from_public_bytes(raw)
    except ImportError as exc:
        raise DevKitError(
            "install requirements.txt before verification",
        ) from exc
    except (OSError, ValueError) as exc:
        raise DevKitError("invalid Ed25519 public key") from exc


def build_package(
    source: Path,
    manifest_path: Path,
    private_key_path: Path,
) -> bytes:
    manifest = _read_json(manifest_path)
    metadata = manifest.setdefault("public_metadata", {})
    if isinstance(metadata, dict):
        metadata.setdefault("description", "")
        metadata.setdefault("icon", None)
        metadata.setdefault("tags", [])
    manifest.setdefault("runtime", None)
    runtime = manifest.get("runtime")
    if isinstance(runtime, dict):
        runtime.setdefault("failure_policy", "fail_closed")
    manifest["capability_digest"] = compute_capability_digest(manifest)
    validate_workspace(source, manifest)
    files = _collect_source(source)
    manifest["content_digest"] = _payload_digest(files)
    validate_manifest(manifest, require_content_digest=True)
    canonical = _canonical_json(manifest)
    private_key = _load_private_key(private_key_path)
    signature = {
        "signer_id": manifest["signer_id"],
        "algorithm": "ed25519",
        "signature": base64.b64encode(private_key.sign(canonical)).decode(
            "ascii",
        ),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr("manifest.json", canonical)
        for path in sorted(files):
            archive.writestr(path, files[path])
        archive.writestr("signature.json", _canonical_json(signature))
    if output.tell() > MAX_PACKAGE_BYTES:
        raise DevKitError("sealed package exceeds size limit")
    return output.getvalue()


def _read_package_files(data: bytes) -> dict[str, bytes]:
    if len(data) > MAX_PACKAGE_BYTES or not zipfile.is_zipfile(
        io.BytesIO(data),
    ):
        raise DevKitError("invalid sealed package")
    files: dict[str, bytes] = {}
    expanded = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > MAX_MEMBERS:
            raise DevKitError("sealed package contains too many files")
        for info in archive.infolist():
            path = _normalize_member_path(info.filename)
            if path in files:
                raise DevKitError("duplicate normalized package path")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise DevKitError("sealed package contains a symlink")
            if info.file_size > MAX_FILE_BYTES:
                raise DevKitError("sealed package member exceeds size limit")
            if (
                info.compress_size
                and info.file_size > info.compress_size * MAX_COMPRESSION_RATIO
            ):
                raise DevKitError("sealed package compression ratio is unsafe")
            expanded += info.file_size
            if expanded > MAX_EXPANDED_BYTES:
                raise DevKitError("sealed package expands beyond size limit")
            files[path] = archive.read(info)
    return files


def _verify_package_signature(
    manifest: dict,
    signature: dict,
    public_key_path: Path,
) -> None:
    if (
        signature.get("signer_id") != manifest["signer_id"]
        or signature.get("algorithm") != "ed25519"
    ):
        raise DevKitError("sealed package signer mismatch")
    try:
        encoded_signature = base64.b64decode(
            signature.get("signature", ""),
            validate=True,
        )
        _load_public_key(public_key_path).verify(
            encoded_signature,
            _canonical_json(manifest),
        )
    except Exception as exc:
        if isinstance(exc, DevKitError):
            raise
        raise DevKitError("sealed package signature is invalid") from exc


def verify_package(package_path: Path, public_key_path: Path) -> dict:
    files = _read_package_files(package_path.read_bytes())
    if "manifest.json" not in files or "signature.json" not in files:
        raise DevKitError("sealed package metadata is missing")
    try:
        manifest = json.loads(files["manifest.json"])
        signature = json.loads(files["signature.json"])
    except json.JSONDecodeError as exc:
        raise DevKitError("sealed package metadata is invalid") from exc
    if not isinstance(manifest, dict) or not isinstance(signature, dict):
        raise DevKitError("sealed package metadata is invalid")
    validate_manifest(manifest, require_content_digest=True)
    _verify_package_signature(manifest, signature, public_key_path)
    payload = {
        key: value
        for key, value in files.items()
        if key not in {"manifest.json", "signature.json"}
    }
    if manifest["content_digest"] != _payload_digest(payload):
        raise DevKitError("sealed package payload digest mismatch")
    if manifest["entrypoint"] not in payload:
        raise DevKitError("sealed package entrypoint is missing")
    if "agent/state-contract.json" in payload:
        _validate_state_contract(payload["agent/state-contract.json"])
    return manifest


def _json_result(**values: object) -> None:
    print(
        json.dumps(
            values,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dclaw-agent-devkit")
    parser.add_argument("--version", action="version", version=DEVKIT_VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--wheelhouse-only", action="store_true")
    digest = subparsers.add_parser("digest")
    digest.add_argument("--manifest", type=Path, required=True)
    digest.add_argument("--write", action="store_true")
    validate = subparsers.add_parser("validate")
    validate.add_argument("--source", type=Path, required=True)
    validate.add_argument("--manifest", type=Path, required=True)
    keygen = subparsers.add_parser("keygen")
    keygen.add_argument("--private-key", type=Path, required=True)
    keygen.add_argument("--public-key", type=Path, required=True)
    keygen.add_argument("--force", action="store_true")
    build = subparsers.add_parser("build")
    build.add_argument("--source", type=Path, required=True)
    build.add_argument("--manifest", type=Path, required=True)
    build.add_argument("--private-key", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--package", type=Path, required=True)
    verify.add_argument("--public-key", type=Path, required=True)
    subparsers.add_parser("contracts")
    components = subparsers.add_parser("component-registry")
    components.add_argument("--base-url", required=True)
    components.add_argument(
        "--access-token",
        default=os.environ.get("DCLAW_ACCESS_TOKEN", ""),
    )
    component_commands = components.add_subparsers(
        dest="component_command",
        required=True,
    )
    component_commands.add_parser("get")
    register_component = component_commands.add_parser("register")
    register_component.add_argument("--descriptor", type=Path, required=True)
    register_component.add_argument("--signer-id", required=True)
    component_signature = register_component.add_mutually_exclusive_group(
        required=True,
    )
    component_signature.add_argument("--signature-file", type=Path)
    component_signature.add_argument("--private-key", type=Path)
    upload_component = component_commands.add_parser("upload")
    upload_component.add_argument("--file", type=Path, required=True)
    upload_component.add_argument("--component-id", required=True)
    upload_component.add_argument("--platform", required=True)
    upload_component.add_argument("--component-version", required=True)
    publish = subparsers.add_parser("publish")
    publish.add_argument("--base-url", required=True)
    publish.add_argument(
        "--access-token", default=os.environ.get("DCLAW_ACCESS_TOKEN", ""),
    )
    publish_commands = publish.add_subparsers(
        dest="publish_command", required=True,
    )
    register_signer = publish_commands.add_parser("register-signer")
    register_signer.add_argument("--public-key", type=Path, required=True)
    upload_release = publish_commands.add_parser("upload")
    upload_release.add_argument("--package", type=Path, required=True)
    retry_release = publish_commands.add_parser("retry-activation")
    retry_release.add_argument("--agent-id", required=True)
    retry_release.add_argument("--release-id", required=True)
    publish_commands.add_parser("list")
    return parser


def _command_doctor(args: argparse.Namespace) -> None:
    platform_id = _development_platform()
    wheel_count = _verify_wheelhouse()
    cryptography_version = None
    if not args.wheelhouse_only:
        import cryptography

        cryptography_version = cryptography.__version__
        if cryptography_version != CRYPTOGRAPHY_VERSION:
            raise DevKitError(
                "unexpected cryptography version: "
                f"{cryptography_version}; expected {CRYPTOGRAPHY_VERSION}",
            )
    _json_result(
        status="ok",
        devkit_version=DEVKIT_VERSION,
        python=platform.python_version(),
        supported_python=SUPPORTED_PYTHON,
        platform=platform_id,
        wheelhouse_files=wheel_count,
        wheelhouse_verified=True,
        cryptography_version=cryptography_version,
    )


def _command_digest(args: argparse.Namespace) -> None:
    manifest = _read_json(args.manifest)
    digest = compute_capability_digest(manifest)
    if args.write:
        manifest["capability_digest"] = digest
        _write_json(args.manifest, manifest)
    _json_result(
        status="ok",
        capability_digest=digest,
        updated=bool(args.write),
    )


def _command_validate(args: argparse.Namespace) -> None:
    manifest = _read_json(args.manifest)
    validate_manifest(manifest, require_content_digest=False)
    validate_workspace(args.source, manifest)
    _json_result(
        status="valid",
        agent_id=manifest["agent_id"],
        devkit_version=DEVKIT_VERSION,
    )


def _command_keygen(args: argparse.Namespace) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    for path in (args.private_key, args.public_key):
        if path.exists() and not args.force:
            raise DevKitError(f"refusing to overwrite key: {path}")
    private = Ed25519PrivateKey.generate()
    private_raw = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    args.private_key.parent.mkdir(parents=True, exist_ok=True)
    args.public_key.parent.mkdir(parents=True, exist_ok=True)
    args.private_key.write_text(
        base64.b64encode(private_raw).decode("ascii") + "\n",
        encoding="utf-8",
    )
    args.public_key.write_text(
        base64.b64encode(public_raw).decode("ascii") + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(args.private_key, 0o600)
    except OSError:
        pass
    _json_result(
        status="ok",
        private_key=str(args.private_key),
        public_key=str(args.public_key),
    )


def _command_build(args: argparse.Namespace) -> None:
    package = build_package(
        args.source.resolve(),
        args.manifest,
        args.private_key,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(package)
    _json_result(
        status="built",
        output=str(args.output),
        bytes=len(package),
        devkit_version=DEVKIT_VERSION,
    )


def _command_verify(args: argparse.Namespace) -> None:
    manifest = verify_package(args.package, args.public_key)
    _json_result(
        status="valid",
        agent_id=manifest["agent_id"],
        version=manifest["version"],
        signer_id=manifest["signer_id"],
    )


def _command_contracts(_args: argparse.Namespace) -> None:
    catalog = _read_json(_root() / "capability-catalog.json")
    operation_catalog = _root() / "operation-catalog.json"
    transport_fixture = (
        _root()
        / "fixtures"
        / "business-identity"
        / "transport-cases.json"
    )
    component_export_fixture = (
        _root()
        / "fixtures"
        / "public-components"
        / "component-export-cases.json"
    )
    _json_result(
        status="ok",
        devkit_version=DEVKIT_VERSION,
        catalog_version=catalog["catalog_version"],
        dependency_mode="bundled-wheelhouse",
        cryptography_version=CRYPTOGRAPHY_VERSION,
        supported_python=SUPPORTED_PYTHON,
        supported_platforms=sorted(set(SUPPORTED_PLATFORMS.values())),
        operation_catalog=operation_catalog.relative_to(_root()).as_posix(),
        operation_catalog_sha256=hashlib.sha256(
            operation_catalog.read_bytes(),
        ).hexdigest(),
        transport_fixture=transport_fixture.relative_to(_root()).as_posix(),
        transport_fixture_sha256=hashlib.sha256(
            transport_fixture.read_bytes(),
        ).hexdigest(),
        component_export_fixture=(
            component_export_fixture.relative_to(_root()).as_posix()
        ),
        component_export_fixture_sha256=hashlib.sha256(
            component_export_fixture.read_bytes(),
        ).hexdigest(),
        schemas=sorted(
            path.relative_to(_root()).as_posix()
            for path in (_root() / "schemas").rglob("*.json")
        ),
    )


def _component_request(
    method: str,
    url: str,
    *,
    access_token: str,
    body: dict[str, object] | None = None,
    operation_name: str = "Component registry",
) -> dict[str, object]:
    if not access_token:
        raise DevKitError("authenticated DClaw access token is required")
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    encoded = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=encoded, headers=headers, method=method)
    try:
        with urlopen(request, timeout=60) as response:  # nosec B310
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise DevKitError(
            f"{operation_name} returned HTTP {exc.code}: {detail}",
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise DevKitError(f"{operation_name} request failed: {exc}") from exc
    if not isinstance(result, dict):
        raise DevKitError(f"{operation_name} response must be a JSON object")
    return result


def _component_signature(
    args: argparse.Namespace,
    descriptor: dict[str, object],
) -> str:
    if args.signature_file:
        signature = args.signature_file.read_text(encoding="utf-8").strip()
        try:
            base64.b64decode(signature, validate=True)
        except ValueError as exc:
            raise DevKitError("public Component signature file is invalid") from exc
        return signature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric.ec import ECDSA, SECP256R1

    private_key = serialization.load_pem_private_key(
        args.private_key.read_bytes(),
        password=None,
    )
    if not isinstance(private_key.curve, SECP256R1):
        raise DevKitError("public Component key must use P-256")
    canonical = json.dumps(
        descriptor,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.b64encode(
        private_key.sign(canonical, ECDSA(hashes.SHA256())),
    ).decode("ascii")


def _command_component_registry(args: argparse.Namespace) -> None:
    base_url = args.base_url.rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise DevKitError("DClaw base URL must be an absolute HTTPS URL")
    support_endpoint = base_url + "/api/super-agent-support"
    endpoint = support_endpoint + "/component-registry"
    if args.component_command == "get":
        result = _component_request(
            "GET",
            endpoint,
            access_token=args.access_token,
        )
    elif args.component_command == "upload":
        import hashlib

        sha256 = hashlib.sha256()
        md5 = hashlib.md5(usedforsecurity=False)
        size = 0
        with args.file.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                sha256.update(chunk)
                md5.update(chunk)
        if not 1 <= size <= 2_147_483_648:
            raise DevKitError("Component archive size is outside the supported range")
        upload = _component_request(
            "POST",
            support_endpoint + "/admin/component-artifacts/uploads",
            access_token=args.access_token,
            body={
                "component_id": args.component_id,
                "platform": args.platform,
                "component_version": args.component_version,
                "size_bytes": size,
                "sha256": sha256.hexdigest(),
                "md5": md5.hexdigest(),
            },
        )
        target = upload.get("upload")
        if not isinstance(target, dict) or target.get("method") != "PUT":
            raise DevKitError("Component upload response is invalid")
        upload_url = target.get("url")
        if not isinstance(upload_url, str) or urlsplit(upload_url).scheme != "https":
            raise DevKitError("Component upload URL must use HTTPS")
        headers = dict(target.get("headers") or {})
        headers["Content-Length"] = str(size)
        with args.file.open("rb") as source:
            request = Request(upload_url, data=source, headers=headers, method="PUT")
            try:
                with urlopen(request, timeout=3600) as response:  # nosec B310
                    if response.status not in (200, 201, 204):
                        raise DevKitError("Component object upload failed")
            except (HTTPError, URLError, TimeoutError) as exc:
                raise DevKitError(f"Component object upload failed: {exc}") from exc
        upload_id = upload.get("upload_id")
        if not isinstance(upload_id, str):
            raise DevKitError("Component upload ID is missing")
        result = _component_request(
            "POST",
            support_endpoint + "/admin/component-artifacts/uploads/"
            + quote(upload_id, safe="") + "/complete",
            access_token=args.access_token,
        )
    else:
        descriptor = _read_json(args.descriptor)
        component_id = descriptor.get("component_id")
        component_platform = descriptor.get("platform")
        if not isinstance(component_id, str) or not isinstance(
            component_platform,
            str,
        ):
            raise DevKitError("public Component descriptor identity is missing")
        result = _component_request(
            "PUT",
            support_endpoint
            + "/admin/component-registry/"
            + quote(component_id, safe="")
            + "/variants/"
            + quote(component_platform, safe=""),
            access_token=args.access_token,
            body={
                "descriptor": descriptor,
                "signer_id": args.signer_id,
                "signature": _component_signature(args, descriptor),
            },
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def _command_publish(args: argparse.Namespace) -> None:
    base_url = args.base_url.rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise DevKitError("DClaw base URL must be an absolute HTTPS URL")
    if not args.access_token:
        raise DevKitError("DCLAW_ACCESS_TOKEN is required")
    endpoint = base_url + "/api/user/super-expert-publishing"
    if args.publish_command == "register-signer":
        result = _component_request(
            "POST", endpoint + "/signers",
            access_token=args.access_token,
            body={"public_key": args.public_key.read_text(encoding="ascii").strip()},
            operation_name="Super Expert publishing",
        )
    elif args.publish_command == "list":
        result = _component_request(
            "GET", endpoint + "/agents", access_token=args.access_token,
            operation_name="Super Expert publishing",
        )
    elif args.publish_command == "retry-activation":
        result = _component_request(
            "POST",
            endpoint + "/agents/" + quote(args.agent_id, safe="")
            + "/releases/" + quote(args.release_id, safe="") + "/activate",
            access_token=args.access_token,
            operation_name="Super Expert publishing",
        )
    else:
        package = args.package.read_bytes()
        if not 1 <= len(package) <= MAX_PACKAGE_BYTES:
            raise DevKitError("sealed package size is outside the supported range")
        boundary = "dclaw-" + uuid.uuid4().hex
        prefix = (
            f"--{boundary}\r\n"
            "Content-Disposition: form-data; name=\"file\"; "
            "filename=\"agent.zip\"\r\n"
            "Content-Type: application/zip\r\n\r\n"
        ).encode("ascii")
        suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
        request = Request(
            endpoint + "/releases",
            data=prefix + package + suffix,
            headers={
                "Authorization": f"Bearer {args.access_token}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=3600) as response:  # nosec B310
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise DevKitError(
                f"Super Expert upload returned HTTP {exc.code}: {detail}",
            ) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise DevKitError("Super Expert upload request failed") from exc
        if not isinstance(result, dict):
            raise DevKitError("Super Expert upload response is invalid")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


COMMANDS = {
    "doctor": _command_doctor,
    "digest": _command_digest,
    "validate": _command_validate,
    "keygen": _command_keygen,
    "build": _command_build,
    "verify": _command_verify,
    "contracts": _command_contracts,
    "component-registry": _command_component_registry,
    "publish": _command_publish,
}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        COMMANDS[args.command](args)
    except (
        DevKitError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
        ImportError,
    ) as exc:
        _json_result(status="invalid", error=str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
