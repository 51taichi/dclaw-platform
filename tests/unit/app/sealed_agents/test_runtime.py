from __future__ import annotations

import os

import pytest

from qwenpaw.app.sealed_agents.runtime import (
    SealedRuntimeError,
    create_runtime_context,
)


def test_session_artifact_is_allowed_but_source_asset_is_denied(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "AGENTS.md").write_text("private")
    context = create_runtime_context(
        agent_id="luyu",
        session_id="session-1",
        source_root=source,
        sessions_root=tmp_path / "sessions",
    )
    artifact = context.session_root / "answer.pdf"
    artifact.write_bytes(b"answer")

    assert context.admit_artifact(artifact) == artifact.resolve()
    with pytest.raises(SealedRuntimeError):
        context.admit_artifact(source / "AGENTS.md")


def test_symlink_escape_is_denied(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    source = tmp_path / "source"
    source.mkdir()
    context = create_runtime_context(
        agent_id="luyu",
        session_id="session-1",
        source_root=source,
        sessions_root=tmp_path / "sessions",
    )
    link = context.session_root / "answer.txt"
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip("symlinks are unavailable")

    with pytest.raises(SealedRuntimeError):
        context.admit_artifact(link)


def test_session_ids_cannot_escape_working_root(tmp_path):
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(SealedRuntimeError):
        create_runtime_context(
            agent_id="../escape",
            session_id="../../escape",
            source_root=source,
            sessions_root=tmp_path / "sessions",
        )
