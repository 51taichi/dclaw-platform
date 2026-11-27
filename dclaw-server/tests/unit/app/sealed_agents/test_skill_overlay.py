from __future__ import annotations

import pytest

from qwenpaw.app.sealed_agents.skill_overlay import (
    super_expert_skill_overlay_root,
)


def test_super_expert_skill_overlay_survives_release_changes(tmp_path):
    first = super_expert_skill_overlay_root("luyu", working_dir=tmp_path)
    second = super_expert_skill_overlay_root("luyu", working_dir=tmp_path)

    assert first == second
    assert "runtime_workspaces" not in first.parts
    assert first == tmp_path / "sealed_agents" / "skill_overlays" / "luyu"


@pytest.mark.parametrize("agent_id", ["../escape", "/absolute", ""])
def test_super_expert_skill_overlay_rejects_path_escape(tmp_path, agent_id):
    with pytest.raises(ValueError, match="invalid sealed extension agent id"):
        super_expert_skill_overlay_root(agent_id, working_dir=tmp_path)
