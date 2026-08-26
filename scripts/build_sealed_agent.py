#!/usr/bin/env python3
"""Build a signed sealed-agent ZIP outside the DClaw administration UI."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from qwenpaw.app.sealed_agents.package import build_signed_package_bytes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.resolve()
    files = {
        f"agent/{path.relative_to(source).as_posix()}": path.read_bytes()
        for path in source.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    raw_key = base64.b64decode(
        args.private_key.read_text(encoding="utf-8").strip(), validate=True
    )
    package = build_signed_package_bytes(
        manifest,
        files,
        Ed25519PrivateKey.from_private_bytes(raw_key),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(package)


if __name__ == "__main__":
    main()
