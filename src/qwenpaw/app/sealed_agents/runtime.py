"""Filesystem boundary for sealed agent sessions and caller artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

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
