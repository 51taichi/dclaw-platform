"""Persistent platform-Skill overlays for super experts."""

from __future__ import annotations

from pathlib import Path

from ...constant import WORKING_DIR


def super_expert_skill_overlay_root(
    agent_id: str,
    *,
    working_dir: Path = WORKING_DIR,
) -> Path:
    """Return a per-Agent Skill root outside every signed release tree."""
    base = (Path(working_dir) / "sealed_agents" / "skill_overlays").resolve()
    target = (base / agent_id).resolve()
    if target == base or not target.is_relative_to(base):
        raise ValueError("invalid super expert agent id")
    return target
