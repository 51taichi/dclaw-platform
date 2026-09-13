from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from qwenpaw.app.routers import skills
from qwenpaw.agents.skill_system.pool_service import SkillPoolService


def test_workspace_inventory_exposes_super_expert_target_without_assets(
    monkeypatch,
    tmp_path,
):
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
    registry = MagicMock()
    registry.is_sealed.side_effect = lambda agent_id: agent_id == "luyu"
    registry.is_super_expert.side_effect = lambda agent_id: agent_id == "luyu"
    monkeypatch.setattr(skills, "get_sealed_agent_registry", lambda: registry)
    overlay = tmp_path / "overlays" / "luyu"
    monkeypatch.setattr(
        skills,
        "super_expert_skill_overlay_root",
        lambda agent_id: overlay,
    )
    build = MagicMock(return_value=[])
    monkeypatch.setattr(skills, "_build_workspace_skill_specs", build)

    result = asyncio.run(skills.list_workspace_skill_sources(MagicMock()))

    assert [item.agent_id for item in result] == ["ordinary", "luyu"]
    assert result[1].skills == []
    assert result[1].workspace_dir == str(overlay)
    assert [call.args[0] for call in build.call_args_list] == [ordinary, overlay]


def test_pool_download_target_rejects_normal_sealed_agent(monkeypatch):
    registry = MagicMock()
    registry.is_sealed.return_value = True
    registry.is_super_expert.return_value = False
    monkeypatch.setattr(skills, "get_sealed_agent_registry", lambda: registry)
    request = MagicMock()
    request.app.state.multi_agent_manager.get_agent = MagicMock()

    try:
        asyncio.run(
            skills._workspace_dir_for_skill_download_target("sealed", request),
        )
    except ValueError as exc:
        assert "not a super expert" in str(exc)
    else:
        raise AssertionError("normal sealed Agent must not accept Skill overlays")
    request.app.state.multi_agent_manager.get_agent.assert_not_called()


def test_pool_download_target_allows_super_expert(monkeypatch, tmp_path):
    registry = MagicMock()
    registry.is_sealed.return_value = True
    registry.is_super_expert.return_value = True
    monkeypatch.setattr(skills, "get_sealed_agent_registry", lambda: registry)
    overlay = tmp_path / "overlays" / "luyu"
    monkeypatch.setattr(
        skills,
        "super_expert_skill_overlay_root",
        lambda agent_id: overlay,
    )

    request = MagicMock()
    request.state.user_id = "admin"
    request.app.state.multi_agent_manager.get_agent = MagicMock()

    result = asyncio.run(
        skills._workspace_dir_for_skill_download_target("luyu", request),
    )

    assert result == overlay
    assert overlay.is_dir()
    request.app.state.multi_agent_manager.get_agent.assert_not_called()


def test_pool_download_reloads_each_successful_target(monkeypatch, tmp_path):
    targets = [skills.PoolDownloadTarget(workspace_id="luyu")]
    hub_service = MagicMock()
    hub_service.download_to_workspace.return_value = {
        "success": True,
        "name": "pdf",
        "workspace_name": "陆羽",
    }

    async def resolve_and_preflight(request, body):
        return targets, hub_service

    async def build_download_plan(request, selected_targets, skill_name):
        assert selected_targets == targets
        return [
            {
                "workspace_id": "luyu",
                "workspace_dir": tmp_path / "overlay",
                "snapshot": {"backup_dir": None},
            },
        ]

    monkeypatch.setattr(skills, "_resolve_and_preflight", resolve_and_preflight)
    monkeypatch.setattr(skills, "_build_download_plan", build_download_plan)
    reload_agent = MagicMock()
    monkeypatch.setattr(skills, "schedule_agent_reload", reload_agent)
    request = MagicMock()
    body = skills.DownloadFromPoolRequest(skill_name="pdf")

    result = asyncio.run(skills.download_pool_skill_to_workspaces(request, body))

    assert result == {
        "downloaded": [
            {"workspace_id": "luyu", "workspace_name": "陆羽", "name": "pdf"},
        ],
    }
    reload_agent.assert_called_once_with(request, "luyu")


def test_default_skill_fanout_uses_super_overlay_and_skips_normal_sealed(
    monkeypatch,
    tmp_path,
):
    ordinary = tmp_path / "ordinary"
    sealed = tmp_path / "sealed"
    super_runtime = tmp_path / "super-runtime"
    overlay = tmp_path / "overlays" / "luyu"
    workspaces = [
        {"agent_id": "ordinary", "workspace_dir": str(ordinary)},
        {"agent_id": "sealed", "workspace_dir": str(sealed)},
        {"agent_id": "luyu", "workspace_dir": str(super_runtime)},
    ]
    monkeypatch.setattr(skills, "list_workspaces", lambda: workspaces)
    registry = MagicMock()
    registry.is_sealed.side_effect = lambda agent_id: agent_id != "ordinary"
    registry.is_super_expert.side_effect = lambda agent_id: agent_id == "luyu"
    monkeypatch.setattr(skills, "get_sealed_agent_registry", lambda: registry)
    monkeypatch.setattr(
        skills,
        "super_expert_skill_overlay_root",
        lambda agent_id: overlay,
    )
    service = MagicMock()
    service.download_to_workspace.return_value = {"success": True}
    monkeypatch.setattr(skills, "SkillPoolService", lambda: service)
    reload_agent = MagicMock()
    monkeypatch.setattr(skills, "schedule_agent_reload", reload_agent)
    request = MagicMock()

    skills._sync_default_skill_to_all_workspaces("pdf", request)

    assert [call.kwargs["workspace_dir"] for call in service.download_to_workspace.call_args_list] == [
        ordinary,
        overlay,
    ]
    assert all(
        call.kwargs["workspace_dir"] not in {sealed, super_runtime}
        for call in service.download_to_workspace.call_args_list
    )
    assert [call.args[1] for call in reload_agent.call_args_list] == [
        "ordinary",
        "luyu",
    ]


def test_pool_delete_uses_super_overlay_and_skips_normal_sealed(
    monkeypatch,
    tmp_path,
):
    ordinary = tmp_path / "ordinary"
    sealed = tmp_path / "sealed"
    super_runtime = tmp_path / "super-runtime"
    overlay = tmp_path / "overlays" / "luyu"
    monkeypatch.setattr(
        skills,
        "list_workspaces",
        lambda: [
            {"agent_id": "ordinary", "workspace_dir": str(ordinary)},
            {"agent_id": "sealed", "workspace_dir": str(sealed)},
            {"agent_id": "luyu", "workspace_dir": str(super_runtime)},
        ],
    )
    registry = MagicMock()
    registry.is_sealed.side_effect = lambda agent_id: agent_id != "ordinary"
    registry.is_super_expert.side_effect = lambda agent_id: agent_id == "luyu"
    monkeypatch.setattr(skills, "get_sealed_agent_registry", lambda: registry)
    monkeypatch.setattr(
        skills,
        "super_expert_skill_overlay_root",
        lambda agent_id: overlay,
    )
    pool = MagicMock()
    pool.delete_skill.return_value = True
    monkeypatch.setattr(skills, "SkillPoolService", lambda: pool)
    services = []

    def skill_service(path):
        service = MagicMock()
        service.path = Path(path)
        services.append(service)
        return service

    monkeypatch.setattr(skills, "SkillService", skill_service)
    monkeypatch.setattr(skills, "_require_pool_skill_access", MagicMock())
    reload_agent = MagicMock()
    monkeypatch.setattr(skills, "schedule_agent_reload", reload_agent)
    request = MagicMock()

    result = asyncio.run(skills.delete_pool_skill(request, "pdf"))

    assert result == {"deleted": True}
    assert [service.path for service in services] == [ordinary, overlay]
    assert all(service.path not in {sealed, super_runtime} for service in services)
    assert [call.args[1] for call in reload_agent.call_args_list] == [
        "ordinary",
        "luyu",
    ]


def test_hub_install_reloads_enabled_skill(monkeypatch, tmp_path):
    result = SimpleNamespace(
        name="pdf",
        enabled=True,
        source_url="https://example.invalid/pdf.zip",
    )
    monkeypatch.setattr(skills, "install_skill_from_hub", lambda **kwargs: result)

    async def set_status(*args, **kwargs):
        return None

    monkeypatch.setattr(skills, "_hub_task_set_status", set_status)
    reload_agent = MagicMock()
    monkeypatch.setattr(skills, "schedule_agent_reload", reload_agent)
    request = MagicMock()

    asyncio.run(
        skills._run_hub_install_task(
            task_id="task-1",
            workspace_dir=tmp_path,
            body=skills.HubInstallRequest(
                bundle_url=result.source_url,
                enable=True,
            ),
            cancel_event=__import__("threading").Event(),
            request=request,
            agent_id="luyu",
        ),
    )

    reload_agent.assert_called_once_with(request, "luyu")


def test_service_default_distribution_uses_super_overlay(
    monkeypatch,
    tmp_path,
):
    from qwenpaw.agents.skill_system import registry as skill_registry
    from qwenpaw.app.sealed_agents import registry as sealed_registry_module
    from qwenpaw.app.sealed_agents import skill_overlay

    ordinary = tmp_path / "ordinary"
    sealed = tmp_path / "sealed"
    super_runtime = tmp_path / "super-runtime"
    overlay = tmp_path / "overlay"
    monkeypatch.setattr(
        skill_registry,
        "list_workspaces",
        lambda: [
            {"agent_id": "ordinary", "workspace_dir": str(ordinary)},
            {"agent_id": "sealed", "workspace_dir": str(sealed)},
            {"agent_id": "luyu", "workspace_dir": str(super_runtime)},
        ],
    )
    registry = MagicMock()
    registry.is_sealed.side_effect = lambda agent_id: agent_id != "ordinary"
    registry.is_super_expert.side_effect = lambda agent_id: agent_id == "luyu"
    monkeypatch.setattr(
        sealed_registry_module,
        "get_sealed_agent_registry",
        lambda: registry,
    )
    monkeypatch.setattr(
        skill_overlay,
        "super_expert_skill_overlay_root",
        lambda agent_id: overlay,
    )
    service = SkillPoolService.__new__(SkillPoolService)
    install = MagicMock(return_value=[])
    service.install_default_skills_to_workspace = install

    result = service.install_default_skills_to_all_workspaces()

    assert result == []
    assert [call.args[0] for call in install.call_args_list] == [
        ordinary,
        overlay,
    ]
