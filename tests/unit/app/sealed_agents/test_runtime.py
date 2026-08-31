from __future__ import annotations

import os

import pytest

from qwenpaw.app.sealed_agents.runtime import (
    SealedRuntimeError,
    create_runtime_context,
    resolve_pinned_runtime,
    resolve_pinned_release,
)
from qwenpaw.app.sealed_agents.models import SealedAgentRecord, SealedReleaseRecord
from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry


def _release(
    release_id: str,
    *,
    adapter: str | None = None,
    entrypoint: str | None = "agent/agent.json",
) -> SealedReleaseRecord:
    return SealedReleaseRecord(
        release_id=release_id,
        version="1.0.0",
        content_digest=f"sha256:{'a' * 64}",
        signer_id="publisher",
        state="active",
        entrypoint=entrypoint,
        runtime_adapter=adapter,
        runtime_contract_version="1" if adapter else None,
        runtime_failure_policy="fail_closed" if adapter else None,
    )


def _record(release: SealedReleaseRecord) -> SealedAgentRecord:
    return SealedAgentRecord(
        agent_id="sealed",
        name="Sealed",
        active_release_id=release.release_id,
        releases=[release],
    )


def test_standard_agent_has_no_pinned_runtime(tmp_path):
    registry = SealedAgentRegistry(tmp_path)

    assert resolve_pinned_runtime("ordinary", registry) is None


def test_v1_sealed_agent_pins_standard_runtime(tmp_path):
    registry = SealedAgentRegistry(tmp_path)
    registry.upsert_agent(_record(_release("v1", entrypoint=None)))

    pinned = resolve_pinned_runtime("sealed", registry)

    assert pinned is not None
    assert pinned.adapter_key == ("standard", "1")
    assert pinned.entrypoint == "agent/agent.json"


def test_harness_release_identity_is_copied_not_live(tmp_path):
    registry = SealedAgentRegistry(tmp_path)
    old = _release("old-release", adapter="sealed_harness")
    registry.upsert_agent(_record(old))

    pinned = resolve_pinned_runtime("sealed", registry)
    new = _release("new-release", adapter="sealed_harness")
    registry.upsert_agent(_record(new))

    assert pinned is not None
    assert pinned.release_id == "old-release"
    assert pinned.content_digest == f"sha256:{'a' * 64}"


def test_explicit_release_pin_survives_active_release_switch(tmp_path):
    registry = SealedAgentRegistry(tmp_path)
    old = _release("old-release", adapter="sealed_harness")
    new = _release("new-release", adapter="sealed_harness")
    registry.upsert_agent(
        SealedAgentRecord(
            agent_id="sealed",
            name="Sealed",
            active_release_id=new.release_id,
            releases=[old, new],
        ),
    )

    pinned = resolve_pinned_release("sealed", old.release_id, registry)

    assert pinned.release_id == "old-release"


def test_entrypoint_escape_is_rejected_when_pinning(tmp_path):
    registry = SealedAgentRegistry(tmp_path)
    registry.upsert_agent(_record(_release("bad", entrypoint="../escape.py")))

    with pytest.raises(SealedRuntimeError, match="entrypoint"):
        resolve_pinned_runtime("sealed", registry)


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
