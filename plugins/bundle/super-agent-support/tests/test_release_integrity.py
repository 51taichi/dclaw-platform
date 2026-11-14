from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from qwenpaw.app.sealed_agents.package import (
    SealedPackageError,
    inspect_extracted_payload,
)
from super_agent import release_integrity


def _release(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "sealed" / "releases" / "expert" / "release"
    source = root / "agent" / "_vendor" / "package" / "__init__.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"signed source")
    digest, _ = inspect_extracted_payload(root)
    return root, digest


def _cache(root: Path, name: str = "__init__.cpython-311.pyc") -> Path:
    path = root / "agent" / "_vendor" / "package" / "__pycache__" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"unsigned bytecode")
    return path


def test_unsigned_cache_is_quarantined_and_repeated_check_is_stable(tmp_path):
    root, digest = _release(tmp_path)
    cache = _cache(root)
    result = release_integrity.inspect_signed_release(root, digest)
    assert result[0] == digest
    assert not cache.exists()
    assert inspect_extracted_payload(root)[0] == digest
    quarantine = root.parents[2] / "release_cache_quarantine"
    assert len(list(quarantine.rglob("*.pyc"))) == 1
    assert release_integrity.inspect_signed_release(root, digest) == result


def test_real_tamper_and_unknown_extra_file_fail_closed(tmp_path):
    root, digest = _release(tmp_path)
    cache = _cache(root)
    source = root / "agent" / "_vendor" / "package" / "__init__.py"
    source.write_bytes(b"tampered source")
    assert release_integrity.inspect_signed_release(root, digest)[0] != digest
    assert cache.exists()
    source.write_bytes(b"signed source")
    extra = root / "agent" / "unexpected.txt"
    extra.write_bytes(b"extra")
    assert release_integrity.inspect_signed_release(root, digest)[0] != digest
    assert cache.exists()


def test_signed_bytecode_is_not_removed(tmp_path):
    root, _ = _release(tmp_path)
    signed_cache = _cache(root)
    digest, _ = inspect_extracted_payload(root)
    assert release_integrity.inspect_signed_release(root, digest)[0] == digest
    assert signed_cache.read_bytes() == b"unsigned bytecode"


def test_symlink_and_cache_without_source_are_not_quarantined(tmp_path):
    root, digest = _release(tmp_path)
    link = root / "agent" / "link"
    link.symlink_to("_vendor")
    with pytest.raises(SealedPackageError):
        release_integrity.inspect_signed_release(root, digest)
    link.unlink()
    orphan = _cache(root, "missing.cpython-311.pyc")
    assert release_integrity.inspect_signed_release(root, digest)[0] != digest
    assert orphan.exists()


def test_parallel_checks_and_interrupted_quarantine_recover(tmp_path, monkeypatch):
    root, _ = _release(tmp_path)
    second = root / "agent" / "__pycache__" / "runtime.cpython-311.pyc"
    second.parent.mkdir(parents=True)
    (root / "agent" / "runtime.py").write_bytes(b"runtime")
    digest, _ = inspect_extracted_payload(root)
    first = _cache(root)
    second.write_bytes(b"bytecode")
    original_replace = release_integrity.os.replace
    calls = 0

    def interrupted(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("interrupted move")
        original_replace(source, target)

    monkeypatch.setattr(release_integrity.os, "replace", interrupted)
    with pytest.raises(OSError, match="interrupted move"):
        release_integrity.inspect_signed_release(root, digest)
    monkeypatch.setattr(release_integrity.os, "replace", original_replace)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda _: release_integrity.inspect_signed_release(root, digest),
            range(8),
        ))
    assert all(result[0] == digest for result in results)
    assert not first.exists() and not second.exists()
