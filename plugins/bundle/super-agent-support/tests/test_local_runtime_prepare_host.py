from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

from contracts import ERRORS
from super_agent.capabilities import PLATFORM_CAPABILITY_CATALOG_V1
from super_agent.local_host import bind_local_service, prepare_local_runtime
from devkit.local_runtime_prepare_api_demo import prepare_local_runtime as demo_prepare


SCHEMAS = Path(__file__).parents[1] / "devkit/schemas/local-runtime-prepare-v1"
EXAMPLES = Path(__file__).parents[1] / "devkit/examples/local-runtime-prepare-v1"
SCOPE = {
    "tenant_id": "tenant", "user_id": "customer", "session_id": "chat",
    "agent_id": "expert", "installation_id": "installation",
    "release_id": "release", "invocation_id": "invocation",
    "granted_capabilities": ("local.execution.session/1", "local.runtime.prepare/1"),
}
CAPABILITY = "expert.video.compose"


def _validate_response(value):
    schema = json.loads((SCHEMAS / "response.schema.json").read_text())
    validate(value, schema)


@pytest.mark.asyncio
async def test_host_prepare_uses_trusted_turn_and_exact_reported_version():
    class Service:
        state = "preparing"
        calls = []

        async def _local_runtime_prepare(self, arguments, identity, trace):
            self.calls.append((arguments, identity, trace))
            return {
                "state": self.state, "capability_id": CAPABILITY,
                "package_id": CAPABILITY, "package_version": "0.1.0",
                "min_runner_version": "1.3.0", "device_id": "device-1",
                "runner_version": "1.4.7",
                "user_action": "none" if self.state == "ready" else "wait",
            }

    service = Service()
    bind_local_service(service)
    try:
        first = await prepare_local_runtime(
            arguments={"capability_id": CAPABILITY}, **SCOPE,
        )
        _validate_response(first)
        assert first["status"] == "preparing"
        assert first["package_version"] == "0.1.0"
        assert service.calls[0][0] == {"capability": CAPABILITY}
        assert service.calls[0][1] == {
            "t": "tenant", "u": "customer", "s": "chat", "a": "expert",
            "g": "installation", "r": "release", "i": "invocation",
            "n": "expert", "c": SCOPE["granted_capabilities"],
        }
        await prepare_local_runtime(
            arguments={"capability_id": CAPABILITY, "device_id": "device-1"},
            **SCOPE,
        )
        assert service.calls[-1][0] == {
            "capability": CAPABILITY, "device_id": "device-1",
        }
        service.state = "ready"
        second = await prepare_local_runtime(
            arguments={"capability_id": CAPABILITY}, **SCOPE,
        )
        _validate_response(second)
        assert second["status"] == "ready"
        assert second["runner_version"] == "1.4.7"
    finally:
        bind_local_service(None)


@pytest.mark.asyncio
async def test_host_prepare_closes_invalid_and_missing_requests():
    class Service:
        error = ERRORS["CAPABILITY_NOT_FOUND"]

        async def _local_runtime_prepare(self, arguments, identity, trace):
            raise self.error

    service = Service()
    bind_local_service(service)
    try:
        for arguments in (
            {}, {"capability_id": "bad"},
            {"capability_id": CAPABILITY, "device_id": ""},
            {"capability_id": CAPABILITY, "dclaw_session_token": "forbidden"},
        ):
            receipt = await prepare_local_runtime(arguments=arguments, **SCOPE)
            _validate_response(receipt)
            assert receipt["status"] == "invalid_request"
        missing = await prepare_local_runtime(
            arguments={"capability_id": CAPABILITY}, **SCOPE,
        )
        _validate_response(missing)
        assert missing["status"] == "rejected"
        assert missing["error_code"] == "LOCAL_GATEWAY.CAPABILITY_NOT_FOUND"
        service.error = ERRORS["DEVICE_NOT_READY"]
        disconnected = await prepare_local_runtime(
            arguments={"capability_id": CAPABILITY}, **SCOPE,
        )
        _validate_response(disconnected)
        assert disconnected["user_action"] == "reconnect_runner"
        unauthorized = await prepare_local_runtime(
            arguments={"capability_id": CAPABILITY},
            **(SCOPE | {"granted_capabilities": ()}),
        )
        _validate_response(unauthorized)
        assert unauthorized["error_code"] == "LOCAL_GATEWAY.CAPABILITY_NOT_AUTHORIZED"
    finally:
        bind_local_service(None)
    unavailable = await prepare_local_runtime(
        arguments={"capability_id": CAPABILITY}, **SCOPE,
    )
    _validate_response(unavailable)
    assert unavailable["status"] == "unavailable"


@pytest.mark.asyncio
async def test_devkit_demo_validates_host_receipt_and_manifest_dependency():
    class Host:
        calls = []

        async def call(self, capability, request):
            self.calls.append((capability, request))
            return {
                "contract": capability, "status": "device_not_ready",
                "capability_id": CAPABILITY, "package_id": CAPABILITY,
                "package_version": "0.1.0", "min_runner_version": "1.3.0",
                "device_id": None, "runner_version": None,
                "user_action": "open_dclaw",
            }

    host = Host()
    receipt = await demo_prepare(
        host, capability_id=CAPABILITY,
        package_id=CAPABILITY, package_version="0.1.0",
    )
    assert receipt["status"] == "device_not_ready"
    assert host.calls == [
        ("local.runtime.prepare/1", {"capability_id": CAPABILITY}),
    ]
    with pytest.raises(ValidationError):
        await demo_prepare(
            host, capability_id="invalid",
            package_id=CAPABILITY, package_version="0.1.0",
        )
    with pytest.raises(ValueError, match="pinned version"):
        await demo_prepare(
            host, capability_id=CAPABILITY,
            package_id=CAPABILITY, package_version="0.2.0",
        )
    assert PLATFORM_CAPABILITY_CATALOG_V1["local.runtime.prepare/1"].dependencies == (
        "local.execution.session/1",
    )


def test_devkit_examples_validate_against_closed_schemas():
    request_schema = json.loads((SCHEMAS / "request.schema.json").read_text())
    validate(json.loads((EXAMPLES / "request.sample.json").read_text()), request_schema)
    for name in ("preparing.sample.json", "ready.sample.json"):
        _validate_response(json.loads((EXAMPLES / name).read_text()))
