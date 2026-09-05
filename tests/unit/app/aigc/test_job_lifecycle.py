"""Durable terminal results must not be undone by projection or notification."""

import importlib
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from qwenpaw.app.aigc.models import AigcAsset, AigcJob, CanvasNode, CanvasUpsert
from qwenpaw.app.aigc.canvas_service import AigcCanvasService
from qwenpaw.app.aigc.resource_store import AigcResourceStore
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.repos.aigc_execution_repo import AigcExecutionRepository


@pytest.fixture
def resources(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'core.sqlite'}")
    create_all(engine)
    monkeypatch.setattr("qwenpaw.app.storage.engine.get_app_engine", lambda: engine)
    store = AigcResourceStore(tmp_path / "studio")
    canvas = AigcCanvasService(store).create("owner", CanvasUpsert(nodes=[
        CanvasNode(id="video", type="video_generate", position={"x": 0, "y": 0}),
    ]))
    job = AigcJob(id="job", canvas_id=canvas.id, node_id="video", capability="text_to_video",
                  provider_id="p", model_id="m", status="queued", created_at="start", updated_at="start")
    asset = AigcAsset(id="asset", kind="video", name="Clip", path="private/path.mp4", created_at="end",
                      meta={"owner_user_id": "owner", "canvas_id": canvas.id, "node_id": "video"})
    store.write("jobs", job.id, job.model_dump())
    store.write("assets", asset.id, asset.model_dump())
    yield SimpleNamespace(engine=engine, store=store, job=job, asset=asset,
                          repository=AigcExecutionRepository(engine))
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["notification", "running_notification", "canvas_projection"])
async def test_success_is_not_changed_to_failure_after_provider_completed(resources, monkeypatch, fault):
    from qwenpaw.app.routers import aigc_studio
    from qwenpaw.app.billing.model_publication import ModelPublicationService

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", resources.store.root)
    monkeypatch.setattr(ModelPublicationService, "is_published", lambda *_: True)

    async def generate(*_):
        return [resources.asset]

    async def notify(job, _message):
        if (fault == "notification" and job.status == "succeeded"
                or fault == "running_notification" and job.status == "running"):
            raise OSError("notification down")

    original_write = AigcResourceStore.write

    def write(store, kind, resource_id, value):
        if fault == "canvas_projection" and kind == "canvases":
            raise OSError("canvas projection interrupted")
        return original_write(store, kind, resource_id, value)

    monkeypatch.setattr(aigc_studio, "_execute_job", generate)
    monkeypatch.setattr(aigc_studio, "_publish_job_event", notify)
    monkeypatch.setattr(AigcResourceStore, "write", write)
    result = await aigc_studio._run_job_to_completion(SimpleNamespace(), resources.job.id)
    assert result.status == "succeeded"
    assert result.outputs[0].id == "asset"
    assert resources.store.read("jobs", "job")["status"] == "succeeded"
    if fault == "canvas_projection":
        assert resources.repository.get_job_result("job")["projection_status"] == "pending"


def lifecycle(resources):
    module = importlib.import_module("qwenpaw.app.aigc.job_lifecycle")
    return module.AigcJobLifecycle(resources.store, resources.repository)


def test_success_survives_projection_failure_and_restart(resources, monkeypatch):
    first = lifecycle(resources)
    original_write = resources.store.write

    def interrupted(kind, *args, **kwargs):
        if kind in {"jobs", "canvases"}:
            raise OSError("projection interrupted")
        return original_write(kind, *args, **kwargs)

    with monkeypatch.context() as changes:
        changes.setattr(resources.store, "write", interrupted)
        result = first.record_success(resources.job, [resources.asset], owner_user_id="owner")
    assert result.status == "succeeded"
    assert resources.store.read("jobs", "job")["status"] == "queued"
    assert lifecycle(resources).recover_projections() == 1
    assert resources.store.read("jobs", "job")["status"] == "succeeded"
    canvas = resources.store.read("canvases", resources.job.canvas_id)
    assert canvas["nodes"][0]["data"]["outputs"][0]["id"] == "asset"
    assert lifecycle(resources).recover_projections() == 0


def test_repeated_success_records_one_event_without_private_media_path(resources):
    service = lifecycle(resources)
    first = service.record_success(resources.job, [resources.asset], owner_user_id="owner")
    service.record_success(first, [resources.asset], owner_user_id="owner")
    events = resources.repository.list_domain_events()
    assert [event.event_type for event in events] == ["job.succeeded", "asset.ready"]
    assert events[0].owner_user_id == "owner"
    assert "private/path" not in str([event.model_dump() for event in events])
    assert all("installation_id" not in event.model_dump() for event in events)


@pytest.mark.asyncio
async def test_unrecorded_provider_result_cannot_start_generation_again(resources, monkeypatch):
    from fastapi import HTTPException
    from qwenpaw.app.routers import aigc_studio
    from qwenpaw.app.billing.model_publication import ModelPublicationService

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", resources.store.root)
    monkeypatch.setattr(ModelPublicationService, "is_published", lambda *_: True)
    calls = []

    async def generate(*_):
        calls.append("paid-generation")
        return [resources.asset]

    def fail(*_args, **_kwargs):
        raise OSError("result database unavailable")

    monkeypatch.setattr(aigc_studio, "_execute_job", generate)
    with monkeypatch.context() as change:
        change.setattr(AigcExecutionRepository, "save_job_result", fail)
        with pytest.raises(HTTPException) as first:
            await aigc_studio._run_job_to_completion(SimpleNamespace(), "job")
        assert first.value.status_code == 503
    with pytest.raises(HTTPException) as retry:
        await aigc_studio._run_job_to_completion(SimpleNamespace(), "job")
    assert retry.value.status_code == 409
    assert retry.value.detail == "JOB_RECONCILIATION_REQUIRED"
    assert calls == ["paid-generation"]


def test_ownerless_projection_recovers_only_with_trusted_compatibility(resources, monkeypatch):
    canvas = resources.store.read("canvases", resources.job.canvas_id)
    canvas["meta"] = {}
    resources.store.write("canvases", canvas["id"], canvas)
    original_write = resources.store.write

    def interrupted(kind, *args, **kwargs):
        if kind == "canvases":
            raise OSError("projection interrupted")
        return original_write(kind, *args, **kwargs)

    with monkeypatch.context() as changes:
        changes.setattr(resources.store, "write", interrupted)
        lifecycle(resources).record_success(resources.job, [resources.asset],
                                            owner_user_id="owner", allow_ownerless=True)
    assert lifecycle(resources).recover_projections() == 1
    assert resources.store.read("canvases", canvas["id"])["nodes"][0]["data"]["outputs"][0]["id"] == "asset"


def test_ownerless_projection_is_not_implicitly_authorized(resources):
    canvas = resources.store.read("canvases", resources.job.canvas_id)
    canvas["meta"] = {}
    resources.store.write("canvases", canvas["id"], canvas)
    lifecycle(resources).record_success(resources.job, [resources.asset], owner_user_id="owner")
    assert lifecycle(resources).recover_projections() == 0
    assert not resources.store.read("canvases", canvas["id"])["nodes"][0]["data"].get("outputs")


def test_durable_success_prevents_a_second_attempt_after_stale_read(resources):
    token = resources.repository.begin_job_attempt("job", "owner")
    lifecycle(resources).record_success(resources.job, [resources.asset], owner_user_id="owner")
    resources.repository.finish_job_attempt("job", token)
    with pytest.raises(ValueError, match="JOB_ALREADY_SUCCEEDED"):
        resources.repository.begin_job_attempt("job", "owner")


def test_old_pending_projection_cannot_overwrite_new_success(resources):
    failed = resources.job.model_copy(update={"status": "failed", "error": "provider unavailable"})
    stale = resources.repository.save_job_result("owner", failed.model_dump(mode="json"))
    lifecycle(resources).record_success(resources.job, [resources.asset], owner_user_id="owner")
    lifecycle(resources).project_result(stale)
    assert resources.store.read("jobs", "job")["status"] == "succeeded"
    assert resources.store.read("jobs", "job")["outputs"][0]["id"] == "asset"


def test_unrecoverable_first_projection_does_not_starve_next_result(resources):
    failed_canvas_job = resources.job.model_copy(update={"id": "a-job", "canvas_id": "deleted",
                                                         "status": "succeeded", "outputs": []})
    valid = resources.job.model_copy(update={"status": "succeeded", "outputs": [resources.asset]})
    resources.repository.save_job_result("owner", failed_canvas_job.model_dump(mode="json"))
    resources.repository.save_job_result("owner", valid.model_dump(mode="json"))
    assert lifecycle(resources).recover_projections(limit=1) == 0
    assert lifecycle(resources).recover_projections(limit=1) == 1
    assert resources.store.read("jobs", "job")["status"] == "succeeded"


def test_projection_does_not_erase_customer_edit_during_merge(resources, monkeypatch):
    from qwenpaw.app.aigc import job_lifecycle

    original = job_lifecycle._merge_node_output

    def edit_during_merge(canvas, job):
        second = AigcResourceStore(resources.store.root)
        edited = second.read("canvases", canvas.id)
        edited["name"] = "Customer renamed this canvas"
        second.write("canvases", canvas.id, edited)
        return original(canvas, job)

    with monkeypatch.context() as changes:
        changes.setattr(job_lifecycle, "_merge_node_output", edit_during_merge)
        lifecycle(resources).record_success(resources.job, [resources.asset], owner_user_id="owner")
    assert resources.store.read("canvases", resources.job.canvas_id)["name"] == "Customer renamed this canvas"
    assert lifecycle(resources).recover_projections() == 1
    canvas = resources.store.read("canvases", resources.job.canvas_id)
    assert canvas["name"] == "Customer renamed this canvas"
    assert canvas["nodes"][0]["data"]["outputs"][0]["id"] == "asset"


def test_result_and_attempt_completion_commit_together(resources):
    from sqlalchemy import select
    from qwenpaw.app.storage.schema import aigc_job_attempts

    token = resources.repository.begin_job_attempt("job", "owner")
    lifecycle(resources).record_success(resources.job, [resources.asset],
                                        owner_user_id="owner", attempt_token=token)
    with resources.engine.connect() as connection:
        assert connection.execute(select(aigc_job_attempts.c.phase)).scalar_one() == "finished"
    assert resources.repository.get_job_result("job")["resource_version"] == 1
    assert len(resources.repository.list_domain_events()) == 2


def test_event_write_failure_rolls_back_result_and_attempt_completion(resources):
    from sqlalchemy import event, select
    from qwenpaw.app.storage.schema import aigc_job_attempts

    token = resources.repository.begin_job_attempt("job", "owner")

    def reject_event(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO aigc_domain_events"):
            raise OSError("event write unavailable")

    event.listen(resources.engine, "before_cursor_execute", reject_event)
    try:
        with pytest.raises(OSError, match="event write unavailable"):
            lifecycle(resources).record_success(resources.job, [resources.asset],
                                                owner_user_id="owner", attempt_token=token)
    finally:
        event.remove(resources.engine, "before_cursor_execute", reject_event)
    assert resources.repository.get_job_result("job") is None
    assert resources.repository.list_domain_events() == []
    with resources.engine.connect() as connection:
        assert connection.execute(select(aigc_job_attempts.c.phase)).scalar_one() == "running"


@pytest.mark.parametrize("older_finishes_last", [False, True])
def test_older_job_cannot_replace_newer_job_node_output(resources, monkeypatch, older_finishes_last):
    service = lifecycle(resources)
    newer = resources.job.model_copy(update={"id": "new-job", "created_at": "2026-09-06T02:00:00+00:00"})
    older = resources.job.model_copy(update={"created_at": "2026-09-06T01:00:00+00:00"})
    new_asset = resources.asset.model_copy(update={"id": "new-asset"})
    resources.store.write("assets", new_asset.id, new_asset.model_dump())
    if older_finishes_last:
        service.record_success(newer, [new_asset], owner_user_id="owner")
        service.record_success(older, [resources.asset], owner_user_id="owner")
    else:
        with monkeypatch.context() as changes:
            changes.setattr(service, "_write_projection", lambda _: (_ for _ in ()).throw(OSError("interrupted")))
            service.record_success(older, [resources.asset], owner_user_id="owner")
        service.record_success(newer, [new_asset], owner_user_id="owner")
        assert lifecycle(resources).recover_projections() == 1
    node = resources.store.read("canvases", older.canvas_id)["nodes"][0]
    assert node["data"]["job_id"] == "new-job"
    assert node["data"]["outputs"][0]["id"] == "new-asset"
    assert resources.store.read("jobs", older.id)["outputs"][0]["id"] == "asset"


@pytest.mark.asyncio
async def test_failure_before_provider_call_does_not_strand_attempt(resources, monkeypatch):
    from qwenpaw.app.routers import aigc_studio
    from qwenpaw.app.billing.model_publication import ModelPublicationService

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", resources.store.root)
    monkeypatch.setattr(ModelPublicationService, "is_published", lambda *_: True)
    calls = []

    async def generate(*_):
        calls.append("provider")
        return [resources.asset]

    def fail(*_):
        raise OSError("running record unavailable")

    monkeypatch.setattr(aigc_studio, "_execute_job", generate)
    with monkeypatch.context() as changes:
        changes.setattr(aigc_studio, "_write_json", fail)
        with pytest.raises(OSError, match="running record unavailable"):
            await aigc_studio._run_job_to_completion(SimpleNamespace(), "job")
    result = await aigc_studio._run_job_to_completion(SimpleNamespace(), "job")
    assert result.status == "succeeded"
    assert calls == ["provider"]


def test_ownerless_canvas_has_one_result_order_across_authorized_admins(resources, monkeypatch):
    canvas = resources.store.read("canvases", resources.job.canvas_id)
    canvas["meta"] = {}
    resources.store.write("canvases", canvas["id"], canvas)
    old = resources.job.model_copy(update={"created_at": "2026-09-06T01:00:00Z"})
    new = resources.job.model_copy(update={"id": "new-job", "created_at": "2026-09-06T02:00:00Z"})
    old_asset = resources.asset.model_copy(update={"meta": {**resources.asset.meta, "owner_user_id": "admin-a"}})
    new_asset = resources.asset.model_copy(update={"id": "new-asset", "meta": {**resources.asset.meta, "owner_user_id": "admin-b"}})
    resources.store.write("assets", old_asset.id, old_asset.model_dump())
    resources.store.write("assets", new_asset.id, new_asset.model_dump())
    first = lifecycle(resources)
    with monkeypatch.context() as changes:
        changes.setattr(first, "_write_projection", lambda _: (_ for _ in ()).throw(OSError("interrupted")))
        first.record_success(old, [old_asset], owner_user_id="admin-a", allow_ownerless=True)
    lifecycle(resources).record_success(new, [new_asset], owner_user_id="admin-b", allow_ownerless=True)
    assert lifecycle(resources).recover_projections() == 1
    assert resources.store.read("canvases", canvas["id"])["nodes"][0]["data"]["job_id"] == "new-job"
