"""Deterministic and defensive archive utilities for trusted snapshots."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import struct
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping


class SnapshotArchiveError(ValueError):
    """Raised when a source tree cannot be exported safely."""


@dataclass(frozen=True)
class ArchiveLimits:
    max_files: int = 4096
    max_file_bytes: int = 100 * 1024 * 1024
    max_total_bytes: int = 400 * 1024 * 1024


def _normalize_path(raw_path: str) -> str:
    if not raw_path or "\\" in raw_path:
        raise SnapshotArchiveError("unsafe archive path")
    normalized = unicodedata.normalize("NFC", raw_path)
    if normalized.startswith("/") or (
        len(normalized) >= 3
        and normalized[1] == ":"
        and normalized[2] == "/"
    ):
        raise SnapshotArchiveError("unsafe archive path")
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise SnapshotArchiveError("unsafe archive path")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SnapshotArchiveError("unsafe archive path")
    return path.as_posix()


def _normalized_files(
    files: Mapping[str, bytes],
    limits: ArchiveLimits,
) -> list[tuple[str, bytes]]:
    if len(files) > limits.max_files:
        raise SnapshotArchiveError("archive has too many files")
    normalized: list[tuple[str, bytes]] = []
    seen: set[str] = set()
    total = 0
    for raw_path, raw_content in files.items():
        path = _normalize_path(raw_path)
        if path in seen:
            raise SnapshotArchiveError("duplicate normalized archive path")
        seen.add(path)
        content = bytes(raw_content)
        if len(content) > limits.max_file_bytes:
            raise SnapshotArchiveError("single file exceeds archive limit")
        total += len(content)
        if total > limits.max_total_bytes:
            raise SnapshotArchiveError("archive total size exceeds limit")
        normalized.append((path, content))
    return sorted(normalized, key=lambda item: item[0].encode("utf-8"))


def deterministic_digest(files: Mapping[str, bytes]) -> str:
    """Hash a canonical normalized path/content sequence."""
    digest = hashlib.sha256()
    for path, content in _normalized_files(files, ArchiveLimits()):
        path_bytes = path.encode("utf-8")
        digest.update(struct.pack(">Q", len(path_bytes)))
        digest.update(path_bytes)
        digest.update(struct.pack(">Q", len(content)))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def build_deterministic_archive(
    files: Mapping[str, bytes],
    *,
    limits: ArchiveLimits = ArchiveLimits(),
) -> bytes:
    """Build byte-stable ZIP bytes from a safe normalized file mapping."""
    normalized = _normalized_files(files, limits)
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path, content in normalized:
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED)
    return output.getvalue()


def _is_sensitive_name(name: str) -> bool:
    lowered = name.casefold()
    return bool(
        lowered == ".env"
        or lowered.startswith(".env.")
        or lowered in {"credentials.json", "secrets.json", "id_rsa", "id_ed25519"}
        or lowered.endswith((".pem", ".key", ".p12", ".pfx"))
    )


def collect_directory_files(
    root: Path,
    *,
    prefix: str,
    limits: ArchiveLimits = ArchiveLimits(),
) -> dict[str, bytes]:
    """Read a source directory while rejecting links, secrets, and special files."""
    root = Path(root)
    if not root.is_dir():
        raise SnapshotArchiveError("source directory is unavailable")
    resolved_root = root.resolve(strict=True)
    result: dict[str, bytes] = {}
    for candidate in sorted(root.rglob("*"), key=lambda path: path.as_posix()):
        if candidate.is_symlink():
            raise SnapshotArchiveError("source tree contains a link")
        metadata = candidate.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise SnapshotArchiveError("source tree contains a non-regular file")
        if metadata.st_nlink > 1:
            raise SnapshotArchiveError("source tree contains a hard link")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(resolved_root):
            raise SnapshotArchiveError("source tree escapes its root")
        relative = resolved.relative_to(resolved_root)
        if any(_is_sensitive_name(part) for part in relative.parts):
            raise SnapshotArchiveError("source tree contains a sensitive file")
        archive_path = PurePosixPath(prefix, *relative.parts).as_posix()
        result[archive_path] = resolved.read_bytes()
    _normalized_files(result, limits)
    return result
