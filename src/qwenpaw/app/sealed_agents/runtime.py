"""Filesystem boundary for sealed agent sessions and caller artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .registry import SealedAgentRegistry

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_MAX_ARTIFACT_BYTES = 100 * 1024 * 1024


class SealedRuntimeError(ValueError):
    """A model-selected path crossed the sealed runtime boundary."""


@dataclass(frozen=True)
class SealedRuntimeContext:
    agent_id: str
    session_id: str
    source_root: Path
    session_root: Path

    def admit_artifact(self, candidate: Path) -> Path:
        candidate = Path(candidate)
        if candidate.is_symlink():
            raise SealedRuntimeError("sealed artifact links are not allowed")
        resolved = candidate.resolve()
        session_root = self.session_root.resolve()
        source_root = self.source_root.resolve()
        if not resolved.is_relative_to(session_root):
            raise SealedRuntimeError("sealed artifact is outside the session")
        if resolved.is_relative_to(source_root):
            raise SealedRuntimeError("sealed source assets cannot be returned")
        if not resolved.is_file():
            raise SealedRuntimeError("sealed artifact must be a regular file")
        if resolved.stat().st_size > _MAX_ARTIFACT_BYTES:
            raise SealedRuntimeError("sealed artifact exceeds size limit")
        return resolved


@dataclass(frozen=True)
class PinnedSealedRuntime:
    agent_id: str
    release_id: str
    version: str
    content_digest: str
    release_root: Path
    entrypoint: str
    adapter_key: tuple[str, str]
    failure_policy: str


def resolve_adapter_session_root(
    pinned: PinnedSealedRuntime | None,
    *,
    session_id: str,
    sessions_root: Path,
) -> Path | None:
    if pinned is None or pinned.adapter_key != ("sealed_entrypoint", "1"):
        return None
    return create_runtime_context(
        agent_id=pinned.agent_id,
        session_id=session_id,
        source_root=pinned.release_root,
        sessions_root=sessions_root,
    ).session_root


def resolve_pinned_runtime(
    agent_id: str,
    registry: SealedAgentRegistry,
) -> PinnedSealedRuntime | None:
    from .adapters import get_runtime_adapter

    record = registry.get_agent(agent_id)
    if record is None:
        return None
    if not record.enabled or record.active_release is None:
        raise SealedRuntimeError("sealed agent has no enabled active release")

    release = record.active_release
    adapter_key = (
        release.runtime_adapter or "standard",
        release.runtime_contract_version or "1",
    )
    get_runtime_adapter(*adapter_key)
    failure_policy = release.runtime_failure_policy or "fail_closed"
    entrypoint = release.entrypoint or "agent/agent.json"
    release_root = (
        registry.root / "releases" / record.agent_id / release.release_id
    ).resolve()
    entrypoint_path = (release_root / entrypoint).resolve()
    if not entrypoint_path.is_relative_to(release_root):
        raise SealedRuntimeError("sealed runtime entrypoint escapes release root")

    return PinnedSealedRuntime(
        agent_id=record.agent_id,
        release_id=release.release_id,
        version=release.version,
        content_digest=release.content_digest,
        release_root=release_root,
        entrypoint=entrypoint,
        adapter_key=adapter_key,
        failure_policy=failure_policy,
    )


def resolve_pinned_release(
    agent_id: str,
    release_id: str,
    registry: SealedAgentRegistry,
) -> PinnedSealedRuntime:
    record = registry.get_agent(agent_id)
    if record is None:
        raise SealedRuntimeError("sealed agent is unavailable")
    if release_id not in {item.release_id for item in record.releases}:
        raise SealedRuntimeError("sealed runtime release is unavailable")
    pinned_record = record.model_copy(update={"active_release_id": release_id})

    class _PinnedRegistry:
        root = registry.root

        @staticmethod
        def get_agent(candidate: str):
            return pinned_record if candidate == agent_id else None

    pinned = resolve_pinned_runtime(agent_id, _PinnedRegistry())  # type: ignore[arg-type]
    if pinned is None:
        raise SealedRuntimeError("sealed runtime release is unavailable")
    return pinned


def create_runtime_context(
    *,
    agent_id: str,
    session_id: str,
    source_root: Path,
    sessions_root: Path,
) -> SealedRuntimeContext:
    if not _SAFE_ID.fullmatch(agent_id) or not _SAFE_ID.fullmatch(session_id):
        raise SealedRuntimeError("invalid sealed runtime identity")
    sessions_root = Path(sessions_root).resolve()
    session_root = (sessions_root / agent_id / session_id).resolve()
    if not session_root.is_relative_to(sessions_root):
        raise SealedRuntimeError("invalid sealed session path")
    session_root.mkdir(parents=True, exist_ok=True)
    return SealedRuntimeContext(
        agent_id=agent_id,
        session_id=session_id,
        source_root=Path(source_root).resolve(),
        session_root=session_root,
    )
