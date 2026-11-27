"""Isolated mutable workspaces for immutable signed Agent releases."""

from __future__ import annotations

import os
import json
import shutil
import uuid
from pathlib import Path


def _synchronize_runtime_agent_config(source: Path, target: Path) -> None:
    """Keep signed Agent configuration authoritative in the mutable copy."""
    payload = json.loads((source / "agent.json").read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("agent.json must contain an object")
    payload["workspace_dir"] = str(target)
    temporary = target / f".agent-{uuid.uuid4().hex}.json.tmp"
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target / "agent.json")


def _synchronize_signed_files(source: Path, target: Path) -> None:
    """Restore signed files while leaving runtime-only state untouched."""
    for candidate in source.rglob("*"):
        if candidate.is_symlink():
            raise ValueError("signed workspace contains a symlink")
        relative = candidate.relative_to(source)
        destination = target / relative
        if candidate.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif relative.as_posix() != "agent.json":
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, destination)


def runtime_workspace_root(
    sealed_root: Path,
    agent_id: str,
    release_id: str,
) -> Path:
    return Path(sealed_root) / "runtime_workspaces" / agent_id / release_id / "agent"


def ensure_runtime_workspace(
    sealed_root: Path,
    agent_id: str,
    release_id: str,
) -> Path:
    """Materialize a mutable copy once without ever changing the signed source."""
    target = runtime_workspace_root(sealed_root, agent_id, release_id)
    source = Path(sealed_root) / "releases" / agent_id / release_id / "agent"
    if not source.is_dir():
        raise FileNotFoundError(source)
    if not target.is_dir():
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / f".agent-{uuid.uuid4().hex}.tmp"
        try:
            shutil.copytree(source, temporary)
            try:
                os.replace(temporary, target)
            except OSError:
                if not target.is_dir():
                    raise
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
    _synchronize_signed_files(source, target)
    _synchronize_runtime_agent_config(source, target)
    return target
