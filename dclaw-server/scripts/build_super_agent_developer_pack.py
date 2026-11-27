#!/usr/bin/env python3
"""Build the standalone DClaw Super Agent developer pack."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).parents[1]
PLUGIN_ROOT = ROOT / "plugins" / "bundle" / "super-agent-support"


def _archive_module():
    path = PLUGIN_ROOT / "developer_pack" / "archive.py"
    spec = importlib.util.spec_from_file_location("developer_pack_archive", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load developer pack archive builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    payload, metadata = _archive_module().build_archive(PLUGIN_ROOT)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"{metadata['archive_prefix']}.zip"
    output.write_bytes(payload)
    checksum = output.with_suffix(output.suffix + ".sha256")
    checksum.write_text(f"{metadata['sha256']}  {output.name}\n", encoding="ascii")
    manifest = output.with_suffix(output.suffix + ".json")
    manifest.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    repeated, repeated_metadata = _archive_module().build_archive(PLUGIN_ROOT)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        prefix = metadata["archive_prefix"] + "/"
        package_manifest = json.loads(
            archive.read(prefix + "PACKAGE-MANIFEST.json")
        )
        errors = []
        for item in package_manifest["files"]:
            data = archive.read(prefix + item["path"])
            if hashlib.sha256(data).hexdigest() != item["sha256"]:
                errors.append(item["path"])
        names = set(archive.namelist())
    verification_payload = {
        "status": "valid" if not errors and repeated == payload else "invalid",
        "archive_sha256": metadata["sha256"],
        "manifest_files_verified": len(package_manifest["files"]),
        "checksum_errors": errors,
        "reproducible": repeated == payload,
        "repeated_sha256": repeated_metadata["sha256"],
        "server_source_present": any(
            "/src/qwenpaw/" in name or "/tests/unit/" in name for name in names
        ),
    }
    verification = output.with_suffix(output.suffix + ".verification.json")
    verification.write_text(
        json.dumps(
            verification_payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    if verification_payload["status"] != "valid":
        raise SystemExit("developer pack verification failed")
    print(
        json.dumps(
            {
                "status": "built",
                "output": str(output.resolve()),
                "checksum": str(checksum.resolve()),
                "metadata": str(manifest.resolve()),
                "verification": str(verification.resolve()),
                **metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
