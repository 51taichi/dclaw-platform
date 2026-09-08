"""Core execution contracts survive restarts, conflicts and interrupted writes."""

import importlib
import itertools
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, func

from qwenpaw.app.storage import schema


def binding(**changes):
    module = importlib.import_module("qwenpaw.app.aigc.workflow_execution")
    values = dict(owner_user_id="u", canvas_id="c", workflow_id="w", workflow_revision=1,
                  node_id="n", logical_node_id="clip", provider_id="p", model_id="m",
                  capability="text_to_video")
    return module.WorkflowExecutionBinding(**{**values, **changes})


@pytest.fixture
def engine(tmp_path):
    database = create_engine(f"sqlite:///{tmp_path / 'execution.sqlite'}")
    schema.create_all(database)
    yield database
    database.dispose()


def repository(engine):
    module = importlib.import_module("qwenpaw.app.storage.repos.aigc_execution_repo")
    return module.AigcExecutionRepository(engine)


@pytest.mark.parametrize("field,value", [("provider_id", "other"), ("model_id", "other"),
                                         ("capability", "image_to_video")])
def test_binding_rejects_each_execution_mismatch(field, value):
    target = binding()
    module = importlib.import_module("qwenpaw.app.aigc.workflow_execution")
    values = {"provider_id": "p", "model_id": "m", "capability": "text_to_video"}
    with pytest.raises(ValueError, match="EXECUTION_BINDING_MISMATCH"):
        module.validate_execution(target, **{**values, field: value})
    module.validate_execution(target, **values)


def test_bindings_survive_repository_restart_and_replay(engine):
    first = repository(engine)
    first.register_bindings([binding()], "operation")
    recovered = repository(engine)
    recovered.register_bindings([binding()], "operation")
    assert recovered.get_binding("u", "c", "n").model_id == "m"
    assert recovered.get_binding("other", "c", "n") is None
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(schema.aigc_workflow_execution_bindings)) == 1


def test_operation_key_cannot_be_reused_for_changed_contract(engine):
    repo = repository(engine)
    repo.register_bindings([binding()], "operation")
    with pytest.raises(ValueError, match="OPERATION_CONFLICT"):
        repo.register_bindings([binding(model_id="other")], "operation")
    assert repo.get_binding("u", "c", "n").model_id == "m"


def test_conflicting_batch_rolls_back_all_new_nodes(engine):
    repo = repository(engine)
    repo.register_bindings([binding()], "first")
    with pytest.raises(ValueError, match="EXECUTION_BINDING_CONFLICT"):
        repo.register_bindings([
            binding(node_id="new", logical_node_id="new"), binding(model_id="other"),
        ], "second")
    assert repo.get_binding("u", "c", "new") is None
    assert repo.get_binding("u", "c", "n").model_id == "m"


def test_registration_rejects_mixed_owners(engine):
    repo = repository(engine)
    with pytest.raises(ValueError, match="BINDING_SCOPE_MISMATCH"):
        repo.register_bindings([binding(), binding(owner_user_id="other", node_id="two")], "op")
    assert repo.get_binding("u", "c", "n") is None


@pytest.mark.parametrize("changes", [{"owner_user_id": ""}, {"workflow_revision": 0},
                                    {"model_id": " "}, {"workflow_revision": True}])
def test_binding_rejects_invalid_identity(changes):
    with pytest.raises(ValueError):
        binding(**changes)


def compiled_workflow(prefix="first"):
    from qwenpaw.aigc.workflow_compiler import AvailableWorkflowModel, compile_workflow
    from qwenpaw.aigc.workflow_contract import WorkflowBlueprint
    fixture = Path(__file__).parents[3] / "fixtures/super_expert/aigc-workflow-v2/three-node.json"
    blueprint = WorkflowBlueprint.model_validate(json.loads(fixture.read_text())["workflow"])
    sequence = itertools.count()
    compiled = compile_workflow(blueprint, available_models=tuple(
        AvailableWorkflowModel(provider_id="provider-1", model_id=model,
                               capabilities=frozenset(capabilities))
        for model, capabilities in [("text-1", ["storyboard"]),
                                    ("image-1", ["text_to_image"]),
                                    ("video-1", ["image_to_video", "text_to_video"])]
    ), id_factory=lambda kind: f"{prefix}-{kind}-{next(sequence)}",
        asset_resolver=lambda _asset_id: None)
    return blueprint.model_dump(mode="json"), compiled


def managed_service(engine, tmp_path):
    from qwenpaw.app.aigc.resource_store import AigcResourceStore
    module = importlib.import_module("qwenpaw.app.aigc.workflow_execution")
    return module.AigcWorkflowExecutionService(AigcResourceStore(tmp_path / "studio"), repository(engine))


@pytest.mark.parametrize("failure_point", ["before_file", "after_file", "bindings", "mark_applied"])
def test_interrupted_creation_recovers_same_canvas_and_contract(engine, tmp_path, monkeypatch, failure_point):
    service = managed_service(engine, tmp_path)
    command, compiled = compiled_workflow()
    original_write = service.store.write

    def broken_write(*args, **kwargs):
        if failure_point == "after_file":
            original_write(*args, **kwargs)
        raise OSError("injected interruption")

    def fail(*args, **kwargs):
        raise OSError("injected interruption")

    with monkeypatch.context() as changes:
        if failure_point in {"before_file", "after_file"}:
            changes.setattr(service.store, "write", broken_write)
        elif failure_point == "bindings":
            changes.setattr(service.repository, "_insert_bindings", fail)
        else:
            changes.setattr(service.repository, "mark_applied", fail)
        with pytest.raises(OSError, match="injected interruption"):
            service.create("u", "create-op", command=command, compiled=compiled)

    prepared = service.repository.get_operation("u", "create-op")
    canvas_id = prepared["canvas_id"]
    assert prepared["phase"] == "PREPARED"
    with pytest.raises(ValueError, match="WORKFLOW_OPERATION_INCOMPLETE"):
        service.repository.get_binding("u", canvas_id, compiled.output_node_id)

    restarted = managed_service(engine, tmp_path)
    _, new_attempt = compiled_workflow("retry")
    canvas, recovered_compiled = restarted.create("u", "create-op", command=command, compiled=new_attempt)
    assert canvas.id == canvas_id
    assert recovered_compiled.bindings == compiled.bindings
    assert len(list((tmp_path / "studio/canvases").glob("*.json"))) == 1
    execution = restarted.repository.get_binding("u", canvas.id, compiled.output_node_id)
    assert (execution.provider_id, execution.model_id, execution.capability) == ("provider-1", "video-1", "image_to_video")


def test_applied_replay_preserves_customer_canvas_edits(engine, tmp_path):
    service = managed_service(engine, tmp_path)
    command, compiled = compiled_workflow()
    canvas, _ = service.create("u", "op", command=command, compiled=compiled)
    modified = service.store.read("canvases", canvas.id)
    modified["name"] = "Customer edit"
    service.store.write("canvases", canvas.id, modified)
    second, _ = service.create("u", "op", command=command, compiled=compiled)
    assert second.name == "Customer edit"
    assert second.id == canvas.id


def test_changed_command_cannot_reuse_prepared_operation(engine, tmp_path):
    service = managed_service(engine, tmp_path)
    command, compiled = compiled_workflow()
    service.create("u", "op", command=command, compiled=compiled)
    with pytest.raises(ValueError, match="OPERATION_CONFLICT"):
        service.create("u", "op", command={**command, "title": "Other"}, compiled=compiled)
    assert len(list((tmp_path / "studio/canvases").glob("*.json"))) == 1


def test_parallel_retries_share_one_physical_graph(engine, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)

    def create(prefix):
        command, compiled = compiled_workflow(prefix)
        service = managed_service(engine, tmp_path)
        barrier.wait(timeout=5)
        canvas, saved = service.create("u", "concurrent", command=command, compiled=compiled)
        return canvas.id, saved.bindings

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(create, ["one", "two"]))
    assert results[0] == results[1]
    assert len(list((tmp_path / "studio/canvases").glob("*.json"))) == 1


def test_recovery_refuses_to_overwrite_changed_unfinished_canvas(engine, tmp_path, monkeypatch):
    service = managed_service(engine, tmp_path)
    command, compiled = compiled_workflow()

    def fail(*_args, **_kwargs):
        raise OSError("mark failed")

    with monkeypatch.context() as changes:
        changes.setattr(service.repository, "mark_applied", fail)
        with pytest.raises(OSError):
            service.create("u", "op", command=command, compiled=compiled)
    op = service.repository.get_operation("u", "op")
    edited = service.store.read("canvases", op["canvas_id"])
    edited["name"] = "Existing user change"
    service.store.write("canvases", op["canvas_id"], edited)
    with pytest.raises(ValueError, match="WORKFLOW_RESOURCE_CONFLICT"):
        service.create("u", "op", command=command, compiled=compiled)
    assert service.store.read("canvases", op["canvas_id"])["name"] == "Existing user change"


def test_completed_replay_does_not_resurrect_deleted_canvas(engine, tmp_path):
    service = managed_service(engine, tmp_path)
    command, compiled = compiled_workflow()
    canvas, _ = service.create("u", "op", command=command, compiled=compiled)
    service.store.delete("canvases", canvas.id)
    with pytest.raises(ValueError, match="RESOURCE_NOT_FOUND"):
        service.create("u", "op", command=command, compiled=compiled)
    assert not list((tmp_path / "studio/canvases").glob("*.json"))


def test_recovery_does_not_rewrite_existing_canvas_after_validation(engine, tmp_path, monkeypatch):
    service = managed_service(engine, tmp_path)
    command, compiled = compiled_workflow()

    def fail(*_args, **_kwargs):
        raise OSError("mark failed")

    with monkeypatch.context() as changes:
        changes.setattr(service.repository, "mark_applied", fail)
        with pytest.raises(OSError):
            service.create("u", "op", command=command, compiled=compiled)
    op = service.repository.get_operation("u", "op")
    original_insert = service.repository._insert_bindings

    def concurrent_edit(*args, **kwargs):
        edited = service.store.read("canvases", op["canvas_id"])
        edited["name"] = "Concurrent user change"
        service.store.write("canvases", op["canvas_id"], edited)
        original_insert(*args, **kwargs)

    monkeypatch.setattr(service.repository, "_insert_bindings", concurrent_edit)
    service.create("u", "op", command=command, compiled=compiled)
    assert service.store.read("canvases", op["canvas_id"])["name"] == "Concurrent user change"
