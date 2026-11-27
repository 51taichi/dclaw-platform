from __future__ import annotations

from qwenpaw.app.routers.super_expert_platform import SuperExpertPlatformService
from qwenpaw.app.sealed_agents.models import SealedReleaseRecord
from qwenpaw.app.super_experts.aigc_tasks import AigcTaskRepository
from qwenpaw.app.super_experts.events import SuperExpertEventRepository
from qwenpaw.app.super_experts.grants import SuperExpertGrantRepository


CAPABILITIES = tuple((name, "1") for name in (
    "card.create", "card.update", "aigc.task.create", "aigc.task.resume",
    "aigc.task.cancel", "aigc.guide.update", "aigc.asset.submit",
    "aigc.review.complete",
))


class Bus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def release():
    return SealedReleaseRecord(
        release_id="release-1", version="1.0.0",
        content_digest=f"sha256:{'a' * 64}", signer_id="official-test",
        package_type="super_expert", capability_digest=f"sha256:{'b' * 64}",
        declared_capabilities=CAPABILITIES,
        orchestration_capability_id="workspace.turn.orchestrate/1",
        orchestration_contract_version="1",
    )


async def command(service, grant, capability, event_id, binding, **arguments):
    return await service.execute(
        tenant_id="tenant-a", installation_id=grant.installation_id,
        capability=capability, contract_version="1",
        arguments={"binding": binding, "event_id": event_id, **arguments},
        idempotency_key=event_id,
    )


async def test_bound_material_customer_completion_bypasses_legacy_review(tmp_path):
    grants = SuperExpertGrantRepository(tmp_path / "grants")
    grant = grants.grant_installation(
        grants.preview("luyu-aigc-fixture", release(), tenant_id="tenant-a"),
        administrator_id="admin",
    )
    bus = Bus()
    service = SuperExpertPlatformService(
        grant_repository=grants,
        task_repository=AigcTaskRepository(tmp_path / "tasks"),
        event_repository=SuperExpertEventRepository(tmp_path / "events"),
        event_bus=bus,
    )
    binding = {
        "installation_id": grant.installation_id, "conversation_id": "conversation-1",
        "agent_task_id": "task-1", "content_revision": 3,
        "material_task_id": "material-1", "canvas_id": "canvas-1", "node_id": "video-1",
    }

    await command(service, grant, "aigc.task.create", "e-create", binding)
    # A material card projects an existing task; it cannot precede its binding.
    await command(service, grant, "card.create", "e-card", binding, card={"card_type": "aigc_material_task"})
    await command(service, grant, "aigc.task.resume", "e-start", binding)
    # Leaving the page is a UI pause: the durable server task remains resumable
    # and is recovered from the same bound repository without a cancel command.
    recovered = service.get_task("material-1")
    assert recovered is not None and recovered.status.value == "IN_PROGRESS"
    async def validate_asset(*_args):
        return None

    accepted = await service.execute(
        tenant_id="tenant-a",
        installation_id=grant.installation_id,
        capability="aigc.asset.submit",
        contract_version="1",
        arguments={
            "binding": binding,
            "event_id": "e-complete",
            "asset_id": "asset-1",
        },
        idempotency_key="e-complete",
        asset_validator=validate_asset,
        frontend_asset_submit=True,
    )

    assert accepted["task"]["status"] == "ACCEPTED"
    assert accepted["event"]["event_type"] == "aigc.asset.completed"
    assert [event.type for event in bus.events] == ["super_expert_event"] * 4
    assert all(event.payload["envelope"]["conversation_id"] == "conversation-1" for event in bus.events)


async def test_duplicate_submit_event_is_replayed_without_duplicate_publish(tmp_path):
    grants = SuperExpertGrantRepository(tmp_path / "grants")
    grant = grants.grant_installation(grants.preview("agent", release(), tenant_id="tenant-a"), administrator_id="admin")
    bus = Bus()
    service = SuperExpertPlatformService(grant_repository=grants, task_repository=AigcTaskRepository(tmp_path / "tasks"), event_repository=SuperExpertEventRepository(tmp_path / "events"), event_bus=bus)
    binding = {"installation_id": grant.installation_id, "conversation_id": "c", "agent_task_id": "t", "content_revision": 1, "material_task_id": "m", "canvas_id": "cv", "node_id": "n"}
    await command(service, grant, "aigc.task.create", "create", binding)
    await command(service, grant, "aigc.task.resume", "start", binding)
    async def validate_asset(*_args):
        return None

    async def complete():
        return await service.execute(
            tenant_id="tenant-a",
            installation_id=grant.installation_id,
            capability="aigc.asset.submit",
            contract_version="1",
            arguments={
                "binding": binding,
                "event_id": "complete",
                "asset_id": "asset",
            },
            idempotency_key="complete",
            asset_validator=validate_asset,
            frontend_asset_submit=True,
        )

    first = await complete()
    replay = await complete()
    assert first == replay
    assert len(bus.events) == 3
