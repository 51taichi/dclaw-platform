"""Persistent platform-Skill overlays for sealed extension packages."""

from __future__ import annotations

from pathlib import Path

from ...constant import WORKING_DIR


def sealed_skill_overlay_root(
    agent_id: str,
    *,
    working_dir: Path = WORKING_DIR,
) -> Path:
    """Return a per-Agent Skill root outside every signed release tree."""
    base = (Path(working_dir) / "sealed_agents" / "skill_overlays").resolve()
    target = (base / agent_id).resolve()
    if target == base or not target.is_relative_to(base):
        raise ValueError("invalid sealed extension agent id")
    return target


def super_expert_skill_overlay_root(
    agent_id: str,
    *,
    working_dir: Path = WORKING_DIR,
) -> Path:
    """Compatibility alias for the generic sealed Skill overlay."""
    return sealed_skill_overlay_root(agent_id, working_dir=working_dir)
