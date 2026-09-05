from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from qwenpaw.app.guards import require_user
from qwenpaw.app.routers import router as api_router
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
from qwenpaw.app.routers.aigc_studio import (
    AigcCapabilityInfo,
    CapabilityList,
    project_workflow_capability_catalog,
)


CAPABILITIES = (
    ("aigc.workflow.capabilities.list/1", "1"),
    ("aigc.workflow.create/1", "1"),
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


def _workflow_blueprint(*, kind: str = "video_generate", fallback: str = "FAIL_CLOSED"):
    capability = "text_to_video" if kind == "video_generate" else "image_to_video"
    return {
        "schema_version": 1,
        "title": "三节点招生短视频",
        "execution_preference": "CUSTOMER_TRIGGERED",
        "nodes": [
            {
                "node_id": "copy",
                "kind": "prompt",
                "title": "开场文案",
                "capability": "storyboard",
                "provider_id": "provider-1",
                "model_id": "text-1",
                "inputs": {"text": "失业后学抖音，从哪里开始？"},
                "parameters": {},
                "customer_action": "CLICK_GENERATE",
                "optional": False,
            },
            {
                "node_id": "clip",
                "kind": kind,
                "title": "开场视频",
                "capability": capability,
                "provider_id": "provider-1",
                "model_id": "video-1",
                "inputs": {"prompt": "真实课堂，竖屏纪实"},
                "parameters": {"duration_seconds": 5, "aspect_ratio": "9:16"},
                "customer_action": "CLICK_GENERATE",
                "optional": False,
            },
        ],
        "edges": [
            {"source": "copy", "target": "clip", "target_slot": "prompt"}
        ],
        "output_node_id": "clip",
        "fallback_policy": fallback,
    }


def _workflow_arguments(installation_id: str, **workflow_changes):
    workflow = {**_workflow_blueprint(), **workflow_changes}
    return {
        "scope": _scope(installation_id),
        "event_id": "workflow-event-1",
        "workflow": workflow,
    }


def _workflow_catalog():
    return project_workflow_capability_catalog(
        CapabilityList(
            capabilities=[
                AigcCapabilityInfo(
                    provider_id="provider-1",
                    provider_name="Provider",
                    model_id="text-1",
                    model_name="Text One",
                    capability="storyboard",
                    source="model_registry",
                    parameter_schema={"type": "object"},
                ),
                AigcCapabilityInfo(
                    provider_id="provider-1",
                    provider_name="Provider",
                    model_id="video-1",
                    model_name="Video One",
                    capability="text_to_video",
                    source="model_registry",
                    parameter_schema={"type": "object"},
                ),
                AigcCapabilityInfo(
                    provider_id="provider-1",
                    provider_name="Provider",
                    model_id="video-1",
                    model_name="Video One",
                    capability="image_to_video",
                    source="model_registry",
                    parameter_schema={"type": "object"},
                ),
            ]
        )
    )


@pytest.mark.asyncio
async def test_super_expert_read_api_supports_frontend_compatibility_prefix():
    """The shipped frontend path must resolve to the authenticated platform API."""
    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    app.dependency_overrides[require_user] = lambda: "user-1"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/super-expert-platform/operations/aigc.text_to_video.create",
        )

    assert response.status_code == 200
    assert response.json()["operation_id"] == "aigc.text_to_video.create"


@pytest.mark.asyncio
async def test_super_expert_frontend_compatibility_prefix_requires_user():
    """The compatibility mount must never make platform operations public."""
    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    def deny_user():
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides[require_user] = deny_user
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/super-expert-platform/operations/aigc.text_to_video.create",
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_super_expert_frontend_compatibility_prefix_is_read_only():
    """The console compatibility path must not duplicate command endpoints."""
    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    app.dependency_overrides[require_user] = lambda: "user-1"

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/super-expert-platform/commands/aigc.task.resume",
            json={},
        )

    assert response.status_code == 404


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
async def test_asset_validation_happens_before_submit_state_transition(tmp_path):
    service, grant, _bus = _service(tmp_path)
    binding = _binding()
    binding["installation_id"] = grant.installation_id
    await service.execute(
        tenant_id="tenant-a",
        installation_id=grant.installation_id,
        capability="aigc.task.create",
        contract_version="1",
        arguments={"binding": binding, "event_id": "create"},
        idempotency_key="create",
    )
    await service.execute(
        tenant_id="tenant-a",
        installation_id=grant.installation_id,
        capability="aigc.task.resume",
        contract_version="1",
        arguments={"binding": binding, "event_id": "resume"},
        idempotency_key="resume",
    )

    async def reject_asset(_binding, _asset_id, _task):
        raise SuperExpertPlatformError("asset binding mismatch")

    with pytest.raises(SuperExpertPlatformError, match="asset binding mismatch"):
        await service.execute(
            tenant_id="tenant-a",
            installation_id=grant.installation_id,
            capability="aigc.asset.submit",
            contract_version="1",
            arguments={
                "binding": binding,
                "event_id": "submit",
                "asset_id": "wrong-asset",
            },
            idempotency_key="submit",
            asset_validator=reject_asset,
        )

    task = service.get_task("material-1")
    assert task is not None
    assert task.status == router_module.AigcTaskStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_create_v2_provisions_one_real_owned_canvas_and_persists_operation(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.routers import aigc_studio

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path / "studio")
    aigc_studio._resource_store.cache_clear()
    service, grant, bus = _service(tmp_path)
    generated_ids = iter(
        (
            UUID("7f090b06-12d8-4dd6-8bba-98d12a2e90fe"),
            UUID("8d5315c4-3311-46a8-bf39-4839ea5b6faf"),
        ),
    )
    monkeypatch.setattr(aigc_studio.uuid, "uuid4", lambda: next(generated_ids))
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
    assert task["binding"]["canvas_id"].startswith("canvas-")
    assert task["binding"]["node_id"].startswith("video-")
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


def test_workflow_catalog_exposes_all_canvas_nodes_and_real_models():
    catalog = _workflow_catalog()

    assert len(catalog.nodes) == 11
    by_kind = {node.kind: node for node in catalog.nodes}
    assert by_kind["video_generate"].provisioning == "AUTO_PROVISIONABLE"
    assert by_kind["video_compose"].provisioning == "UNAVAILABLE"
    assert by_kind["director_stage"].provisioning == "UNAVAILABLE"
    assert {
        (model.provider_id, model.model_id, model.capability)
        for model in catalog.available_models
        } == {
            ("provider-1", "text-1", "storyboard"),
            ("provider-1", "video-1", "text_to_video"),
        ("provider-1", "video-1", "image_to_video"),
    }


@pytest.mark.asyncio
async def test_authorized_workflow_create_provisions_all_nodes_and_bindings(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.routers import aigc_studio

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path / "studio")
    aigc_studio._resource_store.cache_clear()
    service, grant, bus = _service(tmp_path)

    async def catalog():
        return _workflow_catalog()

    monkeypatch.setattr(router_module, "_load_workflow_capability_catalog", catalog)
    arguments = _workflow_arguments(grant.installation_id)

    first = await service.execute(
        tenant_id="tenant-a",
        user_id="user-a",
        installation_id=grant.installation_id,
        capability="aigc.workflow.create/1",
        contract_version="1",
        arguments=arguments,
        idempotency_key="workflow-key-1",
    )
    replay = await service.execute(
        tenant_id="tenant-a",
        user_id="user-a",
        installation_id=grant.installation_id,
        capability="aigc.workflow.create/1",
        contract_version="1",
        arguments=arguments,
        idempotency_key="workflow-key-1",
    )

    assert replay == first
    binding = first["task"]["binding"]
    assert binding["execution_mode"] == "PREBUILT_WORKFLOW"
    assert set(binding["node_bindings"]) == {"copy", "clip"}
    assert binding["node_id"] == binding["output_node_id"]
    canvas = aigc_studio._load_canvas(binding["canvas_id"])
    assert [node.type for node in canvas.nodes] == ["prompt", "video_generate"]
    assert len(canvas.edges) == 1
    assert canvas.edges[0].source == binding["node_bindings"]["copy"]
    assert canvas.edges[0].target == binding["node_bindings"]["clip"]
    assert len(bus.events) == 1
    event = bus.events[0].payload["envelope"]
    assert event["payload"]["workflow_binding"] == binding


@pytest.mark.asyncio
async def test_output_wrapper_review_uses_nearest_producing_node(tmp_path, monkeypatch):
    from qwenpaw.app.routers import aigc_studio

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path / "studio")
    aigc_studio._resource_store.cache_clear()
    service, grant, _bus = _service(tmp_path)

    async def catalog():
        return _workflow_catalog()

    monkeypatch.setattr(router_module, "_load_workflow_capability_catalog", catalog)
    base = _workflow_blueprint()
    output_node = {
        "node_id": "final",
        "kind": "output",
        "title": "最终视频",
        "inputs": {"label": "成片"},
        "parameters": {},
        "customer_action": "INSPECT",
        "optional": False,
    }
    arguments = _workflow_arguments(
        grant.installation_id,
        nodes=[*base["nodes"], output_node],
        edges=[
            *base["edges"],
            {"source": "clip", "target": "final", "target_slot": "asset"},
        ],
        output_node_id="final",
    )
    result = await service.execute(
        tenant_id="tenant-a",
        user_id="user-a",
        installation_id=grant.installation_id,
        capability="aigc.workflow.create/1",
        contract_version="1",
        arguments=arguments,
        idempotency_key="workflow-output-wrapper",
    )
    task = service.get_task(result["task"]["binding"]["material_task_id"])
    assert task is not None

    assert router_module._workflow_review_node_ids(task) == {
        result["task"]["binding"]["node_bindings"]["clip"]
    }


@pytest.mark.asyncio
async def test_workflow_task_write_failure_removes_provisioned_canvas(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.routers import aigc_studio

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path / "studio")
    aigc_studio._resource_store.cache_clear()
    service, grant, _bus = _service(tmp_path)

    async def catalog():
        return _workflow_catalog()

    monkeypatch.setattr(router_module, "_load_workflow_capability_catalog", catalog)

    def fail(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(service.task_repository, "apply", fail)
    with pytest.raises(OSError, match="disk full"):
        await service.execute(
            tenant_id="tenant-a",
            user_id="user-a",
            installation_id=grant.installation_id,
            capability="aigc.workflow.create/1",
            contract_version="1",
            arguments=_workflow_arguments(grant.installation_id),
            idempotency_key="workflow-key-1",
        )

    assert list((tmp_path / "studio" / "canvases").glob("*.json")) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("catalog_unavailable_on_retry", [False, True])
async def test_core_managed_workflow_recovers_platform_binding_failure(tmp_path, monkeypatch, catalog_unavailable_on_retry):
    from sqlalchemy import create_engine
    from qwenpaw.app.aigc.resource_store import AigcResourceStore
    from qwenpaw.app.aigc.workflow_execution import AigcWorkflowExecutionService
    from qwenpaw.app.storage.repos.aigc_execution_repo import AigcExecutionRepository
    from qwenpaw.app.storage.schema import create_all
    from qwenpaw.app.routers import aigc_studio

    engine = create_engine(f"sqlite:///{tmp_path / 'core.sqlite'}")
    create_all(engine)
    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path / "studio")
    service, grant, bus = _service(tmp_path)
    core = AigcWorkflowExecutionService(AigcResourceStore(tmp_path / "studio"), AigcExecutionRepository(engine))
    service.workflow_execution_service = core

    async def catalog():
        return _workflow_catalog()

    monkeypatch.setattr(router_module, "_load_workflow_capability_catalog", catalog)
    arguments = _workflow_arguments(grant.installation_id)
    original_apply = service.task_repository.apply

    def fail(*_args, **_kwargs):
        raise OSError("task write interrupted")

    monkeypatch.setattr(service.task_repository, "apply", fail)
    with pytest.raises(OSError, match="task write interrupted"):
        await service.execute(tenant_id="tenant-a", user_id="user-a",
                              installation_id=grant.installation_id,
                              capability="aigc.workflow.create/1", contract_version="1",
                              arguments=arguments, idempotency_key="recover-core")
    canvases = list((tmp_path / "studio/canvases").glob("*.json"))
    assert len(canvases) == 1
    assert not bus.events
    monkeypatch.setattr(service.task_repository, "apply", original_apply)
    if catalog_unavailable_on_retry:
        async def unavailable_catalog():
            raise OSError("catalog temporarily unavailable")

        monkeypatch.setattr(router_module, "_load_workflow_capability_catalog", unavailable_catalog)
    result = await service.execute(tenant_id="tenant-a", user_id="user-a",
                                   installation_id=grant.installation_id,
                                   capability="aigc.workflow.create/1", contract_version="1",
                                   arguments=arguments, idempotency_key="recover-core")
    binding = result["task"]["binding"]
    assert binding["canvas_id"] == canvases[0].stem
    assert len(list((tmp_path / "studio/canvases").glob("*.json"))) == 1
    contract = core.repository.get_binding("user-a", binding["canvas_id"], binding["node_bindings"]["clip"])
    assert (contract.provider_id, contract.model_id, contract.capability) == ("provider-1", "video-1", "text_to_video")
    assert len(bus.events) == 1
    engine.dispose()


@pytest.mark.asyncio
async def test_workflow_rejects_unavailable_model_without_creating_canvas(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.routers import aigc_studio

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path / "studio")
    aigc_studio._resource_store.cache_clear()
    service, grant, _bus = _service(tmp_path)

    async def empty_catalog():
        return project_workflow_capability_catalog(CapabilityList(capabilities=[]))

    monkeypatch.setattr(
        router_module,
        "_load_workflow_capability_catalog",
        empty_catalog,
    )
    with pytest.raises(SuperExpertPlatformError, match="MODEL_UNAVAILABLE"):
        await service.execute(
            tenant_id="tenant-a",
            user_id="user-a",
            installation_id=grant.installation_id,
            capability="aigc.workflow.create/1",
            contract_version="1",
            arguments=_workflow_arguments(grant.installation_id),
            idempotency_key="workflow-key-1",
        )

    assert not (tmp_path / "studio" / "canvases").exists()


@pytest.mark.asyncio
async def test_unavailable_workflow_never_creates_a_misleading_manual_canvas(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.routers import aigc_studio

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path / "studio")
    aigc_studio._resource_store.cache_clear()
    service, grant, _bus = _service(tmp_path)

    async def catalog():
        return _workflow_catalog()

    monkeypatch.setattr(router_module, "_load_workflow_capability_catalog", catalog)
    manual_node = {
        "schema_version": 1,
        "title": "人工合成流程",
        "execution_preference": "CUSTOMER_TRIGGERED",
        "nodes": [
            {
                "node_id": "compose",
                "kind": "video_compose",
                "title": "视频合成",
                "inputs": {},
                "parameters": {},
                "customer_action": "NONE",
                "optional": False,
            }
        ],
        "edges": [],
        "output_node_id": "compose",
        "fallback_policy": "FAIL_CLOSED",
    }
    with pytest.raises(SuperExpertPlatformError, match="NODE_KIND_UNAVAILABLE"):
        await service.execute(
            tenant_id="tenant-a",
            user_id="user-a",
            installation_id=grant.installation_id,
            capability="aigc.workflow.create/1",
            contract_version="1",
            arguments=_workflow_arguments(grant.installation_id, **manual_node),
            idempotency_key="manual-closed",
        )

    manual_node["fallback_policy"] = "MANUAL_BUILD_IF_UNSUPPORTED"
    arguments = _workflow_arguments(grant.installation_id, **manual_node)
    arguments["scope"]["material_task_id"] = "manual-material"
    arguments["event_id"] = "manual-event"
    with pytest.raises(SuperExpertPlatformError, match="NODE_KIND_UNAVAILABLE"):
        await service.execute(
            tenant_id="tenant-a",
            user_id="user-a",
            installation_id=grant.installation_id,
            capability="aigc.workflow.create/1",
            contract_version="1",
            arguments=arguments,
            idempotency_key="manual-open",
        )
    assert list((tmp_path / "studio" / "canvases").glob("*.json")) == []


@pytest.mark.asyncio
async def test_workflow_guide_endpoint_projects_real_canvas_and_blocks_if_deleted(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.routers import aigc_studio

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path / "studio")
    aigc_studio._resource_store.cache_clear()
    service, grant, _bus = _service(tmp_path)

    async def catalog():
        return _workflow_catalog()

    monkeypatch.setattr(router_module, "_load_workflow_capability_catalog", catalog)
    created = await service.execute(
        tenant_id="tenant-a",
        user_id="user-a",
        installation_id=grant.installation_id,
        capability="aigc.workflow.create/1",
        contract_version="1",
        arguments=_workflow_arguments(grant.installation_id),
        idempotency_key="workflow-key-1",
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
            (conversation_id, allow_admin)
        ),
    )
    request = SimpleNamespace(state=SimpleNamespace(user_id="user-a"))

    guide = router_module.get_super_expert_task_guide("material-v2-1", request)

    assert guide["current_step_id"] == "copy.generate"
    assert guide["current_step"]["node_id"] == created["task"]["binding"][
        "node_bindings"
    ]["copy"]
    assert access_checks == [("conversation-1", True)]

    canvas_id = created["task"]["binding"]["canvas_id"]
    aigc_studio._json_path("canvases", canvas_id).unlink()
    aigc_studio._resource_store.cache_clear()
    blocked = router_module.get_super_expert_task_guide("material-v2-1", request)
    assert blocked["current_step"]["status"] == "BLOCKED"
    assert blocked["current_step"]["recovery"]["code"] == "BOUND_CANVAS_MISSING"


@pytest.mark.asyncio
async def test_workflow_guide_update_persists_only_optional_bound_skip(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.routers import aigc_studio

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path / "studio")
    aigc_studio._resource_store.cache_clear()
    service, grant, _bus = _service(tmp_path)

    async def catalog():
        return _workflow_catalog()

    monkeypatch.setattr(router_module, "_load_workflow_capability_catalog", catalog)
    blueprint = _workflow_blueprint()
    blueprint["nodes"][0]["optional"] = True
    created = await service.execute(
        tenant_id="tenant-a",
        user_id="user-a",
        installation_id=grant.installation_id,
        capability="aigc.workflow.create/1",
        contract_version="1",
        arguments={
            "scope": _scope(grant.installation_id),
            "event_id": "workflow-create",
            "workflow": blueprint,
        },
        idempotency_key="workflow-create",
    )
    binding = created["task"]["binding"]
    skipped = await service.execute(
        tenant_id="tenant-a",
        user_id="user-a",
        installation_id=grant.installation_id,
        capability="aigc.guide.update",
        contract_version="1",
        arguments={
            "binding": binding,
            "event_id": "skip-copy",
            "guide": {
                "action": "SKIP_OPTIONAL",
                "workflow_id": binding["workflow_id"],
                "guide_revision": binding["guide_revision"],
                "step_id": "copy.generate",
                "logical_node_id": "copy",
                "node_id": binding["node_bindings"]["copy"],
            },
        },
        idempotency_key="skip-copy",
    )

    assert skipped["task"]["guide_events"][0]["step_id"] == "copy.generate"
    assert skipped["task"]["status"] == "WAITING_TO_START"


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
    async def resolve(*_args, **_kwargs):
        return {
            "type": "video",
            "source": {"type": "url", "url": "file:///tmp/result.mp4"},
        }

    monkeypatch.setattr(
        "qwenpaw.app.routers.aigc_studio.resolve_owned_asset_for_agent_review",
        resolve,
    )
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
