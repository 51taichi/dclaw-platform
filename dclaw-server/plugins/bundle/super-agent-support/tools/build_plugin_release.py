#!/usr/bin/env python3
"""Build a standalone support-plugin ZIP from one committed Git revision."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
PLUGIN_PATH = "plugins/bundle/super-agent-support"
STANDARD_PATH = "docs/super-agent-development-standard-v1.zh-CN.md"
STANDARD_IN_PLUGIN = (
    "super-agent-support/developer_pack/standard/"
    "super-agent-development-standard-v1.zh-CN.md"
)
HELPER_METADATA_IN_PLUGIN = "super-agent-support/windows-helper/helper.json"
HELPER_PROJECT_IN_PLUGIN = (
    "super-agent-support/windows-helper/DClaw.LocalHelper.csproj"
)
HELPER_RELEASE_ROOT = "super-agent-support/platform_helpers/windows-x64"
HELPER_EXECUTABLE_IN_PLUGIN = f"{HELPER_RELEASE_ROOT}/DClaw.LocalHelper.exe"
HELPER_MANIFEST_IN_PLUGIN = f"{HELPER_RELEASE_ROOT}/manifest.json"


def _git_bytes(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=REPOSITORY_ROOT,
        check=True, capture_output=True,
    ).stdout


def _compile_windows_helper(archive_bytes: bytes) -> bytes:
    with tempfile.TemporaryDirectory(prefix="dclaw-helper-release-") as temp:
        root = Path(temp)
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as source:
            source.extractall(root)
        project = root / HELPER_PROJECT_IN_PLUGIN
        publish = root / "published-helper"
        subprocess.run(
            [
                "dotnet", "publish", str(project),
                "--configuration", "Release",
                "--runtime", "win-x64",
                "--self-contained", "true",
                "--output", str(publish),
                "/p:PublishSingleFile=true",
                "/p:IncludeNativeLibrariesForSelfExtract=true",
                "/p:DebugType=None",
            ],
            cwd=REPOSITORY_ROOT,
            check=True,
        )
        executable = publish / "DClaw.LocalHelper.exe"
        if not executable.is_file():
            raise ValueError("Windows local-helper build did not create an executable")
        return executable.read_bytes()


def _write_release_file(
    archive: zipfile.ZipFile,
    name: str,
    content: bytes,
) -> None:
    info = zipfile.ZipInfo(name, (2026, 11, 2, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, content)


def build(
    output: Path,
    *,
    revision: str = "HEAD",
    windows_helper_binary: Path | None = None,
) -> dict[str, str | int]:
    archive_bytes = _git_bytes(
        "archive", "--format=zip", "--prefix=super-agent-support/",
        f"{revision}:{PLUGIN_PATH}",
    )
    standard = _git_bytes("show", f"{revision}:{STANDARD_PATH}")
    match = re.search(
        r"^当前版本：`([^`]+)`",
        standard.decode("utf-8"),
        re.MULTILINE,
    )
    if match is None:
        raise ValueError("canonical standard version is missing")
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as source:
        if STANDARD_IN_PLUGIN in source.namelist():
            raise ValueError("plugin already contains a standard copy")
        project = json.loads(source.read(
            "super-agent-support/developer_pack/templates/project/project.json",
        ))
        expected = project["standard"]["version"]
        if match.group(1) != expected:
            raise ValueError("plugin and canonical standard versions differ")
        plugin = json.loads(source.read("super-agent-support/plugin.json"))
        helper = json.loads(source.read(HELPER_METADATA_IN_PLUGIN))
    if helper != {
        "platform": "windows-x64",
        "version": helper.get("version"),
        "protocol_version": helper.get("protocol_version"),
        "executable": "DClaw.LocalHelper.exe",
    } or not all(
        isinstance(helper.get(key), str) and helper[key]
        for key in ("version", "protocol_version")
    ):
        raise ValueError("Windows local-helper metadata is invalid")
    helper_bytes = (
        windows_helper_binary.read_bytes()
        if windows_helper_binary is not None
        else _compile_windows_helper(archive_bytes)
    )
    if not helper_bytes:
        raise ValueError("Windows local-helper executable is empty")
    helper_manifest = {
        **helper,
        "size_bytes": len(helper_bytes),
        "sha256": hashlib.sha256(helper_bytes).hexdigest(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(archive_bytes)
    with zipfile.ZipFile(output, "a", compression=zipfile.ZIP_DEFLATED) as target:
        _write_release_file(target, STANDARD_IN_PLUGIN, standard)
        _write_release_file(
            target,
            HELPER_EXECUTABLE_IN_PLUGIN,
            helper_bytes,
        )
        _write_release_file(
            target,
            HELPER_MANIFEST_IN_PLUGIN,
            json.dumps(
                helper_manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
    with zipfile.ZipFile(output) as result:
        if result.testzip() is not None:
            raise ValueError("plugin ZIP verification failed")
    return {
        "plugin_version": plugin["version"],
        "standard_version": expected,
        "windows_helper_version": helper["version"],
        "size_bytes": output.stat().st_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", default="HEAD")
    args = parser.parse_args()
    print(json.dumps(build(args.output, revision=args.revision), sort_keys=True))


if __name__ == "__main__":
    main()
