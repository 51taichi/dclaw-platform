"""Durable core progress must stay bound to its original expert and session."""

from types import SimpleNamespace
from datetime import datetime

import pytest

from tests.unit.app.aigc.test_job_lifecycle import resources, lifecycle
from tests.integration.test_super_expert_aigc_workflow import _service, _release, _fixture, _catalog


async def setup_workflows(resources, owners=("owner", "owner")):
    from qwenpaw.app.aigc.workflow_execution import AigcWorkflowExecutionService
    service, first_grant = _service(resources.store.root.parent)
    service.aigc._catalog_loader = _catalog
    service.workflow_execution_service = AigcWorkflowExecutionService(resources.store, resources.repository)
    second_grant = service.grant_repository.grant_installation(
        service.grant_repository.preview("second-expert", _release(), tenant_id="tenant-a"),
        administrator_id="admin",
    )
    scopes, tasks = {}, []
    for index, grant in enumerate((first_grant, second_grant)):
        arguments = _fixture("three-node.json", grant.installation_id)
        arguments["event_id"] = f"create-{index}"
        arguments["scope"].update(conversation_id=f"conversation-{index}", material_task_id=f"material-{index}")
        result = await service.execute(
            tenant_id="tenant-a", user_id=owners[index], installation_id=grant.installation_id,
            capability="aigc.workflow.create/1", contract_version="1",
            arguments=arguments, idempotency_key=f"create-{index}",
        )
        tasks.append(service.get_task(result["task"]["binding"]["material_task_id"]))
        scopes[f"conversation-{index}"] = {"user_id": owners[index], "agent_id": grant.agent_id,
                                              "session_id": f"session-{index}", "tenant_id": "tenant-a"}
    service.event_bus.events.clear()
    return SimpleNamespace(service=service, tasks=tasks, grants=(first_grant, second_grant), scopes=scopes)


def finish_job(resources, task, *, job_id="generated", status="succeeded", created_at="2026-09-06T00:00:00+00:00", owner="owner"):
    core = resources.repository.get_binding(owner, task.binding.canvas_id, task.binding.node_id)
    job = resources.job.model_copy(update={
        "id": job_id, "canvas_id": task.binding.canvas_id, "node_id": task.binding.node_id,
        "provider_id": core.provider_id, "model_id": core.model_id, "capability": core.capability,
        "created_at": created_at, "updated_at": created_at,
    })
    asset = resources.asset.model_copy(update={"id": f"asset-{job_id}", "meta": {
        "owner_user_id": owner, "canvas_id": job.canvas_id, "node_id": job.node_id,
    }})
    resources.store.write("assets", asset.id, asset.model_dump())
    if status == "failed":
        lifecycle(resources).record_failure(job, "raw private error", owner_user_id=owner)
    else:
        lifecycle(resources).record_success(job, [asset], owner_user_id=owner)
    return job, asset


def adapter(resources, setup, **kwargs):
    from qwenpaw.app.super_experts.aigc_event_adapter import AigcEventAdapter
    return AigcEventAdapter(
        setup.service, resources.repository, scope_resolver=setup.scopes.get,
        installation_is_active=kwargs.pop("installation_is_active", lambda grant: True), **kwargs,
    )


@pytest.mark.asyncio
async def test_core_result_only_updates_original_expert_session_without_review(resources):
    setup = await setup_workflows(resources)
    task = setup.tasks[0]
    finish_job(resources, task)
    consumer = adapter(resources, setup)
    await consumer.deliver_pending()
    events = setup.service.event_bus.events
    assert len(events) == 1
    event = events[0].payload["envelope"]
    assert events[0].session_id == "session-0"
    assert event["installation_id"] == setup.grants[0].installation_id
    assert event["conversation_id"] == "conversation-0"
    assert event["material_task_id"] == "material-0"
    assert event["content_revision"] == task.binding.content_revision
    assert event["event_type"] == "aigc.guide.updated"
    assert event["payload"]["job_status"] == "succeeded"
    assert setup.service.get_task("material-0") == task  # no automatic submit or PASS
    assert setup.service.get_task("material-1") == setup.tasks[1]
    assert await consumer.deliver_pending() == 0
    assert len(events) == 1


@pytest.mark.asyncio
async def test_concurrent_delivery_keeps_users_and_original_sessions_separate(resources):
    import asyncio
    setup = await setup_workflows(resources, owners=("owner", "other-owner"))
    finish_job(resources, setup.tasks[0], job_id="first")
    finish_job(resources, setup.tasks[1], job_id="second", owner="other-owner")
    before = {path.name: path.read_bytes() for path in resources.store.directory("jobs").glob("*.json")}
    await asyncio.gather(adapter(resources, setup).deliver_pending(), adapter(resources, setup).deliver_pending())
    delivered = {(event.session_id, event.payload["envelope"]["material_task_id"],
                  event.payload["envelope"]["payload"]["job_id"]) for event in setup.service.event_bus.events}
    assert delivered == {("session-0", "material-0", "first"), ("session-1", "material-1", "second")}
    assert len(setup.service.event_bus.events) == 2
    assert before == {path.name: path.read_bytes() for path in resources.store.directory("jobs").glob("*.json")}
    assert [setup.service.get_task(task.binding.material_task_id) for task in setup.tasks] == setup.tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["owner", "expert", "tenant", "disabled", "cancelled", "revision", "missing_asset"])
async def test_invalid_original_binding_is_blocked_not_rerouted(resources, invalid):
    from qwenpaw.app.super_experts.aigc_tasks import AigcTaskCommand
    from qwenpaw.app.storage.schema import aigc_event_deliveries
    from sqlalchemy import select
    setup = await setup_workflows(resources)
    task = setup.tasks[0]
    job, asset = finish_job(resources, task)
    if invalid in {"owner", "expert", "tenant"}:
        setup.scopes["conversation-0"][{"owner": "user_id", "expert": "agent_id", "tenant": "tenant_id"}[invalid]] = "other"
    elif invalid == "cancelled":
        setup.service.task_repository.apply(AigcTaskCommand(action="cancel", event_id="cancel", binding=task.binding), idempotency_key="cancel")
    elif invalid == "revision":
        # Simulate a persisted task from a later blueprint revision, not a UI selection.
        document = setup.service.task_repository._read()
        document.tasks["material-0"] = task.model_copy(update={"binding": task.binding.model_copy(update={"workflow_revision": 2})})
        setup.service.task_repository._write(document)
    elif invalid == "missing_asset":
        resources.store.delete("assets", asset.id)
    await adapter(resources, setup, installation_is_active=lambda grant: invalid != "disabled").deliver_pending()
    assert setup.service.event_bus.events == []
    with resources.engine.connect() as connection:
        rows = connection.execute(select(aigc_event_deliveries).where(aigc_event_deliveries.c.consumer_id == "super-expert-aigc-v1")).mappings().all()
    assert any(row["status"] == "blocked" for row in rows)
    assert resources.repository.get_job_result(job.id) is not None


@pytest.mark.asyncio
async def test_delivery_retries_same_envelope_after_notification_outage(resources):
    from sqlalchemy import select
    from qwenpaw.app.storage import schema

    setup = await setup_workflows(resources)
    task = setup.tasks[0]
    finish_job(resources, task)
    billing_tables = (schema.billing_wallets, schema.billing_ledger_entries,
                      schema.billing_usage_orders, schema.billing_executions,
                      schema.billing_usage_items)

    def financial_snapshot():
        with resources.engine.connect() as connection:
            return [list(connection.execute(select(table)).mappings()) for table in billing_tables]

    before_billing = financial_snapshot()
    before_jobs = {path.name: path.read_bytes() for path in resources.store.directory("jobs").glob("*.json")}
    original_bus = setup.service.event_bus
    class Offline:
        async def publish(self, event):
            raise OSError("private transport details")
    setup.service.event_bus = Offline()
    await adapter(resources, setup, clock=lambda: 0).deliver_pending()
    assert financial_snapshot() == before_billing
    assert {path.name: path.read_bytes() for path in resources.store.directory("jobs").glob("*.json")} == before_jobs
    persisted = setup.service.list_session_events(installation_id=task.binding.installation_id, conversation_id="conversation-0")
    assert len([event for event in persisted if event.event_type == "aigc.guide.updated"]) == 1
    setup.service.event_bus = original_bus
    await adapter(resources, setup, clock=lambda: 6).deliver_pending()
    assert len(original_bus.events) == 1
    assert setup.service.list_session_events(installation_id=task.binding.installation_id, conversation_id="conversation-0") == persisted
    assert setup.service.get_task("material-0") == task
    assert financial_snapshot() == before_billing
    assert {path.name: path.read_bytes() for path in resources.store.directory("jobs").glob("*.json")} == before_jobs


@pytest.mark.asyncio
async def test_event_file_wait_does_not_block_application_loop(resources, monkeypatch):
    import asyncio
    from threading import Event
    setup = await setup_workflows(resources)
    finish_job(resources, setup.tasks[0])
    entered, released = Event(), Event()
    original = setup.service.event_repository.append

    def slow_append(event):
        entered.set()
        if not released.wait(1):
            raise TimeoutError("application loop could not release writer")
        return original(event)

    monkeypatch.setattr(setup.service.event_repository, "append", slow_append)

    async def other_request():
        assert await asyncio.to_thread(entered.wait, 2)
        released.set()

    await asyncio.gather(adapter(resources, setup).deliver_pending(), other_request())
    assert len(setup.service.event_bus.events) == 1


@pytest.mark.asyncio
async def test_old_failure_does_not_regress_a_successful_job(resources):
    setup = await setup_workflows(resources)
    finish_job(resources, setup.tasks[0], status="failed")
    finish_job(resources, setup.tasks[0])
    await adapter(resources, setup).deliver_pending()
    assert [event.payload["envelope"]["payload"]["job_status"] for event in setup.service.event_bus.events] == ["succeeded"]


@pytest.mark.asyncio
@pytest.mark.parametrize("old_status", ["failed", "succeeded"])
async def test_older_job_cannot_regress_newer_node_result(resources, old_status):
    setup = await setup_workflows(resources)
    finish_job(resources, setup.tasks[0], job_id="new")
    await adapter(resources, setup).deliver_pending()
    finish_job(resources, setup.tasks[0], job_id="old", status=old_status, created_at="2026-09-05T00:00:00+00:00")
    await adapter(resources, setup).deliver_pending()
    assert [event.payload["envelope"]["payload"]["job_id"] for event in setup.service.event_bus.events] == ["new"]


@pytest.mark.asyncio
async def test_concurrent_old_delivery_cannot_follow_new_success(resources, monkeypatch):
    import asyncio
    from threading import Event
    setup = await setup_workflows(resources)
    finish_job(resources, setup.tasks[0], job_id="old", status="failed", created_at="2026-09-05T00:00:00+00:00")
    old_at_append, newer_finished = Event(), Event()
    original = setup.service.event_repository.append

    def pause_old(event):
        if event.payload.get("job_id") == "old":
            old_at_append.set()
            newer_finished.wait(0.3)
        return original(event)

    monkeypatch.setattr(setup.service.event_repository, "append", pause_old)
    first = asyncio.create_task(adapter(resources, setup).deliver_pending())
    assert await asyncio.to_thread(old_at_append.wait, 2)
    finish_job(resources, setup.tasks[0], job_id="new")

    async def deliver_new():
        try:
            await adapter(resources, setup).deliver_pending()
        finally:
            newer_finished.set()

    await asyncio.gather(first, deliver_new())
    progress = [event.payload["envelope"]["payload"] for event in setup.service.event_bus.events]
    assert progress[-1]["job_id"] == "new"
    assert progress[-1]["job_status"] == "succeeded"


@pytest.mark.asyncio
async def test_cancelled_delivery_can_be_reclaimed_without_duplicate_review(resources):
    import asyncio
    setup = await setup_workflows(resources)
    finish_job(resources, setup.tasks[0])
    ready = asyncio.Event()
    original_bus = setup.service.event_bus
    class HangingBus:
        async def publish(self, event):
            ready.set()
            await asyncio.Event().wait()
    setup.service.event_bus = HangingBus()
    pending = asyncio.create_task(adapter(resources, setup, clock=lambda: 0).deliver_pending())
    await asyncio.wait_for(ready.wait(), 1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    setup.service.event_bus = original_bus
    await adapter(resources, setup, clock=lambda: 31).deliver_pending()
    assert len(original_bus.events) == 1
    assert setup.service.get_task("material-0") == setup.tasks[0]


@pytest.mark.asyncio
async def test_timed_out_notification_retries_without_losing_core_result(resources):
    import asyncio
    setup = await setup_workflows(resources)
    job, _ = finish_job(resources, setup.tasks[0])
    original_bus = setup.service.event_bus
    class HangingBus:
        async def publish(self, event):
            await asyncio.Event().wait()
    setup.service.event_bus = HangingBus()
    await adapter(resources, setup, clock=lambda: 0, timeout_seconds=0.01).deliver_pending()
    assert resources.repository.get_job_result(job.id) is not None
    setup.service.event_bus = original_bus
    await adapter(resources, setup, clock=lambda: 6).deliver_pending()
    assert len(original_bus.events) == 1


def test_default_scope_lookup_resolves_public_id_and_internal_session_only_unambiguously(resources):
    from sqlalchemy import insert
    from qwenpaw.app.storage.schema import chats
    from qwenpaw.app.super_experts import composition
    with resources.engine.begin() as connection:
        connection.execute(insert(chats).values(
            id="public-id", agent_id="expert", session_id="internal-session", user_id="owner",
            channel="console", name="example", created_at=datetime(2026, 9, 6), updated_at=datetime(2026, 9, 6),
        ))
    by_id = composition.resolve_event_scope("public-id")
    assert by_id == composition.resolve_event_scope("internal-session")
    assert by_id["agent_id"] == "expert"
    assert by_id["user_id"] == "owner"
    with resources.engine.begin() as connection:
        connection.execute(insert(chats).values(
            id="other-public", agent_id="other-expert", session_id="internal-session", user_id="owner",
            channel="console", name="other", created_at=datetime(2026, 9, 6), updated_at=datetime(2026, 9, 6),
        ))
    assert composition.resolve_event_scope("internal-session") is None


def test_installation_must_match_current_enabled_release(tmp_path):
    from qwenpaw.app.sealed_agents.models import SealedAgentRecord
    from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry
    from qwenpaw.app.super_experts.composition import installation_is_active
    service, grant = _service(tmp_path)
    registry = SealedAgentRegistry(tmp_path / "registry")
    record = SealedAgentRecord(agent_id=grant.agent_id, name="Expert", releases=[_release()], active_release_id=_release().release_id)
    registry.upsert_agent(record)
    assert installation_is_active(grant, registry=registry)
    registry.upsert_agent(record.model_copy(update={"enabled": False}))
    assert not installation_is_active(grant, registry=registry)
    registry.upsert_agent(record)
    assert not installation_is_active(grant.model_copy(update={"package_digest": "sha256:" + "c" * 64}), registry=registry)


@pytest.mark.asyncio
async def test_application_composition_delivers_original_scope_and_can_disable_experts(resources, monkeypatch):
    import builtins
    from qwenpaw.app.runtime import aigc_events
    from qwenpaw.app.super_experts import composition
    setup = await setup_workflows(resources)
    finish_job(resources, setup.tasks[0])
    monkeypatch.setattr(composition, "get_super_expert_platform_service", lambda: setup.service)
    monkeypatch.setattr(composition, "resolve_event_scope", setup.scopes.get)
    monkeypatch.setattr(composition, "installation_is_active", lambda grant: True)
    original_import = builtins.__import__
    def no_experts(name, *args, **kwargs):
        if "super_experts" in name:
            raise AssertionError("disabled expert consumer imported")
        return original_import(name, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", no_experts)
        consumers = aigc_events.build_event_consumers(resources.repository, setup.service.event_bus, enable_super_experts=False)
        for consumer in consumers:
            await consumer.deliver_pending()
    assert [event.type for event in setup.service.event_bus.events] == ["aigc.job.updated"]
    setup.service.event_bus.events.clear()
    for consumer in aigc_events.build_event_consumers(resources.repository, setup.service.event_bus, enable_super_experts=True):
        await consumer.deliver_pending()
    assert [event.type for event in setup.service.event_bus.events] == ["super_expert_event"]
    assert setup.service.event_bus.events[0].session_id == "session-0"
