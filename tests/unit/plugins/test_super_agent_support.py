from __future__ import annotations

import base64
import asyncio
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
import zipfile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from jsonschema import Draft202012Validator
from starlette.testclient import TestClient

from qwenpaw.app.super_experts.capabilities import (
    get_platform_capability_catalog,
)
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.registry import PluginRegistry


ROOT = Path(__file__).parents[3]
PLUGIN_ROOT = ROOT / "plugins" / "bundle" / "super-agent-support"


@pytest.fixture
def plugin_module():
    name = "test_dclaw_super_agent_support"
    spec = importlib.util.spec_from_file_location(
        name,
        PLUGIN_ROOT / "plugin.py",
        submodule_search_locations=[str(PLUGIN_ROOT)],
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    try:
        yield module
    finally:
        for key in list(sys.modules):
            if key == name or key.startswith(name + "."):
                sys.modules.pop(key, None)


@pytest.mark.asyncio
async def test_plugin_load_and_unload_are_isolated(tmp_path):
    previous = PluginRegistry._instance
    PluginRegistry._instance = None
    loader = PluginLoader([PLUGIN_ROOT.parent])
    app = FastAPI()
    loader.registry.set_plugin_http_app(app)
    manifest = loader._load_manifest(PLUGIN_ROOT / "plugin.json")
    try:
        record = await loader.load_plugin(
            manifest,
            PLUGIN_ROOT,
            {"state_dir": str(tmp_path)},
        )
        assert record.manifest.id == "dclaw.super-agent-support"
        assert "local.execution.session/1" in get_platform_capability_catalog()
        assert (
            "local.environment.preflight/1"
            in get_platform_capability_catalog()
        )
        assert any(
            getattr(route, "path", None) == "/api/super-agent-support"
            for route in app.routes
        )
        context = await loader.registry.enrich_workspace_context(
            {
                "user_id": "user-1",
                "session_id": "session-1",
                "agent_id": "agent-1",
                "agent_name": "Agent One",
                "installation_id": "install-1",
                "release_id": "release-1",
            },
            granted_capabilities={"local.execution.session/1": "1"},
            invocation_id="invocation-1",
        )
        assert context["local_execution_session_token"]

        await loader.unload_plugin(record.manifest.id)

        assert (
            "local.execution.session/1"
            not in get_platform_capability_catalog()
        )
        assert (
            "local.environment.preflight/1"
            not in get_platform_capability_catalog()
        )
        assert not any(
            getattr(route, "path", None) == "/api/super-agent-support"
            for route in app.routes
        )
        unchanged = await loader.registry.enrich_workspace_context(
            {"user_id": "user-1"},
            granted_capabilities={},
            invocation_id="invocation-2",
        )
        assert unchanged == {"user_id": "user-1"}
    finally:
        PluginRegistry._instance = previous


@pytest.mark.asyncio
async def test_failed_plugin_registration_rolls_back_generic_spi(tmp_path):
    previous = PluginRegistry._instance
    PluginRegistry._instance = None
    plugin_root = tmp_path / "failing-plugin"
    plugin_root.mkdir()
    (plugin_root / "plugin.json").write_text(
        json.dumps(
            {
                "id": "example.failing-plugin",
                "name": "Failing plugin",
                "version": "1.0.0",
                "entry": {"backend": "plugin.py"},
            },
        ),
        encoding="utf-8",
    )
    (plugin_root / "plugin.py").write_text(
        """
class FailingPlugin:
    def register(self, api):
        api.register_platform_capability('example.failure/1', '1', 'test')
        raise RuntimeError('registration failed')
plugin = FailingPlugin()
""".strip(),
        encoding="utf-8",
    )
    loader = PluginLoader([tmp_path])
    loader.registry.set_plugin_http_app(FastAPI())
    manifest = loader._load_manifest(plugin_root / "plugin.json")
    try:
        with pytest.raises(RuntimeError, match="registration failed"):
            await loader.load_plugin(manifest, plugin_root)
        assert (
            "example.failure/1"
            not in loader.registry.get_platform_capabilities()
        )
        assert loader.registry.get_plugin_manifest(manifest.id) is None
    finally:
        PluginRegistry._instance = previous


def _runtime(plugin_module, tmp_path):
    store = plugin_module.StateStore(tmp_path / "state.sqlite3")
    signer = plugin_module.SessionSigner(b"s" * 32)
    broker = plugin_module.CredentialBroker(store, b"s" * 32)
    service_cls = sys.modules[
        "test_dclaw_super_agent_support.service"
    ].LocalExecutionService
    return store, signer, broker, service_cls(store, signer, broker)


def test_store_migrates_legacy_waiting_task_status(plugin_module, tmp_path):
    path = tmp_path / "state.sqlite3"
    store = plugin_module.StateStore(path)
    task, _created = store.create_task(
        user_id="user-1",
        agent_id="agent-1",
        agent_name="Agent",
        invocation_id="invocation-1",
        capability_id="example.video.compose",
        task_input={},
        idempotency_key="legacy-task",
        device_id="device-1",
        max_concurrency=1,
    )
    store.update_task(task["task_id"], status="waiting_for_input")

    migrated = plugin_module.StateStore(path).get_task(
        task["task_id"],
        "user-1",
    )

    assert migrated is not None
    assert migrated["status"] == "awaiting_input"


def test_mcp_endpoint_exposes_exact_standard_tool_set(plugin_module, tmp_path):
    store, signer, broker, service = _runtime(plugin_module, tmp_path)
    del store, signer, broker
    mcp_cls = sys.modules[
        "test_dclaw_super_agent_support.mcp_server"
    ].LocalExecutionMcp
    endpoint = mcp_cls(service)
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
    }
    with TestClient(endpoint.app) as client:
        initialized = client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "contract-test", "version": "1"},
                },
            },
        )
        listed = client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        )
    assert initialized.status_code == 200
    assert listed.status_code == 200
    assert {item["name"] for item in listed.json()["result"]["tools"]} == {
        "local_environment_status",
        "local_capabilities_list",
        "local_runtime_prepare",
        "local_task_start",
        "local_task_continue",
        "local_task_status",
        "local_task_cancel",
        "local_task_result",
    }


def test_developer_kit_is_downloadable_without_server_source(
    plugin_module,
    tmp_path,
):
    store, _signer, broker, service = _runtime(plugin_module, tmp_path)
    mcp_cls = sys.modules[
        "test_dclaw_super_agent_support.mcp_server"
    ].LocalExecutionMcp
    package_cls = sys.modules[
        "test_dclaw_super_agent_support.packages"
    ].CapabilityPackageRegistry
    routes = sys.modules["test_dclaw_super_agent_support.routes"]
    plugin_app = routes.create_app(
        store=store,
        service=service,
        mcp=mcp_cls(service),
        packages=package_cls(
            store,
            PLUGIN_ROOT / "schemas" / "capability-descriptor.schema.json",
            {},
        ),
        credentials=broker,
    )

    with TestClient(plugin_app) as client:
        metadata = client.get("/developer-kit")
        downloaded = client.get("/developer-kit/v1.zip")

    assert metadata.status_code == 200
    assert metadata.json()["name"] == "dclaw-super-agent-devkit"
    assert metadata.json()["version"] == "1.2.0"
    assert metadata.json()["download_path"] == (
        "/api/super-agent-support/developer-kit/v1.zip"
    )
    assert metadata.json()["server_source_required"] is False
    assert metadata.json()["dependency_mode"] == "bundled-wheelhouse"
    assert metadata.json()["offline_bootstrap"] is True
    assert metadata.json()["supported_python"] == ">=3.10,<3.14"
    assert "windows-x86_64" in metadata.json()["supported_platforms"]
    assert len(metadata.json()["requirements_lock_sha256"]) == 64
    assert len(metadata.json()["wheelhouse_manifest_sha256"]) == 64
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/zip"
    assert (
        metadata.json()["sha256"]
        == hashlib.sha256(downloaded.content).hexdigest()
    )
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        names = set(archive.namelist())
    prefix = "dclaw-super-agent-devkit-1.2.0"
    assert f"{prefix}/dclaw_agent_devkit.py" in names
    assert f"{prefix}/bootstrap.ps1" in names
    assert f"{prefix}/bootstrap.sh" in names
    assert f"{prefix}/requirements.lock" in names
    assert f"{prefix}/CHECKSUMS.sha256" in names
    assert len([name for name in names if "/wheelhouse/" in name]) == 26
    assert all("qwenpaw" not in name for name in names)


def test_developer_pack_is_downloadable_and_self_describing(
    plugin_module,
    tmp_path,
):
    store, _signer, broker, service = _runtime(plugin_module, tmp_path)
    mcp_cls = sys.modules[
        "test_dclaw_super_agent_support.mcp_server"
    ].LocalExecutionMcp
    package_cls = sys.modules[
        "test_dclaw_super_agent_support.packages"
    ].CapabilityPackageRegistry
    routes = sys.modules["test_dclaw_super_agent_support.routes"]
    plugin_app = routes.create_app(
        store=store,
        service=service,
        mcp=mcp_cls(service),
        packages=package_cls(
            store,
            PLUGIN_ROOT / "schemas" / "capability-descriptor.schema.json",
            {},
        ),
        credentials=broker,
    )

    with TestClient(plugin_app) as client:
        metadata = client.get("/developer-pack")
        downloaded = client.get("/developer-pack/download")

    assert metadata.status_code == 200
    payload = metadata.json()
    assert payload["version"] == "1.0.0"
    assert payload["standard"]["version"] == "2.1"
    assert payload["devkit_version"] == "1.2.0"
    assert payload["server_source_required"] is False
    assert payload["download_path"].endswith("/developer-pack/download")
    assert payload["sha256"] == hashlib.sha256(downloaded.content).hexdigest()
    assert payload["content_sha256"] == payload["sha256"]
    assert downloaded.status_code == 200
    assert "dclaw-super-agent-developer-pack-1.0.0.zip" in (
        downloaded.headers["content-disposition"]
    )
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        names = set(archive.namelist())
    prefix = "dclaw-super-agent-developer-pack-1.0.0"
    assert f"{prefix}/PACKAGE-MANIFEST.json" in names
    assert f"{prefix}/SHA256SUMS" in names
    assert f"{prefix}/dclaw_developer.py" in names
    assert f"{prefix}/devkit/dclaw_agent_devkit.py" in names
    assert (
        f"{prefix}/standard/super-agent-development-standard-v1.zh-CN.md"
        in names
    )


def test_device_bootstrap_reuses_only_current_users_device(
    plugin_module,
    tmp_path,
):
    store, _signer, broker, service = _runtime(plugin_module, tmp_path)
    store.upsert_device(
        device_id="device-1",
        user_id="user-1",
        display_name="Windows",
        runner_version="1.0.0",
        protocol_version="1",
        device_token="device-token",
    )
    mcp_cls = sys.modules[
        "test_dclaw_super_agent_support.mcp_server"
    ].LocalExecutionMcp
    package_cls = sys.modules[
        "test_dclaw_super_agent_support.packages"
    ].CapabilityPackageRegistry
    routes = sys.modules["test_dclaw_super_agent_support.routes"]
    plugin_app = routes.create_app(
        store=store,
        service=service,
        mcp=mcp_cls(service),
        packages=package_cls(
            store,
            PLUGIN_ROOT / "schemas" / "capability-descriptor.schema.json",
            {},
        ),
        credentials=broker,
    )
    root = FastAPI()

    @root.middleware("http")
    async def authenticated(request, call_next):
        request.state.user_id = request.headers.get("x-test-user", "user-1")
        request.state.role = "user"
        return await call_next(request)

    root.mount("/api/super-agent-support", plugin_app)
    with TestClient(root) as client:
        environment = client.get(
            "/api/super-agent-support/environment-status",
        )
        reused = client.post(
            "/api/super-agent-support/device-bootstrap",
            json={"device_id": "device-1"},
        )
        other_user = client.post(
            "/api/super-agent-support/device-bootstrap",
            headers={"x-test-user": "user-2"},
            json={"device_id": "device-1"},
        )

    assert environment.status_code == 200
    assert environment.json()["state"] == "device_not_ready"
    assert environment.json()["reason"] == "device_offline"
    assert reused.status_code == 200
    assert reused.json() == {
        "paired": True,
        "device_id": "device-1",
        "pairing_code": None,
        "expires_in": 0,
        "websocket_path": "/api/super-agent-support/devices/connect",
    }
    assert other_user.status_code == 200
    assert other_user.json()["paired"] is False
    assert other_user.json()["device_id"] is None
    assert other_user.json()["pairing_code"]


class _FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)

    async def close(self, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_environment_catalog_and_runtime_prepare_contract(
    plugin_module,
    tmp_path,
):
    store, signer, _broker, service = _runtime(plugin_module, tmp_path)
    token = signer.issue(
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Video Agent",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-1",
    )
    environment = {
        "agent_protocol_version": "1",
        "bootstrap_session_id": "bootstrap-1",
        "wait_seconds": 0,
        "dclaw_session_token": token,
    }

    missing = await service.call("local_environment_status", environment)
    assert missing["data"] == {
        "state": "device_not_ready",
        "reason": "no_paired_device",
        "protocol_version": "1",
        "compatible": True,
        "minimum_runner_version": "1.0.0",
        "bootstrap_session_id": "bootstrap-1",
        "user_action": "open_dclaw",
        "devices": [],
    }

    store.upsert_device(
        device_id="device-1",
        user_id="user-1",
        display_name="Windows",
        runner_version="0.9.0",
        protocol_version="1",
        device_token="device-token",
    )
    websocket = _FakeWebSocket()
    await service.attach("device-1", websocket)
    outdated = await service.call("local_environment_status", environment)
    assert outdated["data"]["state"] == "runner_update_required"
    assert outdated["data"]["reason"] == "runner_version_too_old"
    assert outdated["data"]["user_action"] == "update_dclaw"

    store.upsert_device(
        device_id="device-1",
        user_id="user-1",
        display_name="Windows",
        runner_version="1.0.0",
        protocol_version="1",
        capabilities=[],
    )
    ready = await service.call("local_environment_status", environment)
    assert ready["data"]["state"] == "ready"
    assert ready["data"]["bootstrap_session_id"] == "bootstrap-1"
    assert ready["data"]["devices"][0]["online"] is True

    catalog = await service.call(
        "local_capabilities_list",
        {"dclaw_session_token": token},
    )
    assert catalog["data"] == {
        "catalog_version": "1",
        "availability": "available",
        "capabilities": [],
        "device_count": 1,
    }

    descriptor = {
        "capability_id": "example.video.compose",
        "package_id": "example.video.package",
        "package_version": "1.2.0",
        "min_runner_version": "1.0.0",
        "schemas": {
            name: {"document": {"type": "object"}}
            for name in ("input", "result", "checkpoint")
        },
        "limits": {"max_concurrency": 1},
    }
    store.register_package(descriptor, signer_id="test", signature="test")
    preparing = await service.call(
        "local_runtime_prepare",
        {
            "capability": "example.video.compose",
            "dclaw_session_token": token,
        },
    )
    assert preparing["data"] == {
        "capability_id": "example.video.compose",
        "package_id": "example.video.package",
        "package_version": "1.2.0",
        "min_runner_version": "1.0.0",
        "state": "preparing",
        "device_id": "device-1",
        "runner_version": "1.0.0",
        "user_action": "wait",
    }
    assert websocket.messages[-1]["type"] == "runtime.prepare"

    store.update_device_capabilities(
        "device-1",
        [
            {
                "capability_id": "example.video.compose",
                "version": "1",
                "package_id": "example.video.package",
                "package_version": "1.2.0",
            },
        ],
    )
    runtime_ready = await service.call(
        "local_runtime_prepare",
        {
            "capability": "example.video.compose",
            "dclaw_session_token": token,
        },
    )
    assert runtime_ready["data"]["state"] == "ready"
    assert runtime_ready["data"]["user_action"] == "none"


@pytest.mark.asyncio
async def test_environment_waits_for_automatic_client_connection(
    plugin_module,
    tmp_path,
):
    store, signer, _broker, service = _runtime(plugin_module, tmp_path)
    token = signer.issue(
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-1",
    )

    async def connect():
        await asyncio.sleep(0.01)
        store.upsert_device(
            device_id="device-1",
            user_id="user-1",
            display_name="Windows",
            runner_version="1.0.0",
            protocol_version="1",
            device_token="token",
        )
        await service.attach("device-1", _FakeWebSocket())

    connection = asyncio.create_task(connect())
    result = await service.call(
        "local_environment_status",
        {
            "agent_protocol_version": "1",
            "bootstrap_session_id": "wait-1",
            "wait_seconds": 1,
            "dclaw_session_token": token,
        },
    )
    await connection
    assert result["data"]["state"] == "ready"
    assert result["data"]["bootstrap_session_id"] == "wait-1"


@pytest.mark.asyncio
async def test_local_task_is_idempotent_and_completes_from_device_event(
    plugin_module,
    tmp_path,
):
    store, signer, _broker, service = _runtime(plugin_module, tmp_path)
    descriptor = {
        "capability_id": "example.video.compose",
        "package_id": "example.video.package",
        "package_version": "1.0.0",
        "limits": {"max_concurrency": 2},
        "schemas": {
            "input": {
                "document": {
                    "type": "object",
                    "required": ["title"],
                    "properties": {"title": {"type": "string"}},
                },
            },
            "result": {
                "document": {
                    "type": "object",
                    "required": ["artifacts"],
                    "properties": {"artifacts": {"type": "array"}},
                },
            },
            "checkpoint": {"document": {"type": "object"}},
        },
    }
    store.register_package(descriptor, signer_id="test", signature="test")
    store.upsert_device(
        device_id="device-1",
        user_id="user-1",
        display_name="Windows",
        runner_version="1.0.0",
        protocol_version="1",
        capabilities=[
            {
                "capability_id": "example.video.compose",
                "version": "1",
                "package_id": "example.video.package",
                "package_version": "1.0.0",
            },
        ],
    )
    websocket = _FakeWebSocket()
    await service.attach("device-1", websocket)
    token = signer.issue(
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Video Agent",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-1",
    )
    arguments = {
        "capability_id": "example.video.compose",
        "input": {"title": "hello"},
        "idempotency_key": "turn-1",
        "dclaw_session_token": token,
    }

    invalid = await service.call(
        "local_task_start",
        {
            **arguments,
            "input": {"title": 123},
            "idempotency_key": "invalid-turn",
        },
    )
    assert invalid["ok"] is False
    assert invalid["error"]["code"] == "CAPABILITY.INVALID_PAYLOAD"
    assert websocket.messages == []

    started = await service.call("local_task_start", arguments)
    replayed = await service.call("local_task_start", arguments)

    assert started["ok"] is True
    assert replayed["data"]["idempotent_replay"] is True
    assert (
        len(
            [
                item
                for item in websocket.messages
                if item["type"] == "task.start"
            ],
        )
        == 1
    )
    task_id = started["data"]["task_id"]
    await service.handle_device_message(
        "device-1",
        "user-1",
        {
            "type": "task.event",
            "task_id": task_id,
            "sequence": 1,
            "event_type": "started",
            "payload": {},
        },
    )
    await service.handle_device_message(
        "device-1",
        "user-1",
        {
            "type": "task.event",
            "task_id": task_id,
            "sequence": 2,
            "event_type": "completed",
            "payload": {
                "artifacts": [
                    {
                        "path": "result.mp4",
                        "sha256": "a" * 64,
                        "size_bytes": 12,
                    },
                ],
            },
        },
    )
    result = await service.call(
        "local_task_result",
        {"task_id": task_id, "dclaw_session_token": token},
    )
    assert result["data"]["status"] == "succeeded"
    assert result["data"]["result"]["artifacts"][0]["path"] == "result.mp4"

    second = await service.call(
        "local_task_start",
        {**arguments, "idempotency_key": "turn-2"},
    )
    await service.handle_device_message(
        "device-1",
        "user-1",
        {
            "type": "task.event",
            "task_id": second["data"]["task_id"],
            "sequence": 1,
            "event_type": "started",
            "payload": {},
        },
    )
    await service.handle_device_message(
        "device-1",
        "user-1",
        {
            "type": "task.event",
            "task_id": second["data"]["task_id"],
            "sequence": 2,
            "event_type": "completed",
            "payload": {},
        },
    )
    invalid_result = await service.call(
        "local_task_result",
        {
            "task_id": second["data"]["task_id"],
            "dclaw_session_token": token,
        },
    )
    assert invalid_result["data"]["status"] == "failed"
    assert invalid_result["data"]["error"]["code"] == (
        "CAPABILITY.INVALID_PAYLOAD"
    )

    third = await service.call(
        "local_task_start",
        {**arguments, "idempotency_key": "turn-3"},
    )
    third_id = third["data"]["task_id"]
    await service.handle_device_message(
        "device-1",
        "user-1",
        {
            "type": "task.event",
            "task_id": third_id,
            "sequence": 1,
            "event_type": "started",
            "payload": {},
        },
    )
    await service.handle_device_message(
        "device-1",
        "user-1",
        {
            "type": "task.event",
            "task_id": third_id,
            "sequence": 2,
            "event_type": "checkpoint",
            "payload": {"checkpoint_id": "checkpoint-1"},
        },
    )
    waiting = await service.call(
        "local_task_status",
        {"task_id": third_id, "dclaw_session_token": token},
    )
    assert waiting["data"]["status"] == "awaiting_input"
    continued = await service.call(
        "local_task_continue",
        {
            "task_id": third_id,
            "checkpoint_id": "checkpoint-1",
            "input": {"confirmed": True},
            "dclaw_session_token": token,
        },
    )
    assert continued["data"]["status"] == "running"
    assert websocket.messages[-1]["type"] == "task.continue"


def test_credential_broker_never_stores_plaintext(plugin_module, tmp_path):
    store, _signer, broker, _service = _runtime(plugin_module, tmp_path)
    reference = broker.bind(
        user_id="user-1",
        provider="vendor",
        secret={"token": "top-secret-token"},
        scopes=["media.resolve"],
        agent_ids=["agent-1"],
        installation_ids=["install-1"],
    )
    row = store.get_credential(reference)
    assert b"top-secret-token" not in row["ciphertext"]
    assert broker.resolve(
        reference,
        user_id="user-1",
        agent_id="agent-1",
        installation_id="install-1",
        required_scope="media.resolve",
    ) == {"token": "top-secret-token"}
    with pytest.raises(Exception, match="access denied"):
        broker.resolve(
            reference,
            user_id="user-1",
            agent_id="agent-2",
            installation_id="install-1",
            required_scope="media.resolve",
        )


def test_capability_descriptor_schema_and_signature(plugin_module, tmp_path):
    schema_path = PLUGIN_ROOT / "schemas" / "capability-descriptor.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    private_key = Ed25519PrivateKey.generate()
    public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    store = plugin_module.StateStore(tmp_path / "state.sqlite3")
    registry_cls = sys.modules[
        "test_dclaw_super_agent_support.packages"
    ].CapabilityPackageRegistry
    registry = registry_cls(
        store,
        schema_path,
        {"developer-1": base64.b64encode(public).decode()},
    )
    schema_file = {
        "path": "schemas/input.json",
        "sha256": "b" * 64,
        "document": {"type": "object"},
    }
    descriptor = {
        "descriptor_version": "1",
        "contract_version": "1",
        "capability_id": "example.video.compose",
        "package_id": "example.video.package",
        "package_version": "1.0.0",
        "implementation_status": "release",
        "min_runner_version": "1.0.0",
        "artifact": {
            "url": "https://packages.example.test/video.zip",
            "sha256": "a" * 64,
            "size_bytes": 1024,
        },
        "entrypoint": {"executable": "compose.exe", "arguments": []},
        "schemas": {
            "input": schema_file,
            "result": {**schema_file, "path": "schemas/result.json"},
            "checkpoint": {**schema_file, "path": "schemas/checkpoint.json"},
        },
        "operating_systems": ["windows-x64"],
        "permissions": {
            "workspace": "task-only",
            "network_domains": ["cdn.example.test"],
            "processes": ["ffmpeg"],
            "browser": False,
        },
        "limits": {
            "max_runtime_seconds": 3600,
            "max_memory_mib": 4096,
            "max_disk_mib": 10240,
            "max_concurrency": 1,
            "max_output_bytes": 2147483648,
        },
        "semantics": {
            "idempotency": "resume",
            "cancellation": "stop",
            "recovery": "checkpoint",
            "cleanup": "task root only",
        },
    }
    signature = base64.b64encode(
        private_key.sign(registry.canonical_payload(descriptor)),
    ).decode()
    registry.register(descriptor, signer_id="developer-1", signature=signature)
    assert (
        store.get_package_for_capability("example.video.compose")["descriptor"]
        == descriptor
    )

    candidate = dict(descriptor)
    candidate[
        "implementation_status"
    ] = "candidate_library_pending_platform_runner_adapter"
    with pytest.raises(Exception, match="invalid capability descriptor"):
        registry.register(
            candidate,
            signer_id="developer-1",
            signature=signature,
        )
