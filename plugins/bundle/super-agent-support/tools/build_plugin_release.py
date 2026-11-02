#!/usr/bin/env python3
"""Build a standalone support-plugin ZIP from one committed Git revision."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import re
import subprocess
import zipfile


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
PLUGIN_PATH = "plugins/bundle/super-agent-support"
STANDARD_PATH = "docs/super-agent-development-standard-v1.zh-CN.md"
STANDARD_IN_PLUGIN = (
    "super-agent-support/developer_pack/standard/"
    "super-agent-development-standard-v1.zh-CN.md"
)


def _git_bytes(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=REPOSITORY_ROOT,
        check=True, capture_output=True,
    ).stdout


def build(output: Path, *, revision: str = "HEAD") -> dict[str, str | int]:
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
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(archive_bytes)
    with zipfile.ZipFile(output, "a", compression=zipfile.ZIP_DEFLATED) as target:
        info = zipfile.ZipInfo(STANDARD_IN_PLUGIN, (2026, 11, 2, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        target.writestr(info, standard)
    with zipfile.ZipFile(output) as result:
        if result.testzip() is not None:
            raise ValueError("plugin ZIP verification failed")
    return {
        "plugin_version": plugin["version"],
        "standard_version": expected,
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
