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
    ("aigc.task.create/2", "1"),
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


def _scope(installation_id: str):
    return {
        "installation_id": installation_id,
        "conversation_id": "conversation-1",
        "agent_task_id": "agent-task-1",
        "content_revision": 3,
        "material_task_id": "material-v2-1",
    }


def _operation():
    return {
        "operation_id": "aigc.text_to_video.create",
        "operation_version": "1",
        "arguments": {
            "project_name": "天门就业培训招生视频",
            "prompt": "真实课堂与就业服务场景，竖屏纪实风格。",
            "model_id": "video-model-1",
            "aspect_ratio": "9:16",
            "duration_seconds": 5,
        },
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
    assert envelope["payload"]["task_status"] == "WAITING_TO_START"
    assert envelope["payload"]["task_version"] == 1

    session_events = service.list_session_events(
        installation_id=grant.installation_id,
        conversation_id="conversation-1",
    )
    assert [event.event_id for event in session_events] == ["event-1"]
    assert service.list_session_events(
        installation_id=grant.installation_id,
        conversation_id="another-conversation",
    ) == ()


@pytest.mark.asyncio
async def test_create_v2_provisions_one_real_owned_canvas_and_persists_operation(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.routers import aigc_studio

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path / "studio")
    aigc_studio._JSON_CACHE.clear()
    service, grant, bus = _service(tmp_path)
    arguments = {
        "scope": _scope(grant.installation_id),
        "event_id": "event-v2-1",
        "operation": _operation(),
    }

    first = await service.execute(
        tenant_id="tenant-a",
        user_id="user-a",
        installation_id=grant.installation_id,
        capability="aigc.task.create/2",
        contract_version="1",
        arguments=arguments,
        idempotency_key="key-v2-1",
    )
    replay = await service.execute(
        tenant_id="tenant-a",
        user_id="user-a",
        installation_id=grant.installation_id,
        capability="aigc.task.create/2",
        contract_version="1",
        arguments=arguments,
        idempotency_key="key-v2-1",
    )

    assert replay == first
    task = first["task"]
    assert task["operation_id"] == "aigc.text_to_video.create"
    assert task["operation_version"] == "1"
    assert task["operation_arguments"] == _operation()["arguments"]
    assert task["binding"]["canvas_id"] != "canvas-material-v2-1"
    assert task["binding"]["node_id"] != "video-material-v2-1"
    canvas = aigc_studio._load_canvas(task["binding"]["canvas_id"])
    assert canvas.meta["owner_user_id"] == "user-a"
    assert canvas.name == "天门就业培训招生视频"
    assert [node.id for node in canvas.nodes] == [task["binding"]["node_id"]]
    assert canvas.nodes[0].type == "video_generate"
    assert canvas.nodes[0].data["text"] == _operation()["arguments"]["prompt"]
    assert canvas.nodes[0].data["aspectRatio"] == "9:16"
    assert canvas.nodes[0].data["videoDuration"] == 5
    assert len(list((tmp_path / "studio" / "canvases").glob("*.json"))) == 1
    assert len(bus.events) == 1


@pytest.mark.asyncio
async def test_create_v2_rejects_agent_supplied_canvas_or_node_ids(tmp_path):
    service, grant, _bus = _service(tmp_path)
    arguments = {
        "scope": _scope(grant.installation_id),
        "binding": {
            **_scope(grant.installation_id),
            "canvas_id": "agent-canvas",
            "node_id": "agent-node",
        },
        "event_id": "event-v2-1",
        "operation": _operation(),
    }

    with pytest.raises(SuperExpertPlatformError, match="physical binding"):
        await service.execute(
            tenant_id="tenant-a",
            user_id="user-a",
            installation_id=grant.installation_id,
            capability="aigc.task.create/2",
            contract_version="1",
            arguments=arguments,
            idempotency_key="key-v2-1",
        )


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


@pytest.mark.asyncio
async def test_create_v2_route_uses_scope_for_access_and_passes_trusted_user(
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
        state=SimpleNamespace(tenant_id="tenant-a", user_id="user-a"),
    )
    command = PlatformCommandRequest(
        installation_id="installation-1",
        contract_version="1",
        idempotency_key="key-v2-1",
        arguments={
            "scope": _scope("installation-1"),
            "event_id": "event-v2-1",
            "operation": _operation(),
        },
    )

    result = await router_module.execute_super_expert_command(
        "aigc.task.create/2",
        command,
        request,
    )

    assert result == {"ok": True}
    assert access_checks == [("conversation-1", True)]
    assert captured["user_id"] == "user-a"


@pytest.mark.asyncio
async def test_asset_submit_dispatches_bound_agent_review_in_the_same_page(
    monkeypatch,
):
    captured = {}

    class Service:
        def __init__(self):
            self.receipts = {}

        async def execute(self, **kwargs):
            return {"task": {"status": "SUBMITTED"}, "event": {}}

        def review_lock(self, _event_id):
            return __import__("asyncio").Lock()

        def get_review_receipt(self, event_id):
            return self.receipts.get(event_id)

        def save_review_receipt(self, event_id, receipt):
            self.receipts[event_id] = receipt
            return receipt

        def get_task(self, _material_task_id):
            return SimpleNamespace(
                status=router_module.AigcTaskStatus.SUBMITTED,
                model_dump=lambda **_kwargs: {"status": "REVISION_REQUIRED"},
            )

    service = Service()
    monkeypatch.setattr(
        router_module,
        "get_super_expert_platform_service",
        lambda: service,
    )
    monkeypatch.setattr(router_module, "ensure_chat_access", lambda *_args, **_kwargs: None)

    async def dispatch(_request, **kwargs):
        captured.update(kwargs)
        return {"status": "completed", "reply": "需要调整第一个镜头。"}

    monkeypatch.setattr(router_module, "_dispatch_agent_asset_review", dispatch)
    request = SimpleNamespace(
        state=SimpleNamespace(tenant_id="tenant-a", user_id="user-1"),
    )
    binding = _binding()
    binding["installation_id"] = "installation-1"
    command = PlatformCommandRequest(
        installation_id="installation-1",
        contract_version="1",
        idempotency_key="submit-1",
        arguments={
            "binding": binding,
            "event_id": "submit-1",
            "asset_id": "asset-1",
        },
    )

    result = await router_module.execute_super_expert_command(
        "aigc.asset.submit",
        command,
        request,
    )

    assert result["agent_review"]["reply"] == "需要调整第一个镜头。"
    assert captured["asset_id"] == "asset-1"
    assert captured["binding"].material_task_id == "material-1"


@pytest.mark.asyncio
async def test_asset_review_dispatch_uses_bound_session_and_media(monkeypatch):
    captured = {}

    class GrantRepository:
        def get(self, _installation_id):
            return SimpleNamespace(agent_id="agent-1", tenant_id="tenant-a")

    class Runner:
        async def query_handler(self, messages, request):
            captured["messages"] = messages
            captured["request"] = request
            yield SimpleNamespace(get_text_content=lambda: "审核通过。"), True

    class Manager:
        async def get_agent(self, agent_id):
            assert agent_id == "agent-1"
            return SimpleNamespace(runner=Runner())

    async def resolve(*_args, **_kwargs):
        return {
            "type": "video",
            "source": {"type": "url", "url": "file:///tmp/result.mp4"},
        }

    monkeypatch.setattr(
        "qwenpaw.app.routers.aigc_studio.resolve_owned_asset_for_agent_review",
        resolve,
    )
    billing = SimpleNamespace(
        activate=lambda: __import__("contextlib").nullcontext(),
        finalize_completed=lambda: True,
        finalize=lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        router_module,
        "prepare_user_billing_execution",
        lambda *_a, **_k: billing,
    )
    request = SimpleNamespace(
        state=SimpleNamespace(user_id="user-1"),
        app=SimpleNamespace(
            state=SimpleNamespace(multi_agent_manager=Manager()),
        ),
    )
    service = SimpleNamespace(grant_repository=GrantRepository())

    result = await router_module._dispatch_agent_asset_review(
        request,
        service=service,
        installation_id="installation-1",
        binding=router_module.AigcTaskBinding.model_validate(_binding()),
        asset_id="asset-1",
        request_key="submit-1:agent-review",
    )

    assert result == {"status": "completed", "reply": "审核通过。"}
    assert captured["request"].session_id == "conversation-1"
    assert captured["request"].channel == "platform:aigc-review"
    assert captured["messages"][0].content[1]["type"] == "video"


@pytest.mark.asyncio
async def test_duplicate_asset_submit_replays_the_durable_agent_review(
    tmp_path,
    monkeypatch,
):
    grants = SuperExpertGrantRepository(tmp_path / "grants")
    grant = grants.grant_installation(
        grants.preview("agent", _release(), tenant_id="tenant-a"),
        administrator_id="admin",
    )
    service = SuperExpertPlatformService(
        grant_repository=grants,
        task_repository=AigcTaskRepository(tmp_path / "tasks"),
        event_repository=SuperExpertEventRepository(tmp_path / "events"),
        event_bus=Bus(),
    )
    binding = _binding()
    binding["installation_id"] = grant.installation_id
    for capability, event_id in (
        ("aigc.task.create", "create"),
        ("aigc.task.resume", "resume"),
    ):
        await service.execute(
            tenant_id="tenant-a",
            installation_id=grant.installation_id,
            capability=capability,
            contract_version="1",
            arguments={"binding": binding, "event_id": event_id},
            idempotency_key=event_id,
        )
    monkeypatch.setattr(
        router_module,
        "get_super_expert_platform_service",
        lambda: service,
    )
    monkeypatch.setattr(router_module, "ensure_chat_access", lambda *_a, **_k: None)
    dispatches = 0

    async def dispatch(*_args, **_kwargs):
        nonlocal dispatches
        dispatches += 1
        return {"status": "completed", "reply": "同一份审核结论。"}

    monkeypatch.setattr(router_module, "_dispatch_agent_asset_review", dispatch)
    request = SimpleNamespace(state=SimpleNamespace(tenant_id="tenant-a"))
    command = PlatformCommandRequest(
        installation_id=grant.installation_id,
        contract_version="1",
        idempotency_key="submit",
        arguments={
            "binding": binding,
            "event_id": "submit",
            "asset_id": "asset-1",
        },
    )

    first = await router_module.execute_super_expert_command(
        "aigc.asset.submit", command, request,
    )
    replay = await router_module.execute_super_expert_command(
        "aigc.asset.submit", command, request,
    )

    assert dispatches == 1
    assert replay["agent_review"] == first["agent_review"]


@pytest.mark.asyncio
async def test_submit_retry_recovers_terminal_review_without_running_agent_again(
    tmp_path,
    monkeypatch,
):
    service, grant, _bus = _service(tmp_path)
    binding = _binding()
    binding["installation_id"] = grant.installation_id
    for capability, event_id, extra in (
        ("aigc.task.create", "create", {}),
        ("aigc.task.resume", "resume", {}),
        ("aigc.asset.submit", "submit", {"asset_id": "asset-1"}),
        (
            "aigc.review.complete",
            "accept",
            {"asset_id": "asset-1", "decision": "ACCEPTED"},
        ),
    ):
        await service.execute(
            tenant_id="tenant-a",
            installation_id=grant.installation_id,
            capability=capability,
            contract_version="1",
            arguments={"binding": binding, "event_id": event_id, **extra},
            idempotency_key=event_id,
        )
    monkeypatch.setattr(
        router_module,
        "get_super_expert_platform_service",
        lambda: service,
    )
    monkeypatch.setattr(router_module, "ensure_chat_access", lambda *_a, **_k: None)

    async def must_not_dispatch(*_args, **_kwargs):
        pytest.fail("a terminal review retry must not invoke the Agent again")

    monkeypatch.setattr(
        router_module,
        "_dispatch_agent_asset_review",
        must_not_dispatch,
    )
    command = PlatformCommandRequest(
        installation_id=grant.installation_id,
        contract_version="1",
        idempotency_key="submit",
        arguments={
            "binding": binding,
            "event_id": "submit",
            "asset_id": "asset-1",
        },
    )

    result = await router_module.execute_super_expert_command(
        "aigc.asset.submit",
        command,
        SimpleNamespace(state=SimpleNamespace(tenant_id="tenant-a")),
    )

    assert result["task"].status.value == "ACCEPTED"
    assert "审核已完成" in result["agent_review"]["reply"]


@pytest.mark.asyncio
async def test_asset_review_dispatch_runs_inside_user_billing(monkeypatch):
    lifecycle = []

    class Billing:
        class Activation:
            def __enter__(self):
                lifecycle.append("activated")

            def __exit__(self, *_args):
                lifecycle.append("deactivated")

        def activate(self):
            return self.Activation()

        def finalize_completed(self):
            lifecycle.append("completed")
            return True

        def finalize(self, state, error_code=None):
            lifecycle.append((state, error_code))
            return True

    def prepare(user_id, source, request_key, fingerprint):
        lifecycle.append((user_id, source.id, request_key, fingerprint["asset_id"]))
        return Billing()

    monkeypatch.setattr(router_module, "prepare_user_billing_execution", prepare)
    monkeypatch.setattr(
        "qwenpaw.app.routers.aigc_studio.resolve_owned_asset_for_agent_review",
        lambda *_a, **_k: None,
    )

    async def resolve(*_args, **_kwargs):
        return {"type": "image", "source": {"type": "url", "url": "file:///tmp/a"}}

    monkeypatch.setattr(
        "qwenpaw.app.routers.aigc_studio.resolve_owned_asset_for_agent_review",
        resolve,
    )

    class Runner:
        async def query_handler(self, _messages, _request):
            yield SimpleNamespace(get_text_content=lambda: "完成"), True

    class Manager:
        async def get_agent(self, _agent_id):
            return SimpleNamespace(runner=Runner())

    service = SimpleNamespace(
        grant_repository=SimpleNamespace(
            get=lambda _id: SimpleNamespace(agent_id="agent-1", tenant_id="tenant-a"),
        ),
    )
    request = SimpleNamespace(
        state=SimpleNamespace(user_id="user-1"),
        app=SimpleNamespace(state=SimpleNamespace(multi_agent_manager=Manager())),
    )

    await router_module._dispatch_agent_asset_review(
        request,
        service=service,
        installation_id="installation-1",
        binding=router_module.AigcTaskBinding.model_validate(_binding()),
        asset_id="asset-1",
        request_key="submit:agent-review",
    )

    assert lifecycle == [
        ("user-1", "conversation-1", "submit:agent-review", "asset-1"),
        "activated",
        "deactivated",
        "completed",
    ]


@pytest.mark.asyncio
async def test_asset_submit_returns_safe_payment_required_error(monkeypatch):
    class Service:
        async def execute(self, **_kwargs):
            return {"task": {"status": "SUBMITTED"}, "event": {}}

        def review_lock(self, _event_id):
            return __import__("asyncio").Lock()

        def get_review_receipt(self, _event_id):
            return None

        def get_task(self, _material_task_id):
            return SimpleNamespace(status=router_module.AigcTaskStatus.SUBMITTED)

    async def insufficient(*_args, **_kwargs):
        raise router_module.InsufficientUsageCreditsError(3, 0)

    monkeypatch.setattr(
        router_module,
        "get_super_expert_platform_service",
        lambda: Service(),
    )
    monkeypatch.setattr(router_module, "ensure_chat_access", lambda *_a, **_k: None)
    monkeypatch.setattr(router_module, "_dispatch_agent_asset_review", insufficient)
    binding = _binding()
    binding["installation_id"] = "installation-1"
    command = PlatformCommandRequest(
        installation_id="installation-1",
        contract_version="1",
        idempotency_key="submit",
        arguments={"binding": binding, "event_id": "submit", "asset_id": "asset"},
    )

    with pytest.raises(HTTPException) as exc_info:
        await router_module.execute_super_expert_command(
            "aigc.asset.submit",
            command,
            SimpleNamespace(state=SimpleNamespace(tenant_id="tenant-a")),
        )

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail == "insufficient usage credits"


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
