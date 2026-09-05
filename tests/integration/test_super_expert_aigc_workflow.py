from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from qwenpaw.app.routers import super_expert_platform as platform_router
from qwenpaw.app.routers.aigc_studio import (
    AigcAsset,
    AigcCapabilityInfo,
    AigcJob,
    CapabilityList,
    project_workflow_capability_catalog,
)
from qwenpaw.app.routers.super_expert_platform import SuperExpertPlatformService
from qwenpaw.app.sealed_agents.models import SealedReleaseRecord
from qwenpaw.app.super_experts.aigc_guide import project_aigc_guide
from qwenpaw.app.super_experts.aigc_tasks import AigcTaskRepository
from qwenpaw.app.super_experts.events import SuperExpertEventRepository
from qwenpaw.app.super_experts.grants import SuperExpertGrantRepository


FIXTURES = Path(__file__).parents[1] / "fixtures" / "super_expert" / "aigc-workflow-v2"
CAPABILITIES = tuple((name, "1") for name in (
    "aigc.workflow.capabilities.list/1",
    "aigc.workflow.create/1",
    "aigc.task.resume",
    "aigc.asset.submit",
))
NOW = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)


class Bus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def _release():
    return SealedReleaseRecord(
        release_id="release-workflow-v2",
        version="1.0.0",
        content_digest=f"sha256:{'a' * 64}",
        signer_id="official-test",
        package_type="super_expert",
        capability_digest=f"sha256:{'b' * 64}",
        declared_capabilities=CAPABILITIES,
        orchestration_capability_id="workspace.turn.orchestrate/1",
        orchestration_contract_version="1",
    )


def _fixture(name: str, installation_id: str):
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    value["scope"]["installation_id"] = installation_id
    return value


async def _catalog():
    return project_workflow_capability_catalog(CapabilityList(capabilities=[
        AigcCapabilityInfo(
            provider_id="provider-1", provider_name="Provider",
            model_id="text-1", model_name="Text",
            capability="storyboard", source="model_registry",
            parameter_schema={"type": "object"},
        ),
        AigcCapabilityInfo(
            provider_id="provider-1", provider_name="Provider",
            model_id="image-1", model_name="Image",
            capability="text_to_image", source="model_registry",
            parameter_schema={"type": "object"},
        ),
        AigcCapabilityInfo(
            provider_id="provider-1", provider_name="Provider",
            model_id="video-1", model_name="Video",
            capability="text_to_video", source="model_registry",
            parameter_schema={"type": "object"},
        ),
        AigcCapabilityInfo(
            provider_id="provider-1", provider_name="Provider",
            model_id="video-1", model_name="Video",
            capability="image_to_video", source="model_registry",
            parameter_schema={"type": "object"},
        ),
    ]))


def _service(tmp_path):
    from qwenpaw.app.aigc.asset_service import AigcAssetService
    from qwenpaw.app.aigc.canvas_service import AigcCanvasService
    from qwenpaw.app.aigc.resource_store import AigcResourceStore
    from qwenpaw.app.super_experts.aigc_adapter import AigcServiceAdapter

    grants = SuperExpertGrantRepository(tmp_path / "grants")
    grant = grants.grant_installation(
        grants.preview("luyu-workflow-v2", _release(), tenant_id="tenant-a"),
        administrator_id="admin",
    )
    service = SuperExpertPlatformService(
        grant_repository=grants,
        task_repository=AigcTaskRepository(tmp_path / "tasks"),
        event_repository=SuperExpertEventRepository(tmp_path / "events"),
        event_bus=Bus(),
        aigc_adapter=AigcServiceAdapter(
            AigcCanvasService(AigcResourceStore(tmp_path / "studio")),
            AigcAssetService(AigcResourceStore(tmp_path / "studio")),
            catalog_loader=lambda: platform_router._load_workflow_capability_catalog(),
        ),
    )
    return service, grant


async def _command(service, grant, capability, event_id, binding, **arguments):
    return await service.execute(
        tenant_id="tenant-a",
        user_id="user-a",
        installation_id=grant.installation_id,
        capability=capability,
        contract_version="1",
        arguments={"binding": binding, "event_id": event_id, **arguments},
        idempotency_key=event_id,
    )


def _job(canvas_id, node_id, ordinal, output_kind):
    stamp = (NOW + timedelta(minutes=ordinal)).isoformat()
    asset = AigcAsset(
        id=f"asset-{ordinal}",
        kind=output_kind,
        name=f"output-{ordinal}",
        path=f"/tmp/output-{ordinal}",
        created_at=stamp,
        meta={"owner_user_id": "user-a", "canvas_id": canvas_id},
    )
    return AigcJob(
        id=f"job-{ordinal}",
        canvas_id=canvas_id,
        node_id=node_id,
        capability=(
            "storyboard"
            if output_kind == "file"
            else "text_to_image"
            if output_kind == "image"
            else "image_to_video"
        ),
        provider_id="provider-1",
        model_id={"file": "text-1", "image": "image-1", "video": "video-1"}[output_kind],
        status="succeeded",
        created_at=stamp,
        updated_at=stamp,
        outputs=[asset],
    )


@pytest.mark.asyncio
async def test_fixture_manifest_and_one_node_request_are_compatible(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.app.routers import aigc_studio

    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["contract"] == "aigc.workflow.create/1"
    assert set(manifest["fixtures"]) == {"one-node.json", "three-node.json"}
    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path / "studio")
    aigc_studio._resource_store.cache_clear()
    monkeypatch.setattr(platform_router, "_load_workflow_capability_catalog", _catalog)
    service, grant = _service(tmp_path)
    arguments = _fixture("one-node.json", grant.installation_id)

    result = await service.execute(
        tenant_id="tenant-a", user_id="user-a",
        installation_id=grant.installation_id,
        capability="aigc.workflow.create/1", contract_version="1",
        arguments=arguments, idempotency_key="one-node",
    )

    assert result["task"]["binding"]["execution_mode"] == "PREBUILT_WORKFLOW"
    assert set(result["task"]["binding"]["node_bindings"]) == {"clip"}


@pytest.mark.asyncio
async def test_three_node_customer_triggered_closed_loop(tmp_path, monkeypatch):
    from qwenpaw.app.routers import aigc_studio

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path / "studio")
    aigc_studio._resource_store.cache_clear()
    monkeypatch.setattr(platform_router, "_load_workflow_capability_catalog", _catalog)
    service, grant = _service(tmp_path)
    arguments = _fixture("three-node.json", grant.installation_id)

    created = await service.execute(
        tenant_id="tenant-a", user_id="user-a",
        installation_id=grant.installation_id,
        capability="aigc.workflow.create/1", contract_version="1",
        arguments=arguments, idempotency_key="three-node",
    )
    binding = created["task"]["binding"]
    task = service.get_task(binding["material_task_id"])
    canvas, stored_jobs = service.aigc.workflow_context(
        canvas_id=binding["canvas_id"], material_task_id=binding["material_task_id"],
    )
    guide = project_aigc_guide(task=task, canvas=canvas, jobs=stored_jobs)
    assert guide.current_step_id == "copy.generate"
    prompt_node = next(node for node in canvas.nodes if node.id == binding["node_bindings"]["copy"])
    assert prompt_node.data["modelId"] == "text-1"

    jobs = []
    expected = (
        ("copy", "file", "keyframe.generate"),
        ("keyframe", "image", "clip.generate"),
        ("clip", "video", "workflow.submit"),
    )
    for ordinal, (logical_id, output_kind, next_step) in enumerate(expected, 1):
        jobs.append(_job(binding["canvas_id"], binding["node_bindings"][logical_id], ordinal, output_kind))
        # Refresh reconstructs progress solely from the persisted task/canvas and
        # the supplied job history; no browser step index participates.
        guide = project_aigc_guide(task=task, canvas=canvas, jobs=copy.deepcopy(jobs))
        assert guide.current_step_id == next_step

    await _command(service, grant, "aigc.task.resume", "workflow-start", binding)
    submitted = await _command(
        service, grant, "aigc.asset.submit", "workflow-submit", binding,
        asset_id="asset-3",
    )
    assert submitted["task"]["status"] == "SUBMITTED"
    assert submitted["task"]["binding"]["node_id"] == binding["output_node_id"]
