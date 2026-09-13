from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from qwenpaw.app.routers import skills


def test_workspace_inventory_excludes_sealed_agent_assets(monkeypatch, tmp_path):
    ordinary = tmp_path / "ordinary"
    sealed = tmp_path / "sealed"
    ordinary.mkdir()
    sealed.mkdir()
    monkeypatch.setattr(
        skills,
        "list_workspaces",
        lambda: [
            {
                "agent_id": "ordinary",
                "agent_name": "普通专家",
                "workspace_dir": str(ordinary),
            },
            {
                "agent_id": "luyu",
                "agent_name": "陆羽",
                "workspace_dir": str(sealed),
            },
        ],
    )
    monkeypatch.setattr(
        skills,
        "get_sealed_agent_registry",
        lambda: MagicMock(is_sealed=lambda agent_id: agent_id == "luyu"),
        raising=False,
    )
    build = MagicMock(return_value=[])
    monkeypatch.setattr(skills, "_build_workspace_skill_specs", build)

    result = asyncio.run(skills.list_workspace_skill_sources(MagicMock()))

    assert [item.agent_id for item in result] == ["ordinary"]
    build.assert_called_once()
