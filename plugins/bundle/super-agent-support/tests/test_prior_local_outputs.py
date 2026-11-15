from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
from pathlib import Path
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from super_agent.local_host import bind_local_service, bind_localized_task_outputs
from store import StateStore
from devkit.local_task_outputs_bind_api_demo import start_from_localized_outputs

ROOT = Path(__file__).parents[1]
DEVICE_MESSAGE_SCHEMA = json.loads(
    (ROOT / "schemas/device-message.schema.json").read_text(encoding="utf-8"),
)


SOURCE = {
    "task_id": "source-task", "tenant_id": "tenant", "user_id": "user",
    "session_id": "session", "agent_id": "agent", "agent_name": "agent",
    "installation_id": "old-install", "release_id": "old-release",
    "device_id": "device", "capability_id": "aigc.task.assets.localize/1",
    "status": "succeeded",
    "input": {"assets": [
        {"asset_id": "asset-1", "slot": "clip_01", "order": 0, "usage": "timeline_clip", "destination": "res"},
        {"asset_id": "asset-2", "slot": "clip_02", "order": 1, "usage": "timeline_clip", "destination": "res"},
    ]},
    "result": {"files": [
        {"asset_id": "asset-1", "slot": "clip_01", "order": 0,
         "usage": "timeline_clip", "relative_path": "res/clip_01.mp4",
         "sha256": "a" * 64, "size_bytes": 5},
        {"asset_id": "asset-2", "slot": "clip_02", "order": 1,
         "usage": "timeline_clip", "relative_path": "res/clip_02.mp4",
         "sha256": "b" * 64, "size_bytes": 6},
    ]},
}
SCOPE = {
    "tenant_id": "tenant", "user_id": "user", "session_id": "session",
    "agent_id": "agent", "installation_id": "new-install",
    "release_id": "new-release", "invocation_id": "invocation",
    "compatible_installation_releases": {"new-install": "new-release", "old-install": "old-release"},
}


@pytest.mark.asyncio
async def test_bind_prior_outputs_scopes_and_preserves_order():
    source = deepcopy(SOURCE)

    class Service:
        store = SimpleNamespace(get_task=lambda task_id, user_id: source)

        async def bind_localized_outputs(self, *, identity, source_task, files):
            assert identity["g"] == "new-install" and source_task is source
            assert [item["slot"] for item in files] == ["clip_01", "clip_02"]
            return {"status": "bound", "expires_at": 123,
                    "files": [{"slot": item["slot"], "order": item["order"],
                               "file": {"local_file_ref": "lfr_" + "a" * 32}}
                              for item in files]}

    bind_local_service(Service())
    try:
        arguments = {"source_task_id": "source-task", "slots": ["clip_02", "clip_01"]}
        result = await bind_localized_task_outputs(arguments=arguments, **SCOPE)
        assert result["status"] == "bound"
        assert [item["slot"] for item in result["files"]] == ["clip_01", "clip_02"]
        for override in (
            {"tenant_id": "other"}, {"user_id": "other"},
            {"session_id": "other"}, {"agent_id": "other"},
            {"compatible_installation_releases": {"new-install": "new-release"}},
            {"compatible_installation_releases": {"old-install": "wrong-release"}},
        ):
            assert (await bind_localized_task_outputs(
                arguments=arguments, **(SCOPE | override))) ["status"] == "not_found"
        source["status"] = "failed"
        assert (await bind_localized_task_outputs(arguments=arguments, **SCOPE))["status"] == "source_not_ready"
        source["status"] = "succeeded"
        source["result"]["files"][0]["sha256"] = "bad"
        assert (await bind_localized_task_outputs(arguments=arguments, **SCOPE))["status"] == "unavailable"
    finally:
        bind_local_service(None)


@pytest.mark.asyncio
async def test_bind_device_response_is_atomic_and_version_gated(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "support_prior_outputs", ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    LocalExecutionService = importlib.import_module(
        "support_prior_outputs.service").LocalExecutionService
    service = object.__new__(LocalExecutionService)
    service.store = SimpleNamespace(save_local_file_refs=lambda *args, **kwargs: True)
    device = {"device_id": "device", "runner_version": "1.4.7"}
    monkeypatch.setattr(service, "_require_file_device", lambda user, device_id: device)
    async def respond(device_id, request):
        assert request["type"] == "aigc.assets.bind"
        assert request["source_task_id"] == "source-task"
        return {"status": "bound", "files": [
            {"slot": "clip_01", "order": 0, "file": {
                "local_file_ref": "lfr_" + "a" * 32, "display_name": "clip_01.mp4",
                "mime_type": "video/mp4", "size_bytes": 5, "device_id": "device",
                "last_modified_ms": 123,
            }},
        ]}
    monkeypatch.setattr(service, "_request_device", respond)
    identity = {"t": "tenant", "u": "user", "s": "session", "a": "agent",
                "g": "new-install", "r": "new-release", "i": "invocation"}
    result = await service.bind_localized_outputs(
        identity=identity, source_task=SOURCE,
        files=[SOURCE["result"]["files"][0]])
    assert result["status"] == "bound"
    device["runner_version"] = "1.4.6"
    with pytest.raises(Exception):
        await service.bind_localized_outputs(
            identity=identity, source_task=SOURCE,
            files=[SOURCE["result"]["files"][0]])


@pytest.mark.asyncio
async def test_bind_helper_reply_passes_gateway_schema_and_completes_request():
    spec = importlib.util.spec_from_file_location(
        "support_bind_reply", ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    service_class = importlib.import_module("support_bind_reply.service").LocalExecutionService
    service = object.__new__(service_class)

    class DeviceSocket:
        async def send_json(self, message):
            sent.append(message)

    sent = []
    service._lock = asyncio.Lock()
    service._connections = {"device": DeviceSocket()}
    service._device_requests = {}
    pending = asyncio.create_task(service._request_device("device", {"type": "aigc.assets.bind"}))
    await asyncio.sleep(0)
    reply = {
        "type": "aigc.assets.bind.result", "request_id": sent[0]["request_id"],
        "status": "bound", "files": [{"slot": "clip_01", "order": 0, "file": {
            "local_file_ref": "lfr_" + "a" * 32,
            "display_name": "clip_01.mp4", "mime_type": "video/mp4",
            "size_bytes": 5, "device_id": "device", "last_modified_ms": 123,
        }}],
    }
    validator = Draft202012Validator(DEVICE_MESSAGE_SCHEMA)
    assert DEVICE_MESSAGE_SCHEMA == json.loads(
        (ROOT / "devkit/schemas/super-agent-support-v1/device-message.schema.json")
        .read_text(encoding="utf-8"),
    )
    validator.validate(reply)
    await service.handle_device_message("device", "user", reply)
    assert await asyncio.wait_for(pending, timeout=1) == reply
    assert service._device_requests == {}

    rejected = {"type": "aigc.assets.bind.result", "request_id": reply["request_id"],
                "status": "rejected", "error_code": "LOCAL_SOURCE.FILE_CHANGED"}
    validator.validate(rejected)
    for invalid in (
        reply | {"unexpected": True},
        reply | {"status": "rejected"},
        rejected | {"error_code": "INTERNAL_EXCEPTION"},
        rejected | {"files": []},
    ):
        assert not validator.is_valid(invalid)


@pytest.mark.asyncio
async def test_bind_device_timeout_returns_stable_rejection(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "support_bind_timeout", ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
    module = importlib.import_module("support_bind_timeout.service")
    service = object.__new__(module.LocalExecutionService)
    monkeypatch.setattr(module, "PRIOR_OUTPUT_BIND_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(service, "_require_file_device", lambda user, device_id: {
        "device_id": "device", "runner_version": "1.4.9",
    })

    async def no_reply(device_id, message):
        await asyncio.Event().wait()

    monkeypatch.setattr(service, "_request_device", no_reply)
    result = await service.bind_localized_outputs(
        identity={"t": "tenant", "u": "user", "s": "session", "a": "agent",
                  "g": "install", "r": "release", "i": "invocation"},
        source_task=SOURCE, files=[SOURCE["result"]["files"][0]],
    )
    assert result == {"status": "rejected", "error_code": "LOCAL_SOURCE.UNAVAILABLE"}


def test_prior_reference_batch_rolls_back_on_conflict(tmp_path):
    store = StateStore(tmp_path / "state.db")
    scope = {key: value for key, value in SCOPE.items()
             if key not in {"compatible_installation_releases"}}
    def item(slot, ref):
        return {"slot": slot, "file": {
            "local_file_ref": "lfr_" + ref * 32,
            "display_name": slot + ".mp4", "mime_type": "video/mp4",
            "size_bytes": 5, "last_modified_ms": 123,
        }}
    assert store.save_local_file_refs(
        [item("clip_01", "a")], scope=scope, source_task_id="task",
        device_id="device", expires_at=9999999999)
    assert not store.save_local_file_refs(
        [item("clip_02", "b"), item("clip_01", "a")],
        scope=scope, source_task_id="task", device_id="device",
        expires_at=9999999999)
    assert store.get_local_file_ref("lfr_" + "b" * 32) is None


@pytest.mark.asyncio
async def test_devkit_demo_passes_bindings_to_next_task():
    calls = []

    class Host:
        async def call(self, capability, request):
            calls.append((capability, request))
            if capability == "local.task.outputs.bind/1":
                return {"contract": capability, "status": "bound", "expires_at": 9999999999,
                        "files": [{"slot": "clip_01", "order": 0, "file": {
                            "local_file_ref": "lfr_" + "a" * 32,
                            "display_name": "clip_01.mp4", "mime_type": "video/mp4",
                            "size_bytes": 5, "device_id": "device", "last_modified_ms": 123,
                        }}]}
            return {"contract": "local.task.receipt/1", "task_id": "next-task",
                    "capability_id": "video.render", "idempotency_key": "render-1",
                    "status": "queued", "error_code": None, "artifact_ids": [],
                    "result_sha256": None}

    receipt = await start_from_localized_outputs(
        Host(), source_task_id="source-task", slots=["clip_01"],
        capability_id="video.render", input_data={}, idempotency_key="render-1")
    assert receipt["task_id"] == "next-task"
    assert calls[1][1]["local_file_bindings"] == {
        "clip_01": {"local_file_ref": "lfr_" + "a" * 32, "access": "read"}}
