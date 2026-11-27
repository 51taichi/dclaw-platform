"""Verify signed releases and quarantine only proven unsigned Python caches."""

from __future__ import annotations

import fcntl
import hashlib
import logging
import os
import re
import struct
import uuid
from pathlib import Path

from qwenpaw.app.sealed_agents.package import (
    SealedPackageError,
    inspect_extracted_payload,
)


_CACHE_NAME = re.compile(r"(.+)\.cpython-\d+(?:\.opt-\d+)?\.pyc\Z")
logger = logging.getLogger(__name__)


def _unsigned_cache_paths(root: Path, files: frozenset[str]) -> frozenset[str]:
    caches: set[str] = set()
    for relative in files:
        path = Path(relative)
        if path.parent.name != "__pycache__":
            continue
        match = _CACHE_NAME.fullmatch(path.name)
        if match is None:
            continue
        source = (path.parent.parent / f"{match.group(1)}.py").as_posix()
        if source in files and (root / source).is_file():
            caches.add(relative)
    return frozenset(caches)


def _digest_without(root: Path, files: frozenset[str], excluded: frozenset[str]) -> str:
    digest = hashlib.sha256()
    for relative in sorted(files - excluded, key=lambda value: value.encode("utf-8")):
        if relative in {"manifest.json", "signature.json"}:
            continue
        path_bytes = relative.encode("utf-8")
        candidate = root / relative
        size = candidate.stat().st_size
        digest.update(struct.pack(">Q", len(path_bytes)))
        digest.update(path_bytes)
        digest.update(struct.pack(">Q", size))
        with candidate.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def inspect_signed_release(
    release_root: Path, expected_digest: str,
) -> tuple[str, frozenset[str]]:
    """Keep the core's strict check; move only caches proven absent from the signature."""
    root = Path(release_root).resolve(strict=True)
    sealed_root = root.parents[2]
    lock_root = sealed_root / "release_cache_quarantine"
    lock_root.mkdir(mode=0o700, exist_ok=True)
    key = hashlib.sha256(os.fsencode(root)).hexdigest()
    with (lock_root / f"{key}.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        actual, files = inspect_extracted_payload(root)
        if actual == expected_digest:
            return actual, files
        caches = _unsigned_cache_paths(root, files)
        if not caches or _digest_without(root, files, caches) != expected_digest:
            return actual, files
        quarantine = lock_root / key / uuid.uuid4().hex
        quarantine.mkdir(mode=0o700, parents=True)
        for relative in sorted(caches):
            source = root / relative
            target = quarantine / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.replace(source, target)
        verified, signed_files = inspect_extracted_payload(root)
        if verified != expected_digest:
            raise SealedPackageError("sealed release changed during cache quarantine")
        logger.info(
            "quarantined %d unsigned Python caches from signed release %s",
            len(caches), key,
        )
        return verified, signed_files
