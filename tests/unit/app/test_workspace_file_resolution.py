# -*- coding: utf-8 -*-
"""Tests for session-aware workspace file resolution."""

from pathlib import Path

from qwenpaw.app.routers.workspace import resolve_workspace_file_for_read


def test_session_file_resolution_falls_back_to_root_deliverable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    session_dir = root / "sessions_data" / "session-1"
    session_dir.mkdir(parents=True)
    deliverable = root / "儿童节短剧_最好的礼物.md"
    deliverable.write_text("# 最好的礼物", encoding="utf-8")

    resolved = resolve_workspace_file_for_read(
        session_dir,
        "儿童节短剧_最好的礼物.md",
    )

    assert resolved == deliverable.resolve()


def test_session_file_resolution_does_not_fall_back_to_internal_cache(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    session_dir = root / "sessions_data" / "session-1"
    session_dir.mkdir(parents=True)
    cache = root / "tool_results" / "result.txt"
    cache.parent.mkdir()
    cache.write_text("debug output", encoding="utf-8")

    resolved = resolve_workspace_file_for_read(session_dir, "tool_results/result.txt")

    assert resolved == (session_dir / "tool_results/result.txt").resolve()
