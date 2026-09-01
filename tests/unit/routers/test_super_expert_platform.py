from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import super_expert_platform as router_module
from qwenpaw.app.routers.super_expert_platform import (
    PlatformCommandRequest,
    SuperExpertPlatformError,
    SuperExpertPlatformService,
)
from qwenpaw.app.sealed_agents.models import SealedReleaseRecord
from qwenpaw.app.super_experts.aigc_tasks import AigcTaskRepository
from qwenpaw.app.super_experts.events import SuperExpertEventRepository
from qwenpaw.app.super_experts.grants import SuperExpertGrantRepository


CAPABILITIES = (
    ("aigc.task.create", "1"),
    ("aigc.task.resume", "1"),
    ("aigc.task.cancel", "1"),
    ("aigc.guide.update", "1"),
    ("aigc.asset.submit", "1"),
    ("aigc.review.complete", "1"),
    ("card.create", "1"),
    ("card.update", "1"),
)


def _release():
    return SealedReleaseRecord(
        release_id="release-1",
        version="1.0.0",
        content_digest=f"sha256:{'a' * 64}",
        signer_id="official",
        package_type="super_expert",
        capability_digest=f"sha256:{'b' * 64}",
        declared_capabilities=CAPABILITIES,
        orchestration_capability_id="workspace.turn.orchestrate/1",
        orchestration_contract_version="1",
    )


def _binding():
    return {
        "installation_id": "placeholder",
        "conversation_id": "conversation-1",
        "agent_task_id": "agent-task-1",
        "content_revision": 3,
        "material_task_id": "material-1",
        "canvas_id": "canvas-1",
        "node_id": "node-1",
    }


class Bus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)
        return event


def _service(tmp_path):
    grants = SuperExpertGrantRepository(tmp_path / "grants")
    preview = grants.preview("agent-1", _release(), tenant_id="tenant-a")
    grant = grants.grant_installation(preview, administrator_id="admin-1")
    bus = Bus()
    service = SuperExpertPlatformService(
        grant_repository=grants,
        task_repository=AigcTaskRepository(tmp_path / "tasks"),
        event_repository=SuperExpertEventRepository(tmp_path / "events"),
        event_bus=bus,
    )
    return service, grant, bus


@pytest.mark.asyncio
async def test_authorized_command_validates_full_binding_and_publishes_once(tmp_path):
    service, grant, bus = _service(tmp_path)
    binding = _binding()
    binding["installation_id"] = grant.installation_id

    first = await service.execute(
        tenant_id="tenant-a",
        installation_id=grant.installation_id,
        capability="aigc.task.create",
        contract_version="1",
        arguments={"binding": binding, "event_id": "event-1"},
        idempotency_key="key-1",
    )
    replay = await service.execute(
        tenant_id="tenant-a",
        installation_id=grant.installation_id,
        capability="aigc.task.create",
        contract_version="1",
        arguments={"binding": binding, "event_id": "event-1"},
        idempotency_key="key-1",
    )

    assert first == replay
    assert first["task"]["status"] == "WAITING_TO_START"
    assert len(bus.events) == 1
    envelope = bus.events[0].payload["envelope"]
    assert envelope["installation_id"] == grant.installation_id
    assert envelope["content_revision"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tenant_id", "installation_id", "version"),
    [
        ("tenant-b", "valid", "1"),
        ("tenant-a", "missing", "1"),
        ("tenant-a", "valid", "2"),
    ],
)
async def test_ordinary_cross_tenant_or_wrong_version_call_is_denied(
    tmp_path,
    tenant_id,
    installation_id,
    version,
):
    service, grant, _bus = _service(tmp_path)
    resolved_installation = (
        grant.installation_id if installation_id == "valid" else installation_id
    )
    binding = _binding()
    binding["installation_id"] = resolved_installation

    with pytest.raises(SuperExpertPlatformError, match="authorized"):
        await service.execute(
            tenant_id=tenant_id,
            installation_id=resolved_installation,
            capability="aigc.task.create",
            contract_version=version,
            arguments={"binding": binding, "event_id": "event-1"},
            idempotency_key="key-1",
        )


@pytest.mark.asyncio
async def test_cross_binding_command_is_rejected(tmp_path):
    service, grant, _bus = _service(tmp_path)
    binding = _binding()
    binding["installation_id"] = "another-installation"

    with pytest.raises(SuperExpertPlatformError, match="binding"):
        await service.execute(
            tenant_id="tenant-a",
            installation_id=grant.installation_id,
            capability="aigc.task.create",
            contract_version="1",
            arguments={"binding": binding, "event_id": "event-1"},
            idempotency_key="key-1",
        )


@pytest.mark.asyncio
async def test_bound_task_and_operation_contract_can_be_resumed_after_refresh(
    tmp_path,
    monkeypatch,
):
    service, grant, _bus = _service(tmp_path)
    binding = _binding()
    binding["installation_id"] = grant.installation_id
    await service.execute(
        tenant_id="tenant-a",
        installation_id=grant.installation_id,
        capability="aigc.task.create",
        contract_version="1",
        arguments={"binding": binding, "event_id": "event-1"},
        idempotency_key="key-1",
    )
    monkeypatch.setattr(
        router_module,
        "get_super_expert_platform_service",
        lambda: service,
    )
    access_checks = []
    monkeypatch.setattr(
        router_module,
        "ensure_chat_access",
        lambda _request, conversation_id, allow_admin: access_checks.append(
            (conversation_id, allow_admin),
        ),
    )
    request = SimpleNamespace(state=SimpleNamespace(tenant_id="tenant-a"))

    task = router_module.get_super_expert_task("material-1", request)
    operation = router_module.get_aigc_operation_contract(
        "aigc.text_to_video.create",
        request,
    )

    assert task["binding"]["canvas_id"] == "canvas-1"
    assert task["status"] == "WAITING_TO_START"
    assert operation["human_guide"][0]["control_id"] == "nav.aigc-studio"
    assert access_checks == [("conversation-1", True)]


@pytest.mark.asyncio
async def test_route_uses_trusted_tenant_and_has_no_ordinary_agent_bypass(
    monkeypatch,
):
    captured = {}

    class Service:
        async def execute(self, **kwargs):
            captured.update(kwargs)
            return {"ok": True}

    monkeypatch.setattr(
        router_module,
        "get_super_expert_platform_service",
        lambda: Service(),
    )
    access_checks = []
    monkeypatch.setattr(
        router_module,
        "ensure_chat_access",
        lambda _request, conversation_id, allow_admin: access_checks.append(
            (conversation_id, allow_admin),
        ),
    )
    request = SimpleNamespace(
        state=SimpleNamespace(tenant_id="tenant-a", user_id="user-1"),
    )
    command = PlatformCommandRequest(
        installation_id="installation-1",
        contract_version="1",
        idempotency_key="key-1",
        arguments={"binding": _binding(), "event_id": "event-1"},
    )

    result = await router_module.execute_super_expert_command(
        "aigc.task.create",
        command,
        request,
    )

    assert result == {"ok": True}
    assert captured["tenant_id"] == "tenant-a"
    assert "administrator_id" not in captured
    assert access_checks == [("conversation-1", True)]


def test_platform_command_router_is_mounted_only_on_authenticated_user_api():
    from qwenpaw.app import routers

    assert any(
        getattr(route, "original_router", None) is router_module.router
        for route in routers.user_api_router.routes
    )
    assert not any(
        getattr(route, "original_router", None) is router_module.router
        for route in routers.router.routes
    )
