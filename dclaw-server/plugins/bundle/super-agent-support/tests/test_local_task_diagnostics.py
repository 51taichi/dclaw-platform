from __future__ import annotations

import asyncio
import importlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from jsonschema import FormatChecker, validate
import pytest

from store import StateStore
from devkit.local_task_diagnostics_api_demo import read as read_demo
from super_agent.publication import PublisherPublication
from super_agent.local_task_diagnostics import (
    read_local_task_diagnostics, read_local_task_diagnostics_v2,
    sanitize_localize_event,
)


ROOT = Path(__file__).parents[1]
SCHEMA = json.loads((ROOT / "devkit/schemas/local-task-diagnostics-v1/response.schema.json").read_text())
SCHEMA_V2 = json.loads((ROOT / "devkit/schemas/local-task-diagnostics-v2/response.schema.json").read_text())


def _task(store, *, agent="comic", tenant="local", installation="old",
          invocation="a" * 32, capability="aigc.task.assets.localize/1"):
    return store.create_task(
        user_id="customer", agent_id=agent, agent_name=agent,
        invocation_id=invocation, capability_id=capability,
        task_input={"material_task_id": "private", "download_url": "https://private.example/secret"},
        idempotency_key=installation + invocation, device_id="device",
        max_concurrency=4, tenant_id=tenant, session_id="session",
        installation_id=installation, release_id="release-" + installation,
    )[0]


def _read(store, reference, *, reference_type="task", owner=None, grants=None,
          now=None, version=1):
    reader = (read_local_task_diagnostics_v2 if version == 2
              else read_local_task_diagnostics)
    return reader(
        agent_id="comic", tenant_id="local", reference=reference,
        reference_type=reference_type, grants=grants or SimpleNamespace(
            list_grants=lambda: [SimpleNamespace(
                tenant_id="local", agent_id="comic", installation_id="old",
                release_id="release-old",
            ), SimpleNamespace(
                tenant_id="local", agent_id="comic", installation_id="new",
                release_id="release-new",
            )],
        ),
        owner_resolver=owner or (lambda _: {
            "tenant_id": "local", "agent_id": "comic", "user_id": "customer",
        }),
        task_lookup=store.diagnostic_tasks,
        device_lookup=lambda *_: {"online": True, "runner_version": "1.4.6"},
        now=now,
    )


def test_local_task_diagnostics_cross_installation_and_privacy(tmp_path):
    store = StateStore(tmp_path / "tasks.db")
    old = _task(store)
    new = _task(store, installation="new")
    for task in (old, new):
        store.append_event(task["task_id"], 1, "started", sanitize_localize_event(
            "started", {"helper_version": "1.4.6"},
        ))
        store.append_event(task["task_id"], 2, "failed", sanitize_localize_event(
            "failed", {
                "code": "HELPER_JSON_LIFETIME_ERROR", "phase": "download_prepare",
                "category": "json_lifetime", "helper_version": "1.4.6",
                "download_url": "https://private.example/secret",
                "stack": "C:\\private\\trace",
            },
        ))
        store.update_task(task["task_id"], status="failed", error={
            "code": "HELPER_JSON_LIFETIME_ERROR",
        })
    result = _read(store, "a" * 32, reference_type="invocation")
    validate(result, SCHEMA, format_checker=FormatChecker())
    assert result["status"] == "found"
    assert len(result["tasks"]) == 2
    assert all(item["responsibility"] == "platform" for item in result["tasks"])
    assert all(item["helper_version"] == "1.4.6" for item in result["tasks"])
    assert "private.example" not in json.dumps(result)
    assert "stack" not in json.dumps(result)
    stored = store.diagnostic_tasks(
        tenant_id="local", agent_id="comic", reference=old["task_id"],
        reference_type="task", cutoff=0,
    )
    assert "download_url" not in stored[0]["events"][-1]["payload_json"]


def test_local_task_diagnostics_legacy_and_scope_denial(tmp_path):
    store = StateStore(tmp_path / "tasks.db")
    task = _task(store)
    store.append_event(task["task_id"], 1, "failed", {
        "code": "AIGC_ASSET_DOWNLOAD_FAILED",
        "message": "Cannot access a disposed object. Object name: JsonDocument",
    })
    store.update_task(task["task_id"], status="failed", error={
        "code": "AIGC_ASSET_DOWNLOAD_FAILED", "message": "private",
    })
    found = _read(store, task["task_id"])
    validate(found, SCHEMA, format_checker=FormatChecker())
    item = found["tasks"][0]
    assert item["failure_evidence"] == "historical_detail_not_recorded"
    assert item["first_failure_phase"] is None
    assert item["exception_category"] is None
    assert item["helper_version"] is None
    assert "disposed" not in json.dumps(found)
    assert _read(store, task["task_id"], owner=lambda _: {
        "tenant_id": "local", "agent_id": "comic", "user_id": "other",
    })["status"] == "no_record"
    assert _read(store, task["task_id"], grants=SimpleNamespace(
        list_grants=lambda: [],
    ))["status"] == "no_record"
    assert _read(store, "f" * 32)["status"] == "no_record"
    assert _read(store, task["task_id"], now=task["created_at"] + 31 * 86400)["status"] == "no_record"


def test_v2_reports_generic_helper_failure_without_inventing_phase(tmp_path):
    store = StateStore(tmp_path / "tasks.db")
    task = _task(store, capability="dclaw.ffmpeg.task.plan")
    store.append_event(task["task_id"], 1, "failed", {
        "code": "RUNNER.EXECUTION_FAILED", "message": "ObjectDisposedException",
        "path": "C:\\private\\source.mp4", "url": "https://private.example/secret",
    })
    store.update_task(task["task_id"], status="failed", error={
        "code": "RUNNER.EXECUTION_FAILED", "message": "ObjectDisposedException",
    })
    assert _read(store, task["task_id"])["status"] == "no_record"
    result = _read(store, task["task_id"], version=2)
    validate(result, SCHEMA_V2, format_checker=FormatChecker())
    item = result["tasks"][0]
    assert item["capability"] == "dclaw.ffmpeg.task.plan"
    assert item["error_code"] == "RUNNER.EXECUTION_FAILED"
    assert item["exception_category"] == "json_lifetime"
    assert item["category_evidence"] == "recorded"
    assert item["phase_evidence"] == "historical_detail_not_recorded"
    assert item["first_failure_phase"] is None
    assert item["responsibility"] == "platform"
    assert item["recovery_action"] == "upgrade_helper"
    assert "private.example" not in json.dumps(result)
    assert "source.mp4" not in json.dumps(result)
    assert "ObjectDisposedException" not in json.dumps(result)
    assert _read(store, task["task_id"], version=2, owner=lambda _: {
        "tenant_id": "local", "agent_id": "comic", "user_id": "other",
    })["status"] == "no_record"
    assert _read(store, task["task_id"], version=2, grants=SimpleNamespace(
        list_grants=lambda: [],
    ))["status"] == "no_record"
    assert _read(store, task["task_id"], version=2,
                 now=task["created_at"] + 31 * 86400)["status"] == "no_record"
    foreign = _task(store, agent="another", installation="new",
                    capability="dclaw.ffmpeg.task.plan")
    assert _read(store, foreign["task_id"], version=2)["status"] == "no_record"


def test_v2_reports_new_helper_stage_and_version(tmp_path):
    store = StateStore(tmp_path / "tasks.db")
    task = _task(store, capability="dclaw.ffmpeg.task.plan")
    payload = {
        "code": "LOCAL_FILE_REF.FILE_MISSING", "phase": "file_binding",
        "category": "file_binding", "helper_version": "1.4.12",
    }
    validate({
        "type": "task.event", "task_id": task["task_id"], "sequence": 1,
        "event_type": "failed", "payload": payload,
    }, json.loads((ROOT / "schemas/device-message.schema.json").read_text()))
    store.append_event(task["task_id"], 1, "failed", payload)
    store.update_task(task["task_id"], status="failed", error={
        "code": "LOCAL_FILE_REF.FILE_MISSING",
    })
    result = _read(store, "a" * 32, reference_type="invocation", version=2)
    validate(result, SCHEMA_V2, format_checker=FormatChecker())
    item = result["tasks"][0]
    assert item["first_failure_phase"] == "file_binding"
    assert item["exception_category"] == "file_binding"
    assert item["responsibility"] == "environment"
    assert item["recovery_action"] == "rebind_files"
    assert item["phase_evidence"] == item["category_evidence"] == "recorded"
    assert item["helper_version"] == "1.4.12"


def test_v2_devkit_demo_uses_formal_route_and_schema(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "tasks.db")
    task = _task(store, capability="dclaw.ffmpeg.task.plan")
    result = _read(store, task["task_id"], version=2)

    def respond(request, timeout):
        assert request.full_url.endswith(
            f"/local-task-diagnostics/v2/tasks/{task['task_id']}?agent_id=comic"
        )
        assert timeout == 20
        return io.BytesIO(json.dumps(result).encode())

    monkeypatch.setattr("devkit.local_task_diagnostics_api_demo.urlopen", respond)
    assert read_demo("https://dclaw.example", "comic", task["task_id"],
                     "tasks", "test-token", 2) == result


def test_local_task_diagnostic_route_requires_owned_expert(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "tasks.db")
    task = _task(store)
    monkeypatch.setattr("super_agent.local_host.read_diagnostic_tasks", store.diagnostic_tasks)
    monkeypatch.setattr("super_agent.local_host.read_diagnostic_device", lambda *_: None)
    monkeypatch.setattr("super_agent.composition.resolve_event_scope", lambda _: {
        "tenant_id": "local", "agent_id": "comic", "user_id": "customer",
    })
    publication = object.__new__(PublisherPublication)
    publication.repository = SimpleNamespace(
        agent_owner=lambda agent: ("local", "developer") if agent == "comic" else None,
    )
    publication.handler = SimpleNamespace(grant_repository=SimpleNamespace(
        list_grants=lambda: [SimpleNamespace(
            tenant_id="local", agent_id="comic", installation_id="old",
            release_id="release-old",
        )],
    ))
    publication._diagnostic_read_times = {}
    publication.router = APIRouter()
    publication._register_routes()
    app = FastAPI()

    @app.middleware("http")
    async def actor(request, call_next):
        request.state.tenant_id = "local"
        request.state.user_id = "developer"
        return await call_next(request)

    app.include_router(publication.router)
    client = TestClient(app)
    path = f"/local-task-diagnostics/v1/tasks/{task['task_id']}"
    assert client.get(path, params={"agent_id": "foreign"}).status_code == 404
    assert client.get(path, params={"agent_id": "comic"}).json()["tasks"][0]["task_id"] == task["task_id"]
    v2_path = f"/local-task-diagnostics/v2/tasks/{task['task_id']}"
    assert client.get(v2_path, params={"agent_id": "foreign"}).status_code == 404
    assert client.get(v2_path, params={"agent_id": "comic"}).json()["contract"] == "developer.local-task.diagnostics.read/2"
    assert client.get("/local-task-diagnostics/v1/tasks/invalid", params={"agent_id": "comic"}).status_code == 422


def test_local_task_event_rejects_untrusted_diagnostic_fields():
    payload = sanitize_localize_event("failed", {
        "code": "UNTRUSTED", "phase": "C:\\private", "category": ["secret"],
        "helper_version": "1.4.6/private", "download_url": "https://private.example",
    })
    assert payload == {
        "code": "AIGC_ASSET_DOWNLOAD_FAILED", "phase": None,
        "category": None, "helper_version": None,
    }


def test_localization_task_replay_does_not_create_or_dispatch_another_task(tmp_path):
    store = StateStore(tmp_path / "tasks.db")
    original = _task(store)
    replay, created = store.create_task(
        user_id="customer", agent_id="comic", agent_name="comic",
        invocation_id="b" * 32, capability_id="aigc.task.assets.localize/1",
        task_input={"material_task_id": "private", "download_url": "https://private.example/secret"},
        idempotency_key="old" + "a" * 32, device_id="device",
        max_concurrency=4, tenant_id="local", session_id="session",
        installation_id="old", release_id="release-old",
    )
    assert created is False
    assert replay["task_id"] == original["task_id"]
    assert _read(store, "b" * 32, reference_type="invocation")["status"] == "no_record"


def test_service_filters_helper_event_before_storage_and_rejects_old_runner(tmp_path):
    plugin_root = ROOT
    spec = importlib.util.spec_from_file_location(
        "support_regression", plugin_root / "__init__.py",
        submodule_search_locations=[str(plugin_root)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    service_module = importlib.import_module("support_regression.service")
    store = StateStore(tmp_path / "tasks.db")
    task = _task(store)
    service = service_module.LocalExecutionService(store, None, None)
    asyncio.run(service.handle_device_message("device", "customer", {
        "type": "task.event", "task_id": task["task_id"], "sequence": 1,
        "event_type": "failed", "payload": {
            "code": "HELPER_JSON_LIFETIME_ERROR", "phase": "download_prepare",
            "category": "json_lifetime", "helper_version": "1.4.6",
            "secret": "https://private.example/asset",
        },
    }))
    stored = store.diagnostic_tasks(
        tenant_id="local", agent_id="comic", reference=task["task_id"],
        reference_type="task", cutoff=0,
    )
    assert "private.example" not in stored[0]["events"][0]["payload_json"]
    service.store = SimpleNamespace(list_devices=lambda _: [{
        "device_id": "device", "status": "online", "protocol_version": "2",
        "runner_version": "1.4.5",
    }])
    service._connections["device"] = object()
    with pytest.raises(service_module.PublicError) as failure:
        service._select_aigc_transfer_device("customer")
    assert failure.value.code == "LOCAL_GATEWAY.DEVICE_NOT_READY"


def test_localize_replay_dispatches_only_once(tmp_path):
    plugin_root = ROOT
    spec = importlib.util.spec_from_file_location(
        "support_replay", plugin_root / "__init__.py",
        submodule_search_locations=[str(plugin_root)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    service_module = importlib.import_module("support_replay.service")
    store = StateStore(tmp_path / "tasks.db")
    service = service_module.LocalExecutionService(store, None, None)
    service._select_aigc_transfer_device = lambda _: {"device_id": "device"}
    sends = []

    async def send(device_id, message):
        sends.append((device_id, message["type"]))

    service._send = send
    identity = {
        "u": "customer", "a": "comic", "n": "comic", "i": "a" * 32,
        "s": "session", "g": "old", "r": "release-old", "t": "local",
    }
    arguments = {
        "material_task_id": "material", "idempotency_key": "same-key",
        "assets": [{"asset_id": "one", "slot": "clip_01"}],
    }
    first = asyncio.run(service._aigc_assets_localize(arguments, identity, "trace"))
    second = asyncio.run(service._aigc_assets_localize(arguments, identity, "trace"))
    assert first["task_id"] == second["task_id"]
    assert second["idempotent_replay"] is True
    assert sends == [("device", "aigc.assets.localize")]
    assert store.diagnostic_tasks(
        tenant_id="local", agent_id="comic", reference=first["task_id"],
        reference_type="task", cutoff=0,
    )[0]["dispatched_at"] is not None
