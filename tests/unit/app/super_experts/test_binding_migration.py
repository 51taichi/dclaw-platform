"""Offline migration preserves legacy physical resources and execution policy."""

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select

from qwenpaw.app.aigc.resource_store import AigcResourceStore
from qwenpaw.app.storage import schema
from qwenpaw.app.storage.repos.aigc_execution_repo import (
    AigcExecutionRepository,
)
from tests.integration.test_super_expert_aigc_workflow import (
    _catalog,
    _fixture,
    _service,
)


@pytest.fixture
async def legacy(tmp_path, monkeypatch):
    from qwenpaw.app.routers import aigc_studio, super_expert_platform

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path / "studio")
    monkeypatch.setattr(
        super_expert_platform,
        "_load_workflow_capability_catalog",
        _catalog,
    )
    service, grant = _service(tmp_path)
    result = await service.execute(
        tenant_id="tenant-a",
        user_id="user-a",
        installation_id=grant.installation_id,
        capability="aigc.workflow.create/1",
        contract_version="1",
        arguments=_fixture("three-node.json", grant.installation_id),
        idempotency_key="legacy",
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'core.sqlite'}")
    schema.create_all(engine)
    monkeypatch.setattr(
        "qwenpaw.app.storage.engine.get_app_engine",
        lambda: engine,
    )
    yield SimpleNamespace(
        engine=engine,
        repository=AigcExecutionRepository(engine),
        tasks=service.task_repository,
        binding=result["task"]["binding"],
        store=AigcResourceStore(tmp_path / "studio"),
    )
    engine.dispose()


def migrate(legacy, **kwargs):
    module = importlib.import_module(
        "qwenpaw.app.super_experts.binding_migration",
    )
    return module.migrate_bindings(
        legacy_root=legacy.tasks.root,
        studio_root=legacy.store.root,
        engine=legacy.engine,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_dry_run_and_repeated_apply_preserve_legacy_resources(legacy):
    before_task = legacy.tasks.path.read_bytes()
    canvas_path = legacy.store.path("canvases", legacy.binding["canvas_id"])
    before_canvas = canvas_path.read_bytes()
    preview = migrate(legacy)
    assert (
        preview["scanned"],
        preview["eligible"],
        preview["migrated"],
        preview["conflicts"],
    ) == (1, 1, 0, [])
    with legacy.engine.connect() as connection:
        assert (
            connection.scalar(
                select(func.count()).select_from(
                    schema.aigc_operation_journal,  # migration target table
                ),
            )
            == 0
        )
    applied = migrate(legacy, apply=True)
    assert applied["migrated"] == 1
    assert migrate(legacy, apply=True)["unchanged"] == 1
    contract = legacy.repository.get_binding(
        "user-a",
        legacy.binding["canvas_id"],
        legacy.binding["node_bindings"]["clip"],
    )
    assert (contract.provider_id, contract.model_id, contract.capability) == (
        "provider-1",
        "video-1",
        "image_to_video",
    )
    assert legacy.tasks.path.read_bytes() == before_task
    assert canvas_path.read_bytes() == before_canvas


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corruption",
    [
        "revision",
        "missing_node",
        "duplicate_physical",
        "wrong_type",
        "missing_owner",
        "wrong_task",
        "missing_blueprint",
    ],
)
async def test_conflicts_never_write_bindings(legacy, corruption):
    canvas = legacy.store.read("canvases", legacy.binding["canvas_id"])
    if corruption in {"revision", "duplicate_physical", "missing_blueprint"}:
        document = json.loads(legacy.tasks.path.read_text())
        binding = document["tasks"][legacy.binding["material_task_id"]][
            "binding"
        ]
        if corruption == "missing_blueprint":
            document["tasks"][legacy.binding["material_task_id"]][
                "workflow"
            ] = None
        elif corruption == "revision":
            binding["workflow_revision"] += 1
        else:
            binding["node_bindings"]["clip"] = binding["node_bindings"][
                "keyframe"
            ]
        legacy.tasks.path.write_text(json.dumps(document))
    elif corruption == "missing_node":
        canvas["nodes"].pop()
    elif corruption == "wrong_type":
        canvas["nodes"][0]["type"] = "video_generate"
    elif corruption == "missing_owner":
        canvas["meta"].pop("owner_user_id")
    else:
        canvas["meta"]["super_expert_material_task_id"] = "another-task"
    legacy.store.write("canvases", legacy.binding["canvas_id"], canvas)
    result = migrate(legacy, apply=True)
    assert len(result["conflicts"]) == 1
    assert result["migrated"] == 0
    assert set(result["conflicts"][0]) == {
        "material_task_id",
        "canvas_id",
        "reason",
    }
    with legacy.engine.connect() as connection:
        assert (
            connection.scalar(
                select(func.count()).select_from(
                    schema.aigc_workflow_execution_bindings,
                ),
            )
            == 0
        )


@pytest.mark.asyncio
async def test_migration_does_not_replace_conflicting_core_contract(legacy):
    from qwenpaw.app.aigc.workflow_execution import WorkflowExecutionBinding

    target = WorkflowExecutionBinding(
        owner_user_id="user-a",
        canvas_id=legacy.binding["canvas_id"],
        workflow_id=legacy.binding["workflow_id"],
        workflow_revision=1,
        node_id=legacy.binding["node_bindings"]["clip"],
        logical_node_id="clip",
        provider_id="provider-1",
        model_id="different",
        capability="image_to_video",
    )
    legacy.repository.register_bindings([target], "conflicting")
    result = migrate(legacy, apply=True)
    assert result["migrated"] == 0 and len(result["conflicts"]) == 1
    assert (
        legacy.repository.get_binding(
            "user-a",
            target.canvas_id,
            target.node_id,
        )
        == target
    )


@pytest.mark.asyncio
async def test_migrated_submission_uses_core_with_deleted_markers(
    legacy,
    monkeypatch,
):
    from qwenpaw.app.routers import aigc_studio, super_expert_platform

    migrate(legacy, apply=True)
    canvas = legacy.store.read("canvases", legacy.binding["canvas_id"])
    for node in canvas["nodes"]:
        node["data"] = {}
    canvas["meta"] = {"owner_user_id": "user-a"}
    legacy.store.write("canvases", canvas["id"], canvas)
    monkeypatch.setattr(
        aigc_studio,
        "_load_canvas_for_request",
        lambda *_: aigc_studio.Canvas(**canvas),
    )

    def unavailable():
        raise AssertionError("system must not call expert platform")

    async def available(*_):
        return object()

    monkeypatch.setattr(
        super_expert_platform,
        "get_super_expert_platform_service",
        unavailable,
    )
    monkeypatch.setattr(aigc_studio, "_find_capability", available)
    monkeypatch.setattr(
        aigc_studio,
        "_assert_job_model_policy_allowed",
        available,
    )
    body = aigc_studio.AigcJobCreate(
        canvas_id=canvas["id"],
        node_id=legacy.binding["node_bindings"]["clip"],
        provider_id="provider-1",
        model_id="video-1",
        capability="image_to_video",
    )
    await aigc_studio._validate_job_submission(SimpleNamespace(), body)
    await aigc_studio._validate_job_submission(
        SimpleNamespace(),
        body.model_copy(update={"model_id": "other"}),
    )
    with pytest.raises(HTTPException) as failure:
        await aigc_studio._validate_job_submission(
            SimpleNamespace(),
            body.model_copy(update={"capability": "text_to_video"}),
        )
    assert failure.value.status_code == 409


@pytest.mark.asyncio
async def test_managed_node_without_migration_is_not_trusted(
    legacy,
    monkeypatch,
):
    from qwenpaw.app.routers import aigc_studio

    canvas = aigc_studio.Canvas(
        **legacy.store.read("canvases", legacy.binding["canvas_id"]),
    )
    monkeypatch.setattr(
        aigc_studio,
        "_load_canvas_for_request",
        lambda *_: canvas,
    )

    async def available(*_):
        return object()

    monkeypatch.setattr(aigc_studio, "_find_capability", available)
    monkeypatch.setattr(
        aigc_studio,
        "_assert_job_model_policy_allowed",
        available,
    )
    body = aigc_studio.AigcJobCreate(
        canvas_id=canvas.id,
        node_id=legacy.binding["node_bindings"]["clip"],
        provider_id="provider-1",
        model_id="video-1",
        capability="image_to_video",
    )
    with pytest.raises(HTTPException) as failure:
        await aigc_studio._validate_job_submission(SimpleNamespace(), body)
    assert failure.value.status_code == 409
    assert failure.value.detail == "WORKFLOW_BINDING_MIGRATION_REQUIRED"


@pytest.mark.asyncio
async def test_cli_defaults_to_dry_run(legacy):
    root = Path(__file__).parents[4]
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/migrate_aigc_execution_bindings.py"),
            "--legacy-root",
            str(legacy.tasks.root),
            "--studio-root",
            str(legacy.store.root),
            "--database-url",
            str(legacy.engine.url),
        ],
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["migrated"] == 0
    with legacy.engine.connect() as connection:
        assert (
            connection.scalar(
                select(func.count()).select_from(
                    schema.aigc_operation_journal,  # migration target table
                ),
            )
            == 0
        )


def test_cli_refuses_missing_sqlite_without_creating_it(tmp_path):
    root = Path(__file__).parents[4]
    database = tmp_path / "does-not-exist.sqlite"
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/migrate_aigc_execution_bindings.py"),
            "--legacy-root",
            str(tmp_path),
            "--studio-root",
            str(tmp_path),
            "--database-url",
            f"sqlite:///{database}",
        ],
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 2
    assert "SQLITE_DATABASE_MISSING" in result.stderr
    assert not database.exists()


@pytest.mark.asyncio
async def test_migration_rejects_core_owner_conflict(legacy):
    from qwenpaw.app.aigc.workflow_execution import WorkflowExecutionBinding

    target = WorkflowExecutionBinding(
        owner_user_id="other-owner",
        canvas_id=legacy.binding["canvas_id"],
        workflow_id=legacy.binding["workflow_id"],
        workflow_revision=1,
        node_id=legacy.binding["node_bindings"]["clip"],
        logical_node_id="clip",
        provider_id="provider-1",
        model_id="video-1",
        capability="image_to_video",
    )
    legacy.repository.register_bindings([target], "other-owner-operation")
    result = migrate(legacy, apply=True)
    assert (
        result["migrated"] == 0
        and result["conflicts"][0]["reason"] == "EXECUTION_BINDING_CONFLICT"
    )
    assert (
        legacy.repository.get_binding(
            "user-a",
            target.canvas_id,
            target.node_id,
        )
        is None
    )


@pytest.mark.asyncio
async def test_schema_missing_is_reported_without_ddl(legacy, tmp_path):
    from sqlalchemy import inspect

    module = importlib.import_module(
        "qwenpaw.app.super_experts.binding_migration",
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.sqlite'}")
    with pytest.raises(ValueError, match="CORE_SCHEMA_NOT_INITIALIZED"):
        module.migrate_bindings(
            legacy_root=legacy.tasks.root,
            studio_root=legacy.store.root,
            engine=engine,
        )
    assert inspect(engine).get_table_names() == []
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("background", [False, True])
async def test_previously_queued_job_is_checked_again_before_execution(
    legacy,
    monkeypatch,
    background,
):
    from qwenpaw.app.routers import aigc_studio

    migrate(legacy, apply=True)
    canvas = aigc_studio.Canvas(
        **legacy.store.read("canvases", legacy.binding["canvas_id"]),
    )
    job = aigc_studio.AigcJob(
        id="old-queued",
        canvas_id=canvas.id,
        node_id=legacy.binding["node_bindings"]["clip"],
        provider_id="provider-1",
        model_id="wrong-old-model",
        capability="image_to_video",
        status="queued",
        created_at="2026-09-06T00:00:00Z",
        updated_at="2026-09-06T00:00:00Z",
    )
    monkeypatch.setattr(aigc_studio, "_load_job_for_request", lambda *_: job)
    monkeypatch.setattr(
        aigc_studio,
        "_load_canvas_for_request",
        lambda *_: canvas,
    )
    calls = []

    async def execute(*_):
        calls.append("execute")
        return job

    monkeypatch.setattr(aigc_studio, "_run_job_to_completion", execute)
    monkeypatch.setattr(aigc_studio, "_mark_job_running", execute)
    monkeypatch.setattr(
        aigc_studio,
        "_start_background_job_run",
        lambda *_: calls.append("background"),
    )

    async def reject_unconfigured_model(*_):
        raise HTTPException(
            status_code=422,
            detail={"code": "aigc_model_not_allowed"},
        )

    monkeypatch.setattr(
        aigc_studio,
        "_assert_job_model_policy_allowed",
        reject_unconfigured_model,
    )
    with pytest.raises(HTTPException) as failure:
        await aigc_studio.run_job(
            SimpleNamespace(),
            job.id,
            background=background,
        )
    assert failure.value.status_code == 422
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("new_node", [False, True])
async def test_managed_canvas_cannot_bypass_contract_with_new_node_id(
    legacy,
    monkeypatch,
    new_node,
):
    from qwenpaw.app.routers import aigc_studio

    migrate(legacy, apply=True)
    canvas = legacy.store.read("canvases", legacy.binding["canvas_id"])
    canvas["meta"] = {"owner_user_id": "user-a"}
    for node in canvas["nodes"]:
        node["data"] = {}
    target = dict(canvas["nodes"][-1])
    target["id"] = "new-unregistered-node"
    if new_node:
        canvas["nodes"].append(target)
    else:
        canvas["nodes"][-1] = target
    monkeypatch.setattr(
        aigc_studio,
        "_load_canvas_for_request",
        lambda *_: aigc_studio.Canvas(**canvas),
    )

    async def available(*_):
        return object()

    monkeypatch.setattr(aigc_studio, "_find_capability", available)
    monkeypatch.setattr(
        aigc_studio,
        "_assert_job_model_policy_allowed",
        available,
    )
    body = aigc_studio.AigcJobCreate(
        canvas_id=canvas["id"],
        node_id=target["id"],
        provider_id="other-provider",
        model_id="other-model",
        capability="text_to_video",
    )
    with pytest.raises(HTTPException) as failure:
        await aigc_studio._validate_job_submission(SimpleNamespace(), body)
    assert failure.value.status_code == 409
    assert failure.value.detail == "WORKFLOW_NODE_BINDING_REQUIRED"


@pytest.mark.asyncio
async def test_accepted_workflow_canvas_allows_new_unbound_node(
    legacy,
    monkeypatch,
):
    from qwenpaw.app.routers import aigc_studio
    from qwenpaw.app.super_experts import composition
    from qwenpaw.app.super_experts.models import AigcTaskStatus

    migrate(legacy, apply=True)
    canvas = legacy.store.read("canvases", legacy.binding["canvas_id"])
    task = legacy.tasks.get(legacy.binding["material_task_id"])
    accepted = task.model_copy(update={"status": AigcTaskStatus.ACCEPTED})
    monkeypatch.setattr(
        composition,
        "get_super_expert_platform_service",
        lambda: SimpleNamespace(get_task=lambda *_: accepted),
    )
    monkeypatch.setattr(
        "qwenpaw.plugins.registry.PluginRegistry.get_aigc_canvas_policies",
        lambda _self: [
            SimpleNamespace(
                plugin_id="dclaw.super-agent-support",
                name="accepted-workflow",
                callback=composition.accepted_workflow_allows_unbound_node,
            ),
        ],
    )
    parsed_canvas = aigc_studio.Canvas(**canvas)
    assert aigc_studio._accepted_workflow_allows_unbound_node(parsed_canvas)

    target = dict(canvas["nodes"][-1])
    target["id"] = "customer-added-image-node"
    target["data"] = {
        key: value
        for key, value in target.get("data", {}).items()
        if key != "workflowLogicalNodeId"
    }
    canvas["nodes"].append(target)
    monkeypatch.setattr(
        aigc_studio,
        "_load_canvas_for_request",
        lambda *_: aigc_studio.Canvas(**canvas),
    )

    async def available(*_):
        return object()

    monkeypatch.setattr(aigc_studio, "_find_capability", available)
    monkeypatch.setattr(
        aigc_studio,
        "_assert_job_model_policy_allowed",
        available,
    )
    body = aigc_studio.AigcJobCreate(
        canvas_id=canvas["id"],
        node_id=target["id"],
        provider_id="other-provider",
        model_id="other-model",
        capability="text_to_video",
    )

    await aigc_studio._validate_job_submission(SimpleNamespace(), body)
