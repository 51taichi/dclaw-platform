"""Restore one damaged signed release file from a verified copy."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from qwenpaw.app.sealed_agents.package import inspect_extracted_payload


def restore_signed_file(
    *,
    release_root: Path,
    relative_path: str,
    source: Path,
    expected_digest: str,
    backup_dir: Path,
    commit: bool = False,
) -> dict[str, str]:
    root = release_root.resolve(strict=True)
    target = root / relative_path
    if (
        not root.is_dir()
        or target.is_symlink()
        or not target.is_file()
        or not target.resolve(strict=True).is_relative_to(root)
        or source.is_symlink()
        or not source.is_file()
        or backup_dir.resolve().is_relative_to(root)
        or not expected_digest.startswith("sha256:")
    ):
        raise ValueError("unsafe signed release recovery input")
    original = target.read_bytes()
    replacement = source.read_bytes()
    before, _ = inspect_extracted_payload(root)
    with tempfile.TemporaryDirectory(prefix="signed-release-check-") as directory:
        staged = Path(directory) / "release"
        shutil.copytree(root, staged, symlinks=True)
        (staged / relative_path).write_bytes(replacement)
        candidate, _ = inspect_extracted_payload(staged)
    if candidate != expected_digest:
        raise ValueError("replacement does not restore signed release digest")
    result = {
        "before_digest": before,
        "expected_digest": expected_digest,
        "old_file_sha256": hashlib.sha256(original).hexdigest(),
        "restored_file_sha256": hashlib.sha256(replacement).hexdigest(),
        "status": "verified_dry_run",
    }
    if not commit:
        return result
    if before == expected_digest:
        result["status"] = "already_valid"
        return result
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{hashlib.sha256(original).hexdigest()}.bak"
    if backup.exists() and backup.read_bytes() != original:
        raise ValueError("backup collision")
    if not backup.exists():
        backup.write_bytes(original)
    temporary = target.with_name(f".{target.name}.restore-{os.getpid()}")
    try:
        temporary.write_bytes(replacement)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    after, _ = inspect_extracted_payload(root)
    if after != expected_digest:
        raise RuntimeError("signed release digest still mismatches after recovery")
    result.update(status="restored", after_digest=after, backup_sha256=backup.stem)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--relative-path", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--expected-digest", required=True)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    import json

    print(json.dumps(restore_signed_file(
        release_root=args.release_root,
        relative_path=args.relative_path,
        source=args.source,
        expected_digest=args.expected_digest,
        backup_dir=args.backup_dir,
        commit=args.commit,
    ), sort_keys=True))


if __name__ == "__main__":
    main()
