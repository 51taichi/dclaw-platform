# -*- coding: utf-8 -*-
"""Tests for Mindspace workspace resolution from standalone pages."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app.routers import workspace as workspace_router


@pytest.mark.asyncio
async def test_mindspace_service_does_not_require_chat_id_for_user_page(
    tmp_path,
    monkeypatch,
) -> None:
    agent_workspace = (tmp_path / "agent").resolve()
    agent_workspace.mkdir()
    global_root = tmp_path / "global"

    async def fake_get_agent_for_request(request):
        return SimpleNamespace(id="agent-a", workspace_dir=str(agent_workspace))

    monkeypatch.setattr(
        workspace_router,
        "get_agent_for_request",
        fake_get_agent_for_request,
    )
    monkeypatch.setattr(workspace_router, "_mindspace_global_root", lambda: global_root)
    monkeypatch.setattr(workspace_router, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(workspace_router, "is_admin_request", lambda request: False)

    request = SimpleNamespace(
        state=SimpleNamespace(user_id="42", role="user"),
        query_params={},
        headers={},
    )

    service = await workspace_router._mindspace_service_for_request(request)

    assert service.agent_workspace == agent_workspace
    assert service.agent_root == agent_workspace / "mindspace"
