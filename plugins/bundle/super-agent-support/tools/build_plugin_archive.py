#!/usr/bin/env python3
"""Build a deterministic hot-install archive for the support plugin."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import stat
import zipfile


STANDARD_RELATIVE_PATH = Path(
    "developer_pack/standard/"
    "super-agent-development-standard-v1.zh-CN.md",
)
EXCLUDED_PARTS = {"__pycache__", "bin", "obj"}
FIXED_TIMESTAMP = (2026, 10, 28, 0, 0, 0)


def _publishable(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return (
        path.is_file()
        and not EXCLUDED_PARTS.intersection(relative.parts)
        and path.suffix != ".pyc"
        and path.name != ".DS_Store"
        and not path.name.startswith("._")
        and "__MACOSX" not in relative.parts
    )


def build_archive(plugin_root: Path, standard_path: Path) -> tuple[bytes, dict]:
    plugin_root = plugin_root.resolve()
    standard_path = standard_path.resolve()
    if not (plugin_root / "plugin.json").is_file():
        raise FileNotFoundError("plugin.json is missing")
    if not standard_path.is_file():
        raise FileNotFoundError("canonical development standard is missing")

    files = {
        path.relative_to(plugin_root).as_posix(): path.read_bytes()
        for path in sorted(plugin_root.rglob("*"))
        if _publishable(path, plugin_root)
    }
    files[STANDARD_RELATIVE_PATH.as_posix()] = standard_path.read_bytes()

    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for name, data in sorted(files.items()):
            source = plugin_root / name
            executable = source.is_file() and bool(
                source.stat().st_mode & stat.S_IXUSR,
            )
            info = zipfile.ZipInfo(name, FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if executable else 0o100644) << 16
            archive.writestr(info, data)

    payload = output.getvalue()
    manifest = json.loads(files["plugin.json"])
    return payload, {
        "plugin_id": manifest["id"],
        "version": manifest["version"],
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "file_count": len(files),
        "standard_path": STANDARD_RELATIVE_PATH.as_posix(),
    }


def main() -> int:
    plugin_root = Path(__file__).parents[1]
    repository_root = plugin_root.parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-root", type=Path, default=plugin_root)
    parser.add_argument(
        "--standard",
        type=Path,
        default=(
            repository_root
            / "docs"
            / "super-agent-development-standard-v1.zh-CN.md"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    payload, metadata = build_archive(args.plugin_root, args.standard)
    repeated, repeated_metadata = build_archive(args.plugin_root, args.standard)
    if payload != repeated or metadata != repeated_metadata:
        raise SystemExit("plugin archive is not reproducible")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(payload)
    print(json.dumps(metadata, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
