# -*- coding: utf-8 -*-
"""Regression tests for per-chat artifact recovery."""

from pathlib import Path
from types import SimpleNamespace

from qwenpaw.app.runner.api import (
    _recover_explicit_artifacts_from_messages,
    _scan_session_files,
)


def test_scan_session_files_does_not_import_unrelated_root_files(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    session_dir = workspace / "sessions_data" / "session-1"
    session_dir.mkdir(parents=True)
    (session_dir / "BOOTSTRAP.md").write_text("internal", encoding="utf-8")
    (workspace / "snake-game.html").write_text("<html></html>", encoding="utf-8")
    (workspace / "儿童节短剧_最好的礼物.md").write_text("# 最好的礼物", encoding="utf-8")

    assert _scan_session_files(workspace, "session-1") == []


def test_scan_session_files_does_not_treat_uploaded_sources_as_outputs(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    source_dir = workspace / "sessions_data" / "session-1" / "命理学习" / "补充资料"
    source_dir.mkdir(parents=True)
    (source_dir / "用户上传.pdf").write_text("uploaded source", encoding="utf-8")

    assert _scan_session_files(workspace, "session-1") == []


def test_recover_explicit_artifacts_ignores_user_uploaded_attachments(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    upload = workspace / "命理学习" / "补充资料" / "用户上传.pdf"
    upload.parent.mkdir(parents=True)
    upload.write_text("uploaded source", encoding="utf-8")
    output = workspace / "考勤统计.xlsx"
    output.write_text("generated report", encoding="utf-8")

    messages = [
        SimpleNamespace(
            role="user",
            content=f"请处理这个文件：📎 [用户上传.pdf]({upload})",
        ),
        SimpleNamespace(
            role="assistant",
            content="已完成，saved as `考勤统计.xlsx`",
        ),
    ]

    assert _recover_explicit_artifacts_from_messages(messages, workspace) == [
        "考勤统计.xlsx",
    ]
