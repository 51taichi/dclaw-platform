#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline project workflow for the DClaw Super Agent developer pack."""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
import zipfile
import xml.etree.ElementTree as ET


PACK_VERSION = "1.6.0"
STANDARD_ID = "dclaw.super-agent-development"
STANDARD_VERSION = "2.12"
DEVKIT_VERSION = "1.5.0"
PROJECT_SCHEMA_VERSION = 1
LOCAL_SESSION = "local.execution.session/1"
LOCAL_PREFLIGHT = "local.environment.preflight/1"
SECRET_FILE_NAMES = {".env", ".env.local", "id_rsa", "id_ed25519"}
SECRET_SUFFIXES = {".key", ".p12", ".pfx"}
SECRET_PATTERNS = (
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----",
    ),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
        r"\s*[:=]\s*['\"]?(?!\$\{|<|replace|change_me|example|test)"
        r"[A-Za-z0-9+/=_-]{16,}",
    ),
)
DEFAULT_CAPABILITY_MEMBERS = (
    "runner.py",
    "input.schema.json",
    "result.schema.json",
    "checkpoint.schema.json",
)
CAPABILITY_BUILD_MANIFEST = "capability-build.json"
RESOURCE_LOCK = "resources.lock.json"
RESOURCE_READY_STATUS = "release-ready"
TEMPORARY_URL_PATH_PARTS = frozenset(
    {"tmp", "temp", "temporary", "staging", "preview", "draft"},
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


def _safe_relative_path(value: object, label: str) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\x00" in value
    ):
        raise DeveloperPackError(f"{label} must be a safe POSIX relative path")
    raw_parts = value.split("/")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in raw_parts)
        or ":" in raw_parts[0]
    ):
        raise DeveloperPackError(f"{label} must be a safe POSIX relative path")
    return path


def _project_file(root: Path, relative: PurePosixPath, label: str) -> Path:
    current = root.resolve()
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise DeveloperPackError(
                f"{label} cannot contain symbolic links: {relative}",
            )
    try:
        current.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise DeveloperPackError(
            f"{label} escapes its project root: {relative}",
        ) from exc
    return current


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, (2026, 10, 26, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def _devkit():
    path = _devkit_root() / "dclaw_agent_devkit.py"
    spec = importlib.util.spec_from_file_location(
        "dclaw_embedded_devkit",
        path,
    )
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
            f"command failed ({completed.returncode}): {' '.join(args)}: {detail}",
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
    return (
        project,
        _read_json(project_path),
        manifest_path,
        _read_json(manifest_path),
    )


def _capability_ids(manifest: dict) -> list[str]:
    values = manifest.get("capabilities")
    if not isinstance(values, list):
        raise DeveloperPackError("manifest capabilities must be a list")
    try:
        return [str(item["capability_id"]) for item in values]
    except (KeyError, TypeError) as exc:
        raise DeveloperPackError(
            "manifest capability declaration is invalid",
        ) from exc


def _validate_evidence(project: Path) -> dict:
    baseline = _read_json(project / "docs" / "SOURCE_BEHAVIOR_SPEC.json")
    differences = _read_json(project / "docs" / "PORTING_RECORD.json")
    cases = baseline.get("cases")
    if (
        baseline.get("status") != "verified"
        or not isinstance(cases, list)
        or not cases
    ):
        raise DeveloperPackError(
            "behavior baseline is missing or not verified",
        )
    required = {
        "id",
        "input",
        "expected_steps",
        "expected_outcome",
        "evidence",
    }
    for case in cases:
        if not isinstance(case, dict) or not required.issubset(case):
            raise DeveloperPackError("behavior baseline case is incomplete")
        if not case["expected_steps"] or not case["evidence"]:
            raise DeveloperPackError(
                "behavior baseline case lacks steps or evidence",
            )
    items = differences.get("differences")
    if not isinstance(items, list):
        raise DeveloperPackError("behavior differences list is missing")
    for item in items:
        if not isinstance(item, dict) or item.get("approved") is not True:
            raise DeveloperPackError(
                "unapproved behavior difference blocks release",
            )
        if not str(item.get("approval_reference", "")).strip():
            raise DeveloperPackError(
                "behavior difference approval reference is missing",
            )
    if differences.get("pending"):
        raise DeveloperPackError("pending behavior differences block release")
    return {"behavior_cases": len(cases), "approved_differences": len(items)}


def _scan_secrets(project: Path) -> int:
    scanned = 0
    ignored = {".git", ".venv", "__pycache__"}
    release_inputs = (
        project / "project.json",
        project / "manifest.template.json",
        project / "agent",
        project / "capability-pack",
        project / "docs",
    )
    candidates: list[Path] = []
    for source in release_inputs:
        if source.is_file():
            candidates.append(source)
        elif source.is_dir():
            candidates.extend(source.rglob("*"))
    for path in sorted(set(candidates)):
        if not path.is_file() or any(part in ignored for part in path.parts):
            continue
        if (
            path.name in SECRET_FILE_NAMES
            or path.suffix.lower() in SECRET_SUFFIXES
        ):
            raise DeveloperPackError(
                f"secret-like file blocks release: {path}",
            )
        if path.stat().st_size > 2 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        scanned += 1
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                raise DeveloperPackError(
                    f"possible embedded secret blocks release: {path}",
                )
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
            "capability-pack/windows-x64/input.schema.json",
            "capability-pack/windows-x64/result.schema.json",
            "capability-pack/windows-x64/checkpoint.schema.json",
            "capability-pack/windows-x64/descriptor.template.json",
        ):
            if not (project / relative).is_file():
                raise DeveloperPackError(
                    f"required local capability file is missing: {relative}",
                )
    return len(dependencies)


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeveloperPackError(f"{label} is missing")
    cleaned = value.strip()
    if re.search(r"(?i)\b(?:pending|placeholder|replace|todo|tbd)\b", cleaned):
        raise DeveloperPackError(f"{label} is not release-ready")
    return cleaned


def _required_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise DeveloperPackError(f"{label} SHA-256 is invalid")
    return value


def _validated_https_url(
    value: object,
    label: str,
    allowed_domains: set[str],
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeveloperPackError(f"{label} URL is missing")
    parsed = urlsplit(value.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise DeveloperPackError(f"{label} URL must use formal HTTPS")
    if (
        hostname == "localhost"
        or hostname.endswith((".localhost", ".local", ".test"))
    ):
        raise DeveloperPackError(f"{label} URL uses a non-production host")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise DeveloperPackError(f"{label} URL uses a non-production host")
    if not any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in allowed_domains
    ):
        raise DeveloperPackError(f"{label} URL host is not allowed")
    path_parts = {
        part.lower() for part in PurePosixPath(parsed.path).parts if part != "/"
    }
    if path_parts & TEMPORARY_URL_PATH_PARTS:
        raise DeveloperPackError(f"{label} URL uses a temporary path")
    return value.strip()


def _validate_resources(
    project: Path,
    mode: str,
    *,
    artifact_url: str | None = None,
) -> int:
    path = project / "capability-pack" / "windows-x64" / RESOURCE_LOCK
    if mode == "none" and not path.is_file():
        return 0
    if not path.is_file():
        raise DeveloperPackError("local resource lock is missing")
    lock = _read_json(path)
    if lock.get("schema_version") != 1:
        raise DeveloperPackError("local resource lock schema_version is unsupported")
    if lock.get("release_ready") is not True:
        raise DeveloperPackError("local resources are not release-ready")
    if lock.get("status") != RESOURCE_READY_STATUS:
        raise DeveloperPackError("local resource lock status is not release-ready")
    domains = lock.get("allowed_domains")
    if not isinstance(domains, list) or not domains:
        raise DeveloperPackError("local resource allowed domains are missing")
    allowed_domains: set[str] = set()
    for value in domains:
        domain = _required_text(value, "local resource allowed domain").lower()
        if (
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", domain)
            or domain == "localhost"
            or domain.endswith((".localhost", ".local", ".test"))
        ):
            raise DeveloperPackError("local resource allowed domain is invalid")
        allowed_domains.add(domain)
    if artifact_url is not None:
        _validated_https_url(
            artifact_url,
            "capability artifact",
            allowed_domains,
        )
    resources = lock.get("resources")
    if not isinstance(resources, list):
        raise DeveloperPackError("local resource entries are invalid")
    identifiers: set[str] = set()
    for index, item in enumerate(resources):
        label = f"local resource {index + 1}"
        if not isinstance(item, dict):
            raise DeveloperPackError(f"{label} is invalid")
        resource_id = _required_text(item.get("resource_id"), f"{label} id")
        if resource_id in identifiers:
            raise DeveloperPackError("local resource id is duplicated")
        identifiers.add(resource_id)
        _required_text(item.get("version"), f"{label} version")
        _validated_https_url(item.get("url"), label, allowed_domains)
        if (
            not isinstance(item.get("size_bytes"), int)
            or isinstance(item["size_bytes"], bool)
            or item["size_bytes"] <= 0
        ):
            raise DeveloperPackError(f"{label} size is invalid")
        _required_sha256(item.get("sha256"), label)
        _validated_https_url(
            item.get("sbom_url"),
            f"{label} SBOM",
            allowed_domains,
        )
        _required_sha256(item.get("sbom_sha256"), f"{label} SBOM")
        _required_text(
            item.get("license_spdx"),
            f"{label} license identifier",
        )
        _validated_https_url(
            item.get("license_evidence_url"),
            f"{label} license evidence",
            allowed_domains,
        )
        _required_sha256(
            item.get("license_evidence_sha256"),
            f"{label} license evidence",
        )
        unpacked_size = item.get("unpacked_size_bytes")
        target_path = item.get("target_path")
        if unpacked_size is not None or target_path is not None:
            if (
                not isinstance(unpacked_size, int)
                or isinstance(unpacked_size, bool)
                or unpacked_size <= 0
            ):
                raise DeveloperPackError(f"{label} unpacked size is invalid")
            _safe_relative_path(target_path, f"{label} target path")
        _required_text(item.get("cache_key"), f"{label} cache key")
        _required_text(item.get("rollback_version"), f"{label} rollback version")
        for field in ("status", "distribution_status"):
            if field in item and item[field] not in {"ready", "release-ready"}:
                raise DeveloperPackError(f"{label} {field} is not release-ready")
    return len(resources)


def _capability_build_spec(
    root: Path,
    artifact_file: Path | None,
) -> tuple[str, Path | None, list[object], int | str]:
    if artifact_file is not None:
        return "prebuilt", artifact_file.resolve(), [], "command-line"
    manifest_path = root / CAPABILITY_BUILD_MANIFEST
    if not manifest_path.is_file():
        return "members", None, list(DEFAULT_CAPABILITY_MEMBERS), "legacy"
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != 1:
        raise DeveloperPackError(
            "capability build manifest schema_version is unsupported",
        )
    artifact = manifest.get("artifact")
    if not isinstance(artifact, dict):
        raise DeveloperPackError(
            "capability build manifest artifact is missing",
        )
    source = artifact.get("source")
    if source == "members":
        members = artifact.get("members")
        if not isinstance(members, list) or not members:
            raise DeveloperPackError(
                "capability build manifest members are missing",
            )
        return "members", None, members, 1
    if source == "prebuilt":
        relative = _safe_relative_path(
            artifact.get("path"),
            "prebuilt artifact path",
        )
        return (
            "prebuilt",
            _project_file(root, relative, "prebuilt artifact"),
            [],
            1,
        )
    raise DeveloperPackError(
        "capability artifact source must be members or prebuilt",
    )


def _capability_files(
    root: Path,
    members: list[object],
) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    names: set[str] = set()
    casefolded: set[str] = set()
    reserved = "DCLAW-CAPABILITY-MANIFEST.json"
    for member in members:
        if isinstance(member, str):
            source_value = target_value = member
            expected_sha256 = None
        elif isinstance(member, dict):
            source_value = member.get("source")
            target_value = member.get("target", source_value)
            expected_sha256 = member.get("sha256")
            if expected_sha256 is not None and not re.fullmatch(
                r"[0-9a-f]{64}",
                str(expected_sha256),
            ):
                raise DeveloperPackError(
                    "capability member SHA-256 is invalid",
                )
        else:
            raise DeveloperPackError(
                "capability build member must be a path or object",
            )
        source_relative = _safe_relative_path(
            source_value,
            "capability member source",
        )
        target_relative = _safe_relative_path(
            target_value,
            "capability member target",
        )
        source = _project_file(
            root,
            source_relative,
            "capability member source",
        )
        if not source.exists():
            raise DeveloperPackError(
                f"local capability source is missing: {source_relative}",
            )
        if source.is_dir():
            if expected_sha256 is not None:
                raise DeveloperPackError(
                    "directory capability members cannot declare sha256",
                )
            candidates = sorted(
                path for path in source.rglob("*") if path.is_file()
            )
            if not candidates:
                raise DeveloperPackError(
                    f"local capability directory is empty: {source_relative}",
                )
            expanded = [
                (
                    path,
                    target_relative
                    / PurePosixPath(path.relative_to(source).as_posix()),
                )
                for path in candidates
            ]
        elif source.is_file():
            if (
                expected_sha256 is not None
                and _sha256(source) != expected_sha256
            ):
                raise DeveloperPackError(
                    f"capability member SHA-256 mismatch: {source_relative}",
                )
            expanded = [(source, target_relative)]
        else:
            raise DeveloperPackError(
                f"unsupported capability member: {source_relative}",
            )
        for path, target in expanded:
            _project_file(
                root,
                PurePosixPath(path.relative_to(root).as_posix()),
                "capability member",
            )
            name = target.as_posix()
            folded = name.casefold()
            if name == reserved or name in names or folded in casefolded:
                raise DeveloperPackError(
                    f"duplicate capability artifact path: {name}",
                )
            names.add(name)
            casefolded.add(folded)
            files.append((path, name))
    return sorted(files, key=lambda item: item[1])


def _build_capability_archive(
    root: Path,
    artifact_path: Path,
    members: list[object],
    manifest_version: int | str,
) -> int:
    files = _capability_files(root, members)
    if any(path.resolve() == artifact_path.resolve() for path, _name in files):
        raise DeveloperPackError(
            "capability artifact cannot include its own output ZIP",
        )
    inventory = {
        "schema_version": 1,
        "build_manifest_version": manifest_version,
        "files": [
            {
                "path": name,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path, name in files
        ],
    }
    inventory_bytes = (
        json.dumps(inventory, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    with zipfile.ZipFile(
        artifact_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        allowZip64=True,
    ) as archive:
        for source, name in files:
            with source.open("rb") as input_handle, archive.open(
                _zip_info(name),
                "w",
            ) as output:
                shutil.copyfileobj(input_handle, output, length=1024 * 1024)
        archive.writestr(
            _zip_info("DCLAW-CAPABILITY-MANIFEST.json"),
            inventory_bytes,
        )
    return len(files)


def _inspect_prebuilt_artifact(path: Path) -> int:
    if not path.is_file():
        raise DeveloperPackError(
            f"prebuilt capability artifact is missing: {path}",
        )
    try:
        with zipfile.ZipFile(path) as archive:
            seen: set[str] = set()
            for info in archive.infolist():
                relative = _safe_relative_path(
                    info.filename.rstrip("/"),
                    "artifact member",
                )
                name = relative.as_posix().casefold()
                if name in seen:
                    raise DeveloperPackError(
                        f"duplicate prebuilt capability artifact path: {info.filename}",
                    )
                seen.add(name)
                if info.flag_bits & 0x1:
                    raise DeveloperPackError(
                        "encrypted capability artifacts are unsupported",
                    )
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise DeveloperPackError(
                        "capability artifacts cannot contain symbolic links",
                    )
            bad = archive.testzip()
            if bad:
                raise DeveloperPackError(
                    f"prebuilt capability artifact is corrupt: {bad}",
                )
            files = sum(not info.is_dir() for info in archive.infolist())
    except zipfile.BadZipFile as exc:
        raise DeveloperPackError(
            "prebuilt capability artifact must be a valid ZIP",
        ) from exc
    if files < 1:
        raise DeveloperPackError("prebuilt capability artifact is empty")
    return files


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


def _validate_local_schemas(
    project: Path,
    mode: str,
    *,
    require_artifact: bool = True,
) -> int:
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
        raise DeveloperPackError(
            "local capability descriptor is not a release",
        )
    public_components = descriptor.get("public_components", [])
    if (
        not isinstance(public_components, list)
        or len(public_components) > 32
        or any(
            not isinstance(item, dict)
            or set(item) != {"component_id", "version"}
            or not isinstance(item.get("component_id"), str)
            or not item["component_id"]
            or not isinstance(item.get("version"), str)
            or not item["version"]
            for item in public_components
        )
        or len(
            {item["component_id"] for item in public_components}
        ) != len(public_components)
    ):
        raise DeveloperPackError(
            "public Component requirements must use unique exact id/version pairs",
        )
    entrypoint = descriptor.get("entrypoint")
    if not isinstance(entrypoint, dict):
        raise DeveloperPackError("local capability entrypoint is invalid")
    entrypoint_component = entrypoint.get("component_id")
    if entrypoint_component is not None and entrypoint_component not in {
        item["component_id"] for item in public_components
    }:
        raise DeveloperPackError(
            "entrypoint public Component is not declared",
        )
    if require_artifact:
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
            raise DeveloperPackError(
                "local capability artifact metadata is incomplete",
            )
    schemas = descriptor.get("schemas")
    if not isinstance(schemas, dict):
        raise DeveloperPackError("local capability schemas are missing")
    for name in ("input", "result", "checkpoint"):
        entry = schemas.get(name)
        if not isinstance(entry, dict):
            raise DeveloperPackError(
                f"local {name} schema declaration is missing",
            )
        path = root / str(entry.get("path", ""))
        document = _read_json(path)
        if (
            entry.get("sha256") != _sha256(path)
            or entry.get("document") != document
        ):
            raise DeveloperPackError(
                f"local {name} schema digest or document mismatch",
            )
        if (
            document.get("type") != "object"
            or document.get("additionalProperties") is not False
        ):
            raise DeveloperPackError(
                f"local {name} schema must be a closed object",
            )
    registration_path = project / "capability-pack" / "registration.json"
    if require_artifact:
        registration = _read_json(registration_path)
        if registration.get("descriptor") != descriptor:
            raise DeveloperPackError("signed local capability descriptor is stale")
        manifest = _read_json(project / "manifest.template.json")
        if registration.get("signer_id") != manifest.get(
            "signer_id",
        ) or not registration.get("signature"):
            raise DeveloperPackError("local capability signature is missing")
    return 3


def build_local_capability(
    project_path: Path,
    artifact_url: str,
    private_key_path: Path,
    artifact_file: Path | None = None,
) -> dict:
    project, metadata, _manifest_path, manifest = _project(project_path)
    _validate_resources(
        project,
        metadata.get("local_helper"),
        artifact_url=artifact_url,
    )
    root = project / "capability-pack" / "windows-x64"
    _materialize_descriptor(project)
    artifact_path = root / "artifact.zip"
    mode, prebuilt, members, manifest_version = _capability_build_spec(
        root,
        artifact_file,
    )
    if mode == "members":
        file_count = _build_capability_archive(
            root,
            artifact_path,
            members,
            manifest_version,
        )
    else:
        assert prebuilt is not None
        file_count = _inspect_prebuilt_artifact(prebuilt)
        if prebuilt.resolve() != artifact_path.resolve():
            shutil.copyfile(prebuilt, artifact_path)
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
            devkit._canonical_json(descriptor),
        ),
    ).decode("ascii")
    registration = {
        "descriptor": descriptor,
        "signer_id": manifest["signer_id"],
        "signature": signature,
    }
    registration_path = project / "capability-pack" / "registration.json"
    _write_json(registration_path, registration)
    _validate_local_schemas(project, metadata.get("local_helper"))
    return {
        "status": "built",
        "artifact": str(artifact_path),
        "artifact_sha256": descriptor["artifact"]["sha256"],
        "artifact_mode": mode,
        "artifact_files": file_count,
        "registration": str(registration_path),
        "signer_id": manifest["signer_id"],
    }


def verify_local_capability(project_path: Path, public_key_path: Path) -> dict:
    project, metadata, _manifest_path, _manifest = _project(project_path)
    if metadata.get("local_helper") == "none":
        return {"status": "not-required"}
    registration = _read_json(
        project / "capability-pack" / "registration.json",
    )
    descriptor = registration["descriptor"]
    try:
        signature = base64.b64decode(registration["signature"], validate=True)
        _devkit()._load_public_key(public_key_path.resolve()).verify(
            signature,
            _devkit()._canonical_json(descriptor),
        )
    except Exception as exc:
        raise DeveloperPackError(
            "local capability signature is invalid",
        ) from exc
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
        raise DeveloperPackError(
            "project has not adopted the current standard",
        )
    if metadata.get("developer_pack_version") != PACK_VERSION:
        raise DeveloperPackError(
            "project developer pack version is not current",
        )
    if metadata.get("devkit_version") != DEVKIT_VERSION:
        raise DeveloperPackError("project DevKit version is not current")
    if _standard_version() != STANDARD_VERSION:
        raise DeveloperPackError(
            "developer pack and standard versions do not match",
        )
    declared = _capability_ids(manifest)
    expected = metadata.get("declared_platform_capabilities")
    if declared != expected:
        raise DeveloperPackError(
            "manifest capability declarations exceed project record",
        )
    if len(declared) != len(set(declared)):
        raise DeveloperPackError("manifest contains duplicate capabilities")
    if str(manifest.get("signer_id", "")).startswith("replace-"):
        raise DeveloperPackError("approved signer_id is not configured")
    mode = metadata.get("local_helper")
    if mode not in {"none", "optional", "required"}:
        raise DeveloperPackError(
            "local_helper must be none, optional, or required",
        )
    local = {item for item in declared if item.startswith("local.")}
    expected_local = {
        "none": set(),
        "optional": {LOCAL_SESSION},
        "required": {LOCAL_SESSION, LOCAL_PREFLIGHT},
    }[mode]
    if local != expected_local:
        raise DeveloperPackError(
            "local helper declaration does not match capability set",
        )
    devkit = _devkit()
    manifest["capability_digest"] = devkit.compute_capability_digest(manifest)
    devkit.validate_manifest(manifest, require_content_digest=False)
    devkit.validate_workspace(project / "agent", manifest)
    evidence = _validate_evidence(project)
    dependencies = _validate_dependencies(project, mode)
    resources = _validate_resources(project, mode)
    schemas = _validate_local_schemas(
        project,
        mode,
        require_artifact=False,
    )
    scanned = _scan_secrets(project)
    return {
        "status": "valid",
        "project": str(project),
        "agent_id": manifest["agent_id"],
        "version": manifest["version"],
        "local_helper": mode,
        "capabilities": len(declared),
        "dependencies": dependencies,
        "resources": resources,
        "local_schemas": schemas,
        "secret_scan_files": scanned,
        **evidence,
    }


def _test_configuration(
    project: Path,
    metadata: dict,
) -> tuple[str, str, list[str], list[str]]:
    configured = metadata.get("tests")
    if configured is None:
        return "unittest", sys.executable, ["tests"], []
    if not isinstance(configured, dict):
        raise DeveloperPackError(
            "project tests configuration must be an object",
        )
    adapter = configured.get("adapter")
    if adapter not in {"unittest", "pytest"}:
        raise DeveloperPackError(
            "project test adapter must be unittest or pytest",
        )
    paths = configured.get("paths", ["tests"])
    arguments = configured.get("arguments", [])
    python_value = configured.get("python")
    if not isinstance(paths, list) or not paths:
        raise DeveloperPackError("project test paths must be a non-empty list")
    if not isinstance(arguments, list) or not all(
        isinstance(value, str) and "\x00" not in value for value in arguments
    ):
        raise DeveloperPackError("project test arguments must be strings")
    safe_paths = [
        _safe_relative_path(value, "project test path").as_posix()
        for value in paths
    ]
    if python_value is None:
        python_executable = sys.executable
    else:
        python_relative = _safe_relative_path(
            python_value,
            "project test Python",
        )
        python_executable = str(
            _validated_project_venv_python(project, python_relative),
        )
    if adapter == "pytest" and any(
        value == "--junitxml"
        or value.startswith("--junitxml=")
        or value == "--junit-xml"
        or value.startswith("--junit-xml=")
        for value in arguments
    ):
        raise DeveloperPackError(
            "pytest JUnit output is managed by the developer pack",
        )
    return adapter, python_executable, safe_paths, arguments


def _validated_project_venv_python(
    project: Path,
    relative: PurePosixPath,
) -> Path:
    label = "project test Python"
    posix_entry = PurePosixPath(".venv/bin/python")
    windows_entry = PurePosixPath(".venv/Scripts/python.exe")
    if relative not in {posix_entry, windows_entry}:
        raise DeveloperPackError(
            f"{label} must be .venv/bin/python or .venv/Scripts/python.exe",
        )
    root = project.resolve(strict=True)
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise DeveloperPackError(
                f"{label} cannot use a symbolic-link directory: {relative}",
            )
        if not current.is_dir():
            raise DeveloperPackError(
                f"{label} parent is missing: {relative}",
            )
    executable = current / relative.parts[-1]
    environment = root / ".venv"
    configuration = environment / "pyvenv.cfg"
    if configuration.is_symlink() or not configuration.is_file():
        raise DeveloperPackError(
            f"{label} requires a trusted .venv/pyvenv.cfg",
        )
    if relative == windows_entry and executable.is_symlink():
        raise DeveloperPackError(
            f"{label} Windows entry cannot be a symbolic link",
        )
    try:
        target = executable.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise DeveloperPackError(
            f"{label} escapes its project root or is missing: {relative}",
        ) from exc
    if not target.is_file() or (
        os.name != "nt" and not os.access(executable, os.X_OK)
    ):
        raise DeveloperPackError(f"{label} is not executable: {relative}")
    try:
        header = target.read_bytes()[:4]
    except OSError as exc:
        raise DeveloperPackError(
            f"{label} cannot be inspected: {relative}",
        ) from exc
    native_headers = {
        b"\x7fELF",
        b"\xfe\xed\xfa\xce",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
    }
    if header not in native_headers and header[:2] != b"MZ":
        raise DeveloperPackError(
            f"{label} must resolve to a native Python executable, not a wrapper",
        )
    try:
        target.relative_to(root)
    except ValueError:
        pass
    else:
        try:
            target.relative_to(environment)
        except ValueError as exc:
            raise DeveloperPackError(
                f"{label} cannot escape to a writable project target",
            ) from exc
    config_values: dict[str, str] = {}
    for line in configuration.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            name, value = line.split("=", 1)
            config_values[name.strip().lower()] = value.strip()
    home = config_values.get("home")
    if relative == posix_entry and executable.is_symlink():
        home_root = Path(home).expanduser() if home else None
        home_candidates: list[Path] = []
        if home_root is not None:
            home_candidates.extend(home_root / name for name in ("python", "python3"))
            if home_root.is_dir():
                home_candidates.extend(home_root.glob("python3.*"))
        home_targets = {
            candidate.resolve()
            for candidate in home_candidates
            if candidate.is_file()
        }
        if target not in home_targets:
            raise DeveloperPackError(
                f"{label} target does not match .venv/pyvenv.cfg home",
            )
    probe = (
        "import json,sys;print(json.dumps({"
        "'implementation':sys.implementation.name,"
        "'executable':sys.executable,"
        "'prefix':sys.prefix,"
        "'base_prefix':sys.base_prefix,"
        "'version':[sys.version_info.major,sys.version_info.minor]}))"
    )
    try:
        completed = subprocess.run(
            [str(executable), "-I", "-c", probe],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        details = json.loads(completed.stdout.strip())
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise DeveloperPackError(
            f"{label} is not a usable Python interpreter: {relative}",
        ) from exc
    try:
        reported_executable = Path(details["executable"]).resolve(strict=True)
        reported_prefix = Path(details["prefix"]).resolve(strict=True)
        reported_base_prefix = Path(details["base_prefix"]).resolve(strict=True)
        version = tuple(details["version"])
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise DeveloperPackError(
            f"{label} returned invalid interpreter metadata: {relative}",
        ) from exc
    if (
        completed.returncode != 0
        or details.get("implementation") != "cpython"
        or reported_executable != target
        or reported_prefix != environment
        or reported_prefix == reported_base_prefix
        or version not in {(3, 10), (3, 11), (3, 12), (3, 13)}
    ):
        raise DeveloperPackError(
            f"{label} must be CPython 3.10-3.13 from its project virtual environment",
        )
    return executable


def _run_project_test_command(
    project: Path,
    command: list[str],
) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )


def run_tests(project_path: Path) -> dict:
    gate = release_gate(project_path)
    project, metadata, _manifest_path, _manifest = _project(project_path)
    adapter, python_executable, paths, arguments = _test_configuration(
        project,
        metadata,
    )
    commands: list[list[str]] = []
    count = 0
    if adapter == "unittest":
        for path in paths:
            command = [
                python_executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                path,
                "-v",
                *arguments,
            ]
            commands.append(command)
            completed = _run_project_test_command(project, command)
            if completed.returncode:
                raise DeveloperPackError(
                    "project tests failed: "
                    + (completed.stderr or completed.stdout).strip(),
                )
            match = re.search(
                r"^Ran (\d+) tests?",
                completed.stderr,
                re.MULTILINE,
            )
            if not match:
                raise DeveloperPackError(
                    "unittest did not report an executed test count",
                )
            count += int(match.group(1))
    else:
        with tempfile.TemporaryDirectory(prefix="dclaw-pytest-") as temporary:
            report = Path(temporary) / "results.xml"
            command = [
                python_executable,
                "-m",
                "pytest",
                *arguments,
                *paths,
                f"--junitxml={report}",
            ]
            commands.append(command)
            completed = _run_project_test_command(project, command)
            if completed.returncode:
                raise DeveloperPackError(
                    "project tests failed: "
                    + (completed.stdout or completed.stderr).strip(),
                )
            try:
                root = ET.parse(report).getroot()
                suites = (
                    [root]
                    if root.tag == "testsuite"
                    else root.findall(".//testsuite")
                )
                count = sum(
                    int(suite.attrib.get("tests", "0")) for suite in suites
                )
            except (OSError, ET.ParseError, ValueError) as exc:
                raise DeveloperPackError(
                    "pytest did not produce valid JUnit evidence",
                ) from exc
    if count < 1:
        raise DeveloperPackError(
            "project test suite did not execute any tests",
        )
    evidence_commands = [
        [
            "<python>"
            if value == python_executable
            else re.sub(r"--junitxml=.*", "--junitxml=<evidence.xml>", value)
            for value in command
        ]
        for command in commands
    ]
    return {
        **gate,
        "tests": count,
        "test_status": "passed",
        "test_adapter": adapter,
        "test_commands": evidence_commands,
    }


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


def initialize_project(
    target: Path,
    agent_id: str,
    name: str,
    mode: str,
) -> dict:
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
            {"capability_id": LOCAL_SESSION, "contract_version": "1"},
        )
        manifest["platform_contract_versions"]["local_execution"] = "1"
    if mode == "required":
        capabilities.append(
            {"capability_id": LOCAL_PREFLIGHT, "contract_version": "1"},
        )
    metadata["local_helper"] = mode
    metadata["declared_platform_capabilities"] = [
        item["capability_id"] for item in capabilities
    ]
    manifest["capability_digest"] = _devkit().compute_capability_digest(
        manifest,
    )
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
    return {
        "status": "initialized",
        "project": str(target.resolve()),
        "local_helper": mode,
    }


def _devkit_command(*args: str) -> dict:
    return _run(
        [sys.executable, str(_devkit_root() / "dclaw_agent_devkit.py"), *args],
    )


def build_project(
    project_path: Path,
    private_key: Path,
    public_key: Path,
    output: Path,
    capability_artifact_url: str | None = None,
    capability_artifact_file: Path | None = None,
) -> dict:
    project_metadata = _read_json(project_path.resolve() / "project.json")
    test_result = run_tests(project_path)
    capability_build = None
    if project_metadata.get("local_helper") != "none":
        if not capability_artifact_url:
            raise DeveloperPackError(
                "--capability-artifact-url is required for local helper releases",
            )
        capability_build = build_local_capability(
            project_path,
            capability_artifact_url,
            private_key,
            capability_artifact_file,
        )
    project, _metadata, manifest_path, manifest = _project(project_path)
    _devkit_command("digest", "--manifest", str(manifest_path), "--write")
    validation = _devkit_command(
        "validate",
        "--source",
        str(project / "agent"),
        "--manifest",
        str(manifest_path),
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
    evidence_path = (
        project / "release-evidence" / f"{manifest['version']}.json"
    )
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
            "major standard upgrade requires --accept-standard after reviewing UPGRADE.md",
        )
    previous = {
        "developer_pack_version": metadata.get("developer_pack_version"),
        "standard_version": current_standard,
        "devkit_version": metadata.get("devkit_version"),
    }
    metadata["developer_pack_version"] = PACK_VERSION
    metadata["standard"] = {"id": STANDARD_ID, "version": STANDARD_VERSION}
    metadata["devkit_version"] = DEVKIT_VERSION
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
                    "expected_outcome": {
                        "output_text": "DCLAW LOCAL CAPABILITY",
                    },
                    "evidence": [
                        "tests/test_runtime.py",
                        "offline demo result.txt",
                    ],
                },
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
        [sys.executable, "capability-pack/windows-x64/runner.py"],
        cwd=workspace,
    )
    output = workspace / "release" / "example-local-agent-0.1.0.zip"
    result = build_project(
        workspace,
        private_key,
        public_key,
        output,
        "https://downloads.deepmega.cn/capabilities/example-local-agent-0.1.0.zip",
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
        "--local-helper",
        choices=("none", "optional", "required"),
        default="none",
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
    build.add_argument("--capability-artifact-file", type=Path)
    capability = commands.add_parser("capability-build")
    capability.add_argument("--project", type=Path, required=True)
    capability.add_argument("--private-key", type=Path, required=True)
    capability.add_argument("--artifact-url", required=True)
    capability.add_argument("--artifact-file", type=Path)
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
                "standard": {
                    "id": STANDARD_ID,
                    "version": _standard_version(),
                },
                "devkit_version": DEVKIT_VERSION,
            }
        elif args.command == "init":
            result = initialize_project(
                args.target,
                args.agent_id,
                args.name,
                args.local_helper,
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
                args.capability_artifact_file,
            )
        elif args.command == "capability-build":
            result = build_local_capability(
                args.project,
                args.artifact_url,
                args.private_key,
                args.artifact_file,
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
