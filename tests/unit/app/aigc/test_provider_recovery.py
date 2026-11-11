"""Recovery queries the accepted provider task; it never submits it twice."""

import asyncio
from types import SimpleNamespace

import pytest
import httpx

from tests.unit.app.aigc.test_job_lifecycle import resources


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter,count", [("mxapi_seedance2", 1), ("mxapi_grok_video", 1), ("mxapi_veo_video", 1), ("mxapi_jimeng_video", 1), ("mxapi_gpt_image", 2), ("mxapi_nano2", 2)])
async def test_accepted_tasks_recover_without_second_submission(resources, monkeypatch, adapter, count):
    from qwenpaw.app.routers import aigc_studio
    from qwenpaw.app.billing.model_publication import ModelPublicationService
    from fastapi import HTTPException

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", resources.store.root)
    monkeypatch.setattr(ModelPublicationService, "is_published", lambda *_: True)
    submitted, queried = [], []
    resources.job.inputs = {"prompt": "A classroom scene"}
    resources.job.model_id = {
        "mxapi_seedance2": "seedance2",
        "mxapi_grok_video": "grok-imagine-video-1.5-fast",
        "mxapi_veo_video": "veo-3.1-fast",
        "mxapi_jimeng_video": "doubao-seedance-1-0-pro-fast-251015",
        "mxapi_gpt_image": "gpt-image-2",
        "mxapi_nano2": "nano-banana-2",
    }[adapter]
    if count > 1:
        resources.job.capability = "text_to_image"
        resources.job.parameters = {"n": count}
    resources.store.write("jobs", "job", resources.job.model_dump())

    async def provider(*_):
        return SimpleNamespace(id="p", api_key="test-only", base_url="https://provider.example"), SimpleNamespace(id=resources.job.model_id)

    class ProviderHTTP:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def post(self, url, **_kwargs):
            remote_id = f"accepted-{len(submitted) + 1}"
            submitted.append(remote_id)
            return httpx.Response(200, json={"code": 200, "data": {"task_id": remote_id}}, request=httpx.Request("POST", url))

    async def poll(_provider, task_id, *_):
        queried.append(task_id)
        if len(queried) <= count:
            raise TimeoutError("query interrupted after acceptance")
        if count > 1:
            return f"https://assets.example/{task_id}.png"
        return "https://assets.example/clip.mp4", {}

    async def download(_url):
        return b"test-video", "video/mp4"

    async def save(*_args, **_kwargs):
        asset = resources.asset.model_copy(deep=True)
        asset.id = f"asset-{len(queried)}-{_kwargs['filename']}".replace(".", "-")
        asset.kind = _kwargs["kind"]
        return asset

    monkeypatch.setattr(aigc_studio, "_find_provider_model", provider)
    monkeypatch.setattr(aigc_studio, "_aigc_adapter_for", lambda *_: adapter)
    monkeypatch.setattr(aigc_studio.httpx, "AsyncClient", ProviderHTTP)
    monkeypatch.setattr(aigc_studio, "_mxapi_seedance_poll_task", poll)
    monkeypatch.setattr(aigc_studio, "_mxapi_grok_poll_task", poll)
    monkeypatch.setattr(aigc_studio, "_mxapi_veo_poll_task", poll)
    monkeypatch.setattr(aigc_studio, "_mxapi_poll_task", poll)
    monkeypatch.setattr(aigc_studio, "_download_remote_asset", download)
    monkeypatch.setattr(aigc_studio, "_save_generated_asset", save)
    with pytest.raises(HTTPException) as interrupted:
        await aigc_studio._run_job_to_completion(SimpleNamespace(), "job")
    assert interrupted.value.detail == "JOB_RESULT_RECONCILIATION_REQUIRED"
    def unavailable_input(*_args):
        raise RuntimeError("original asset cannot be signed again")
    for name in ("_mxapi_seedance_submit_body", "_mxapi_grok_submit_body", "_mxapi_veo_submit_body", "_mxapi_jimeng_submit_body", "_mxapi_reference_images"):
        monkeypatch.setattr(aigc_studio, name, unavailable_input)
    monkeypatch.setattr(ModelPublicationService, "is_published", lambda *_: False)
    async def no_catalog(*_):
        return None
    monkeypatch.setattr(aigc_studio, "_find_capability", no_catalog)
    request = SimpleNamespace(state=SimpleNamespace(user_id="owner", role="user"))
    result = await aigc_studio.run_job(request, "job")
    assert result.status == "succeeded"
    expected_ids = [f"accepted-{index + 1}" for index in range(count)]
    assert [asset.meta["mxapi_task_id"] for asset in result.outputs] == expected_ids
    assert submitted == expected_ids
    assert queried == expected_ids * 2


def test_only_expired_attempt_can_be_reclaimed_and_stale_worker_cannot_save(resources):
    repo = resources.repository
    command = resources.job.model_dump(mode="json")
    old = repo.begin_job_attempt("job", "owner", command=command, now=0)
    repo.prepare_provider_task("job", old, "video", "mxapi_seedance2", now=1)
    repo.accept_provider_task("job", old, "video", "remote-1", now=1)
    with pytest.raises(ValueError, match="JOB_RECONCILIATION_REQUIRED"):
        repo.resume_job_attempt("job", "owner", command=command, now=2)
    resumed = repo.resume_job_attempt("job", "owner", command=command, now=121)
    assert resumed != old
    with pytest.raises(ValueError, match="JOB_ATTEMPT_MISMATCH"):
        repo.accept_provider_task("job", old, "video", "remote-2", now=122)
    assert repo.prepare_provider_task("job", resumed, "video", "mxapi_seedance2", now=122) == "remote-1"


def test_expired_worker_cannot_commit_result_even_before_reclaim(resources, monkeypatch):
    from qwenpaw.app.storage.repos import aigc_execution_repo

    token = resources.repository.begin_job_attempt("job", "owner", now=0)
    snapshot = resources.job.model_dump(mode="json")
    snapshot["status"] = "succeeded"
    monkeypatch.setattr(aigc_execution_repo.time, "time", lambda: 121)
    with pytest.raises(ValueError, match="JOB_ATTEMPT_MISMATCH"):
        resources.repository.save_job_result("owner", snapshot, attempt_token=token)
    assert resources.repository.get_job_result("job") is None
    assert resources.repository.list_domain_events() == []


def test_recovery_does_not_accept_changed_execution_command(resources):
    repo = resources.repository
    command = resources.job.model_dump(mode="json")
    token = repo.begin_job_attempt("job", "owner", command=command, now=0)
    repo.prepare_provider_task("job", token, "video", "mxapi_seedance2", now=1)
    repo.accept_provider_task("job", token, "video", "remote-1", now=1)
    repo.finish_job_attempt("job", token, uncertain=True)
    for changed in [{**command, "model_id": "other"}, {**command, "inputs": {"prompt": "changed"}}]:
        with pytest.raises(ValueError, match="JOB_COMMAND_MISMATCH"):
            repo.resume_job_attempt("job", "owner", command=changed, now=2)


def test_recovery_rejects_changed_command_or_unaccepted_provider_submission(resources):
    repo = resources.repository
    command = resources.job.model_dump(mode="json")
    token = repo.begin_job_attempt("job", "owner", command=command, now=0)
    repo.prepare_provider_task("job", token, "video", "mxapi_seedance2", now=1)
    repo.finish_job_attempt("job", token, uncertain=True)
    with pytest.raises(ValueError, match="JOB_RECONCILIATION_REQUIRED"):
        repo.resume_job_attempt("job", "owner", command=command, now=2)


@pytest.mark.asyncio
async def test_rejected_submission_is_durable_and_does_not_submit_again(resources, monkeypatch):
    from qwenpaw.app.aigc.provider_execution import ProviderExecution
    from qwenpaw.app.routers import aigc_studio

    posts = []
    class ProviderHTTP:
        def __init__(self, **_kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
        async def post(self, url, **_kwargs):
            posts.append(url)
            return httpx.Response(400, json={"message": "bad image"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(aigc_studio.httpx, "AsyncClient", ProviderHTTP)
    repo = resources.repository
    token = repo.begin_job_attempt("job", "owner")
    for _ in range(2):
        execution = ProviderExecution(repo, "job", token, read_only=False)
        with pytest.raises(RuntimeError, match="bad image"):
            await aigc_studio._mxapi_submit_request(
                "https://provider.example", {}, {}, accepted_codes={200}, error_message="failed",
                execution=execution, slot="image-0", adapter="mxapi_gpt_image",
            )
    assert posts == ["https://provider.example"]


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ["image", "seedance", "grok"])
async def test_provider_confirmed_failure_is_not_transport_uncertainty(monkeypatch, adapter):
    from qwenpaw.app.aigc.provider_errors import ProviderTaskFailed
    from qwenpaw.app.routers import aigc_studio

    class ProviderHTTP:
        def __init__(self, **_kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
        async def get(self, url, **_kwargs):
            return httpx.Response(200, json={"code": 200, "data": {"status": "failed", "error_message": "generation rejected"}}, request=httpx.Request("GET", url))

    monkeypatch.setattr(aigc_studio.httpx, "AsyncClient", ProviderHTTP)
    provider = SimpleNamespace(api_key="test-only", base_url="https://provider.example")
    with pytest.raises(ProviderTaskFailed, match="generation rejected"):
        if adapter == "image":
            await aigc_studio._mxapi_query_task(provider, "accepted-1", "mxapi_gpt_image")
        elif adapter == "seedance":
            await aigc_studio._mxapi_seedance_query_task(provider, "accepted-1")
        else:
            await aigc_studio._mxapi_grok_query_task(provider, "accepted-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_failure", [False, True])
async def test_cancelled_job_cannot_be_resurrected_by_late_provider_result(resources, monkeypatch, prior_failure):
    from qwenpaw.app.routers import aigc_studio
    from qwenpaw.app.billing.model_publication import ModelPublicationService

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", resources.store.root)
    monkeypatch.setattr(ModelPublicationService, "is_published", lambda *_: True)
    if prior_failure:
        from tests.unit.app.aigc.test_job_lifecycle import lifecycle
        lifecycle(resources).record_failure(resources.job, "old failure", owner_user_id="owner")
    started, release = asyncio.Event(), asyncio.Event()
    async def accepted():
        return "remote-1"
    async def generate(_request, _job, execution):
        await execution.submit("video", "mxapi_seedance2", accepted)
        started.set()
        await release.wait()
        return [resources.asset]
    monkeypatch.setattr(aigc_studio, "_execute_job", generate)
    request = SimpleNamespace(state=SimpleNamespace(user_id="owner", role="user"))
    running = asyncio.create_task(aigc_studio._run_job_to_completion(request, "job"))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        cancelled = await aigc_studio.cancel_job(request, "job")
        assert cancelled.status == "cancelled"
    finally:
        release.set()
    assert (await running).status == "cancelled"
    assert resources.store.read("jobs", "job")["status"] == "cancelled"
    assert all(event.event_type != "job.succeeded" for event in resources.repository.list_domain_events())


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_at", ["notification", "provider_lookup", "seedream_reference"])
async def test_cancel_before_execution_never_starts_provider(resources, monkeypatch, cancel_at):
    from qwenpaw.app.routers import aigc_studio
    from qwenpaw.app.billing.model_publication import ModelPublicationService

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", resources.store.root)
    monkeypatch.setattr(ModelPublicationService, "is_published", lambda *_: True)
    resources.job.capability = "text_to_image"
    resources.job.inputs = {"prompt": "A classroom"}
    resources.store.write("jobs", "job", resources.job.model_dump())
    request = SimpleNamespace(state=SimpleNamespace(user_id="owner", role="user"))
    calls = []
    async def notify(job, _message):
        if cancel_at == "notification" and job.status == "running":
            assert (await aigc_studio.cancel_job(request, "job")).status == "cancelled"
    async def find(*_args):
        if cancel_at == "provider_lookup":
            assert (await aigc_studio.cancel_job(request, "job")).status == "cancelled"
        return SimpleNamespace(id="p", api_key="test-only"), SimpleNamespace(id="m")
    async def generate(*_args, **_kwargs):
        calls.append("paid generation")
        return [resources.asset]
    async def references(*_args):
        assert (await aigc_studio.cancel_job(request, "job")).status == "cancelled"
        return []
    monkeypatch.setattr(aigc_studio, "_publish_job_event", notify)
    monkeypatch.setattr(aigc_studio, "_find_provider_model", find)
    monkeypatch.setattr(aigc_studio, "_aigc_adapter_for", lambda *_: "volcengine_seedream" if cancel_at == "seedream_reference" else "openai_image")
    monkeypatch.setattr(aigc_studio, "_execute_openai_image", generate)
    monkeypatch.setattr(aigc_studio, "_seedream_reference_images", references)
    monkeypatch.setattr(aigc_studio, "_openai_client", lambda *_: SimpleNamespace(images=SimpleNamespace(generate=generate)))
    assert (await aigc_studio._run_job_to_completion(request, "job")).status == "cancelled"
    assert calls == []


@pytest.mark.asyncio
async def test_cancel_recovers_committed_success_before_stale_json(resources, monkeypatch):
    from qwenpaw.app.routers import aigc_studio
    from tests.unit.app.aigc.test_job_lifecycle import lifecycle

    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", resources.store.root)
    with monkeypatch.context() as patch:
        def unavailable(*_):
            raise OSError("projection unavailable")
        patch.setattr(resources.store, "write", unavailable)
        lifecycle(resources).record_success(resources.job, [resources.asset], owner_user_id="owner")
    request = SimpleNamespace(state=SimpleNamespace(user_id="owner", role="user"))
    assert (await aigc_studio.cancel_job(request, "job")).status == "succeeded"
    assert resources.store.read("jobs", "job")["status"] == "succeeded"


@pytest.mark.asyncio
async def test_all_explicitly_failed_image_slots_remain_a_known_failure(resources, monkeypatch):
    from qwenpaw.app.aigc.provider_errors import ProviderTaskFailed
    from qwenpaw.app.routers import aigc_studio

    resources.job.capability = "text_to_image"
    resources.job.inputs = {"prompt": "A classroom"}
    resources.job.parameters = {"n": 2}
    async def accepted(*_args, **_kwargs):
        return "accepted-task"
    async def failed(*_args):
        raise ProviderTaskFailed("generation rejected")
    monkeypatch.setattr(aigc_studio, "_mxapi_submit_task", accepted)
    monkeypatch.setattr(aigc_studio, "_mxapi_poll_task", failed)
    with pytest.raises(ProviderTaskFailed, match="0/2 succeeded"):
        await aigc_studio._execute_mxapi_gpt_image(SimpleNamespace(), resources.job, SimpleNamespace(), adapter="mxapi_gpt_image")


@pytest.mark.asyncio
async def test_background_cancel_does_not_report_unhandled_callback(monkeypatch):
    from qwenpaw.app.routers import aigc_studio

    async def cancelled(*_):
        raise asyncio.CancelledError
    monkeypatch.setattr(aigc_studio, "_run_job_to_completion", cancelled)
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    errors = []
    loop.set_exception_handler(lambda _loop, context: errors.append(context))
    try:
        aigc_studio._start_background_job_run(SimpleNamespace(), "cancel-cleanup-test")
        task = aigc_studio._JOB_RUN_TASKS["cancel-cleanup-test"]
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)
        assert errors == []
        assert "cancel-cleanup-test" not in aigc_studio._JOB_RUN_TASKS
    finally:
        loop.set_exception_handler(previous)
