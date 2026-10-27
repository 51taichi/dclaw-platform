"""Deterministic archive builder for the public developer pack."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import zipfile


def _is_publishable_file(path: Path) -> bool:
    return (
        path.is_file()
        and "__pycache__" not in path.parts
        and "__MACOSX" not in path.parts
        and path.suffix != ".pyc"
        and path.name != ".DS_Store"
        and not path.name.startswith("._")
    )


def _files(root: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    developer_root = root / "developer_pack"
    for path in sorted(developer_root.rglob("*")):
        if _is_publishable_file(path):
            result[path.relative_to(developer_root).as_posix()] = path.read_bytes()
    devkit_root = root / "devkit"
    for path in sorted(devkit_root.rglob("*")):
        if _is_publishable_file(path):
            relative = path.relative_to(devkit_root).as_posix()
            result[f"devkit/{relative}"] = path.read_bytes()
    repository_root = root.parents[2]
    standard_path = (
        repository_root / "docs" / "super-agent-development-standard-v1.zh-CN.md"
    )
    if not standard_path.is_file():
        standard_path = (
            developer_root
            / "standard"
            / "super-agent-development-standard-v1.zh-CN.md"
        )
    if not standard_path.is_file():
        raise FileNotFoundError("canonical development standard asset is missing")
    result[
        "standard/super-agent-development-standard-v1.zh-CN.md"
    ] = standard_path.read_bytes()
    return result


def _standard_version(data: bytes) -> str:
    match = re.search(r"^当前版本：`([^`]+)`", data.decode("utf-8"), re.MULTILINE)
    if not match:
        raise ValueError("development standard version marker is missing")
    return match.group(1)


def build_archive(plugin_root: Path) -> tuple[bytes, dict]:
    files = _files(plugin_root)
    pack_version = files["VERSION"].decode("utf-8").strip()
    devkit_version = files["devkit/VERSION"].decode("utf-8").strip()
    standard = files[
        "standard/super-agent-development-standard-v1.zh-CN.md"
    ]
    manifest = {
        "name": "dclaw-super-agent-developer-pack",
        "version": pack_version,
        "standard": {
            "id": "dclaw.super-agent-development",
            "version": _standard_version(standard),
        },
        "devkit_version": devkit_version,
        "server_source_required": False,
        "files": [
            {
                "path": name,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
            for name, data in sorted(files.items())
        ],
    }
    files["PACKAGE-MANIFEST.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    files["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n"
        for name, data in sorted(files.items())
    ).encode("ascii")
    prefix = f"dclaw-super-agent-developer-pack-{pack_version}"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(f"{prefix}/{name}", (2026, 10, 26, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o100755 if name in {
                "bootstrap.sh",
                "dclaw_developer.py",
                "devkit/bootstrap.sh",
                "devkit/dclaw_agent_devkit.py",
            } else 0o100644
            info.external_attr = mode << 16
            archive.writestr(info, data)
    payload = output.getvalue()
    metadata = {
        **{key: value for key, value in manifest.items() if key != "files"},
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "file_count": len(files),
        "archive_prefix": prefix,
    }
    return payload, metadata
