"""Validation for sealed releases executed as standard Agent workspaces."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from ...config.config import AgentProfileConfig


class StandardWorkspaceError(ValueError):
    """Stable, path-free validation failure for a standard workspace."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def validate_standard_workspace(
    agent_id: str,
    workspace_root: Path,
) -> AgentProfileConfig:
    """Validate the ordinary ``agent.json`` contract without mutating files."""

    root = Path(workspace_root)
    try:
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise StandardWorkspaceError("workspace_missing") from exc
    if not resolved_root.is_dir():
        raise StandardWorkspaceError("workspace_missing")

    agent_config_path = root / "agent.json"
    if agent_config_path.is_symlink():
        raise StandardWorkspaceError("unsafe_agent_config")
    try:
        resolved_config = agent_config_path.resolve(strict=True)
    except OSError as exc:
        raise StandardWorkspaceError("agent_config_missing") from exc
    if (
        not resolved_config.is_relative_to(resolved_root)
        or not resolved_config.is_file()
    ):
        raise StandardWorkspaceError("unsafe_agent_config")

    try:
        payload = json.loads(resolved_config.read_text(encoding="utf-8"))
        profile = AgentProfileConfig.model_validate(payload)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValidationError,
        TypeError,
    ) as exc:
        raise StandardWorkspaceError("agent_config_invalid") from exc
    if profile.id != agent_id:
        raise StandardWorkspaceError("agent_id_mismatch")
    return profile
