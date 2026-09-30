from __future__ import annotations

import io
import os
import zipfile

import pytest

from qwenpaw.app.config_patch_participant.archive import (
    ArchiveLimits,
    SnapshotArchiveError,
    build_deterministic_archive,
    collect_directory_files,
)


def test_archive_is_byte_stable_and_uses_fixed_safe_metadata():
    first = build_deterministic_archive(
        {"资料/说明.md": b"hello", "agent/agent.json": b"{}"},
    )
    second = build_deterministic_archive(
        {"agent/agent.json": b"{}", "资料/说明.md": b"hello"},
    )

    assert first == second
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert archive.namelist() == ["agent/agent.json", "资料/说明.md"]
        for info in archive.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.external_attr >> 16 == 0o100644
            assert info.create_system == 3


@pytest.mark.parametrize(
    "path",
    [
        "/absolute.txt",
        "../escape.txt",
        "agent/../../escape.txt",
        "agent\\agent.json",
        "C:/windows.txt",
        "./relative.txt",
    ],
)
def test_archive_rejects_unsafe_member_paths(path: str):
    with pytest.raises(SnapshotArchiveError, match="unsafe archive path"):
        build_deterministic_archive({path: b"data"})


def test_archive_rejects_duplicate_unicode_normalized_paths():
    with pytest.raises(SnapshotArchiveError, match="duplicate normalized"):
        build_deterministic_archive(
            {"knowledge/café.txt": b"one", "knowledge/cafe\u0301.txt": b"two"},
        )


def test_archive_enforces_member_and_size_limits_without_large_fixtures():
    limits = ArchiveLimits(max_files=1, max_file_bytes=4, max_total_bytes=6)

    with pytest.raises(SnapshotArchiveError, match="too many files"):
        build_deterministic_archive({"one": b"1", "two": b"2"}, limits=limits)
    with pytest.raises(SnapshotArchiveError, match="single file"):
        build_deterministic_archive({"one": b"12345"}, limits=limits)
    with pytest.raises(SnapshotArchiveError, match="total size"):
        build_deterministic_archive(
            {"one": b"1234", "two": b"123"},
            limits=ArchiveLimits(max_files=2, max_file_bytes=4, max_total_bytes=6),
        )


def test_directory_collection_rejects_symlinks(tmp_path):
    (tmp_path / "real.txt").write_text("real", encoding="utf-8")
    (tmp_path / "linked.txt").symlink_to(tmp_path / "real.txt")

    with pytest.raises(SnapshotArchiveError, match="link"):
        collect_directory_files(tmp_path, prefix="agent")


def test_directory_collection_rejects_hardlinks(tmp_path):
    source = tmp_path / "source.txt"
    source.write_text("real", encoding="utf-8")
    os.link(source, tmp_path / "hardlink.txt")

    with pytest.raises(SnapshotArchiveError, match="hard link"):
        collect_directory_files(tmp_path, prefix="agent")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unsupported")
def test_directory_collection_rejects_device_like_special_files(tmp_path):
    os.mkfifo(tmp_path / "pipe")

    with pytest.raises(SnapshotArchiveError, match="regular file"):
        collect_directory_files(tmp_path, prefix="agent")

