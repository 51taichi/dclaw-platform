# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import importlib.util
import io
import json
import sys
from pathlib import Path
import zipfile

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from jsonschema import Draft202012Validator
from starlette.testclient import TestClient

from qwenpaw.app.super_experts.capabilities import (
    get_platform_capability_catalog,
)
from qwenpaw.app import auth as app_auth
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
        assert (
            "business.service.installation-identity/1"
            in get_platform_capability_catalog()
        )
        assert "agent.outbound/1" in get_platform_capability_catalog()
        assert loader.registry.is_public_http_route(
            "GET",
            "/api/super-agent-support/business-identities/verification-keys",
        )
        assert any(
            getattr(route, "path", None) == "/api/super-agent-support"
            for route in app.routes
        )
        with TestClient(app) as client:
            frontend_response = client.get(
                "/api/super-expert-platform/cards",
                params={"conversation_id": "conversation-1"},
            )
            user_response = client.get(
                "/api/user/super-expert-platform/cards",
                params={"conversation_id": "conversation-1"},
            )
            assert frontend_response.json()["detail"] == "Chat not found"
            assert user_response.json()["detail"] == "Chat not found"
        assert (
            loader.registry.get_workspace_turn_handler(
                "workspace.turn.orchestrate/1",
            )
            is not None
        )
        assert loader.registry.get_aigc_event_consumer_factories()
        assert loader.registry.get_aigc_canvas_policies()
        assert (
            loader.registry.get_sealed_package_type("super_expert") is not None
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
        business_context = await loader.registry.enrich_workspace_context(
            {
                "tenant_id": "tenant-1",
                "user_id": "user-1",
                "session_id": "session-1",
                "agent_id": "agent-1",
                "agent_name": "Agent One",
                "installation_id": "install-1",
                "release_id": "release-1",
            },
            granted_capabilities={
                "business.service.installation-identity/1": "1",
            },
            invocation_id="invocation-2",
        )
        assert business_context["local_execution_session_token"]
        outbound_context = await loader.registry.enrich_workspace_context(
            {
                "tenant_id": "tenant-1",
                "user_id": "user-1",
                "session_id": "session-1",
                "agent_id": "agent-1",
                "agent_name": "Agent One",
                "installation_id": "install-1",
                "release_id": "release-1",
            },
            granted_capabilities={"agent.outbound/1": "1"},
            invocation_id="invocation-3",
        )
        assert outbound_context["local_execution_session_token"]

        await loader.unload_plugin(record.manifest.id)

        assert (
            "local.execution.session/1"
            not in get_platform_capability_catalog()
        )
        assert (
            "local.environment.preflight/1"
            not in get_platform_capability_catalog()
        )
        assert (
            "business.service.installation-identity/1"
            not in get_platform_capability_catalog()
        )
        assert "agent.outbound/1" not in get_platform_capability_catalog()
        assert not loader.registry.is_public_http_route(
            "GET",
            "/api/super-agent-support/business-identities/verification-keys",
        )
        assert not any(
            getattr(route, "path", None) == "/api/super-agent-support"
            for route in app.routes
        )
        with TestClient(app) as client:
            frontend_response = client.get(
                "/api/super-expert-platform/cards",
                params={"conversation_id": "conversation-1"},
            )
            user_response = client.get(
                "/api/user/super-expert-platform/cards",
                params={"conversation_id": "conversation-1"},
            )
            assert frontend_response.status_code == 404
            assert user_response.status_code == 404
            assert frontend_response.json()["detail"] == "Not Found"
            assert user_response.json()["detail"] == "Not Found"
        assert (
            loader.registry.get_workspace_turn_handler(
                "workspace.turn.orchestrate/1",
            )
            is None
        )
        assert not loader.registry.get_aigc_event_consumer_factories()
        assert not loader.registry.get_aigc_canvas_policies()
        assert loader.registry.get_sealed_package_type("super_expert") is None
        unchanged = await loader.registry.enrich_workspace_context(
            {"user_id": "user-1"},
            granted_capabilities={},
            invocation_id="invocation-2",
        )
        assert unchanged == {"user_id": "user-1"}
    finally:
        PluginRegistry._instance = previous


@pytest.mark.asyncio
async def test_mcp_lifecycle_can_stop_from_a_different_task(plugin_module):
    mcp = plugin_module.LocalExecutionMcp(service=object())

    await mcp.start()
    await asyncio.create_task(mcp.stop())

    assert mcp._runner_task is None
    assert mcp._stop_event is None


def test_generic_plugin_public_route_auth_and_unload(monkeypatch):
    previous = PluginRegistry._instance
    PluginRegistry._instance = None
    registry = PluginRegistry()
    app = FastAPI()

    @app.get("/api/example/public")
    async def public_endpoint():
        return {"status": "public"}

    @app.get("/api/example/private")
    async def private_endpoint():
        return {"status": "private"}

    registry.register_public_http_route(
        "example.plugin",
        method="GET",
        path="/api/example/public",
    )
    monkeypatch.setattr(app_auth, "is_auth_enabled", lambda: True)
    app.add_middleware(app_auth.AuthMiddleware)
    try:
        with TestClient(app) as client:
            assert client.get("/api/example/public").status_code == 200
            assert client.get("/api/example/private").status_code == 401
            registry.unregister_plugin("example.plugin")
            assert client.get("/api/example/public").status_code == 401
    finally:
        PluginRegistry._instance = previous


def test_core_uses_generic_spi_and_legacy_imports_resolve_to_plugin():
    core_router = (ROOT / "src/qwenpaw/app/routers/__init__.py").read_text(
        encoding="utf-8",
    )
    runner = (ROOT / "src/qwenpaw/app/runner/runner.py").read_text(
        encoding="utf-8",
    )
    assert "super_expert_platform" not in core_router
    assert "qwenpaw.app.super_experts" not in runner
    assert "..super_experts" not in runner

    import qwenpaw.app.routers.super_expert_platform as legacy_router
    import qwenpaw.app.local_execution.session as legacy_local_execution
    import qwenpaw.app.super_experts.capabilities as legacy_capabilities
    import qwenpaw.app.workspace.orchestration as legacy_orchestration

    for module in (
        legacy_router,
        legacy_local_execution,
        legacy_capabilities,
        legacy_orchestration,
    ):
        assert str(module.__file__).startswith(str(PLUGIN_ROOT))


def test_core_contains_only_thin_super_agent_compatibility_modules():
    core = ROOT / "src" / "qwenpaw"
    compatibility_files = {
        *(core / "app" / "super_experts").glob("*.py"),
        core / "app" / "routers" / "super_expert_platform.py",
        core / "app" / "integration_delivery" / "signer_provisioning.py",
        core / "app" / "local_execution" / "session.py",
        *(
            core / "app" / "workspace" / name
            for name in (
                "aigc_tools.py",
                "empty_reply.py",
                "flow_engine.py",
                "flow_runtime.py",
                "interaction_tools.py",
                "media_delivery.py",
                "media_review_context.py",
                "orchestration.py",
                "orchestration_contract.py",
                "public_stream.py",
            )
        ),
    }
    compatibility_files.discard(core / "app" / "super_experts" / "__init__.py")
    for path in compatibility_files:
        source = path.read_text(encoding="utf-8")
        assert "reexport_bundled_plugin_module" in source, path
        assert "\ndef " not in source, path
        assert "\nclass " not in source, path

    forbidden_dependencies = (
        "qwenpaw.app.super_experts",
        "from ..super_experts",
        "from ...app.super_experts",
        "qwenpaw.app.local_execution",
        "from ..local_execution",
        "workspace.aigc_tools",
        "workspace.empty_reply",
        "workspace.flow_engine",
        "workspace.flow_runtime",
        "workspace.interaction_tools",
        "workspace.media_delivery",
        "workspace.media_review_context",
        "workspace.orchestration",
        "workspace.public_stream",
    )
    for path in core.rglob("*.py"):
        if path in compatibility_files:
            continue
        source = path.read_text(encoding="utf-8")
        for dependency in forbidden_dependencies:
            assert dependency not in source, (path, dependency)


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


def test_session_capability_snapshot_preserves_legacy_tokens(plugin_module):
    secret = b"s" * 32
    signer = plugin_module.SessionSigner(secret)
    context = {
        "tenant_id": "tenant-1",
        "user_id": "user-1",
        "session_id": "session-1",
        "agent_id": "agent-1",
        "agent_name": "Agent",
        "installation_id": "install-1",
        "release_id": "release-1",
    }
    enriched = signer.enrich(
        context,
        granted_capabilities={
            "local.execution.session/1": "1",
            "interaction.file.select/1": "1",
        },
        invocation_id="invocation-1",
    )
    verified = signer.verify(enriched["local_execution_session_token"])
    assert verified["c"] == [
        "interaction.file.select/1",
        "local.execution.session/1",
    ]

    issued_at = 2_000_000_000
    legacy_payload = {
        "v": 1,
        "t": "tenant-1",
        "u": "user-1",
        "s": "session-1",
        "a": "agent-1",
        "n": "Agent",
        "g": "install-1",
        "r": "release-1",
        "i": "invocation-1",
        "iat": issued_at,
        "exp": issued_at + 600,
    }
    encoded = (
        base64.urlsafe_b64encode(
            json.dumps(
                legacy_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    signature = (
        base64.urlsafe_b64encode(
            hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest(),
        )
        .rstrip(b"=")
        .decode("ascii")
    )

    assert (
        signer.verify(
            f"{encoded}.{signature}",
            now=issued_at + 1,
        )["c"]
        == []
    )


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
        "local_file_select",
        "local_file_upload",
        "managed_artifacts_list",
        "managed_artifact_action",
    }


def test_mcp_endpoint_publishes_controlled_outbound_tools(
    plugin_module,
    tmp_path,
):
    store, signer, broker, service = _runtime(plugin_module, tmp_path)
    outbound_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        outbound_requests.append(request)
        return httpx.Response(200, json={"accepted": True})

    _identity_store, _identity_signer, identity, token = (
        _business_identity_runtime(
            plugin_module,
            tmp_path / "identity",
            transport=httpx.MockTransport(handler),
        )
    )
    mcp_cls = sys.modules[
        "test_dclaw_super_agent_support.mcp_server"
    ].LocalExecutionMcp
    outbound_cls = sys.modules[
        "test_dclaw_super_agent_support.agent_outbound"
    ].AgentOutboundManager
    endpoint = mcp_cls(
        service,
        identity,
        outbound_cls(broker, signer, transport=httpx.MockTransport(handler)),
    )
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
        ready = client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
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
        issued = client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "business_service_identity_issue",
                    "arguments": {
                        "service_id": "service-1",
                        "audience": BUSINESS_AUDIENCE,
                        "scopes": ["orders.read"],
                        "idempotency_key": "mcp-identity-issue-01",
                        "dclaw_session_token": token,
                    },
                },
            },
        )
        issue_result = issued.json()["result"]
        issue_payload = json.loads(issue_result["content"][0]["text"])
        outbound_response = client.post(
            "/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "business_service_outbound_request",
                    "arguments": {
                        "binding_ref": issue_payload["binding_ref"],
                        "method": "GET",
                        "url": f"{BUSINESS_AUDIENCE}/orders",
                        "dclaw_session_token": token,
                    },
                },
            },
        )
    del store, broker
    assert initialized.status_code == 200
    assert ready.status_code in {200, 202}
    assert listed.status_code == 200
    tools = {item["name"]: item for item in listed.json()["result"]["tools"]}
    assert {
        "business_service_identity_issue",
        "business_service_outbound_request",
        "agent_outbound_request",
    } <= set(tools)
    outbound_schema = tools["business_service_outbound_request"]["inputSchema"]
    assert set(outbound_schema["required"]) == {
        "binding_ref",
        "method",
        "url",
        "dclaw_session_token",
    }
    agent_schema = tools["agent_outbound_request"]["inputSchema"]
    assert set(agent_schema["required"]) == {
        "credential_scope",
        "method",
        "url",
        "dclaw_session_token",
    }
    assert {"credential_ref", "credential_slot"} <= set(
        agent_schema["properties"],
    )
    assert issued.status_code == 200
    assert issue_result["isError"] is False
    assert outbound_response.status_code == 200
    outbound_result = outbound_response.json()["result"]
    assert outbound_result["isError"] is False
    assert json.loads(outbound_result["content"][0]["text"])["status_code"] == 200
    assert len(outbound_requests) == 1
    assert outbound_requests[0].headers.get_list("authorization") == [
        outbound_requests[0].headers["authorization"],
    ]


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
    assert metadata.json()["version"] == "1.9.5"
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
    prefix = "dclaw-super-agent-devkit-1.9.5"
    assert f"{prefix}/dclaw_agent_devkit.py" in names
    assert f"{prefix}/bootstrap.ps1" in names
    assert f"{prefix}/bootstrap.sh" in names
    assert f"{prefix}/requirements.lock" in names
    assert f"{prefix}/CHECKSUMS.sha256" in names
    assert len([name for name in names if "/wheelhouse/" in name]) == 26
    assert all("qwenpaw" not in name for name in names)
    assert not any(
        "/._" in name
        or "/__MACOSX/" in name
        or name.endswith("/.DS_Store")
        for name in names
    )


def test_plugin_distributes_authenticated_versioned_local_helper(
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
    platform_helper_cls = sys.modules[
        "test_dclaw_super_agent_support.platform_helpers"
    ].PlatformHelperRegistry
    helper = b"MZ\x00plugin-owned-local-helper"
    plugin_root = tmp_path / "plugin"
    helper_root = plugin_root / "platform_helpers" / "windows-x64"
    helper_root.mkdir(parents=True)
    (helper_root / "DClaw.LocalHelper.exe").write_bytes(helper)
    helper_metadata = {
        "platform": "windows-x64",
        "version": "1.3.0",
        "protocol_version": "2",
        "executable": "DClaw.LocalHelper.exe",
    }
    metadata_root = plugin_root / "windows-helper"
    metadata_root.mkdir()
    (metadata_root / "helper.json").write_text(
        json.dumps(helper_metadata),
        encoding="utf-8",
    )
    manifest = {
        **helper_metadata,
        "size_bytes": len(helper),
        "sha256": hashlib.sha256(helper).hexdigest(),
    }
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
        platform_helpers=platform_helper_cls(plugin_root),
    )
    with TestClient(plugin_app) as client:
        assert client.get(
            "/local-helper/manifest?platform=windows-x64",
        ).status_code == 401

    root = FastAPI()

    @root.middleware("http")
    async def authenticated(request, call_next):
        request.state.user_id = "user-1"
        return await call_next(request)

    root.mount("/api/super-agent-support", plugin_app)
    with TestClient(root) as client:
        metadata = client.get(
            "/api/super-agent-support/local-helper/manifest",
            params={"platform": "windows-x64"},
        )
        downloaded = client.get(metadata.json()["download_path"])

    assert metadata.status_code == 200
    assert metadata.json() == {
        **manifest,
        "download_path": (
            "/api/super-agent-support/local-helper/download"
            "?platform=windows-x64"
        ),
    }
    assert downloaded.status_code == 200
    assert downloaded.content == helper
    assert downloaded.headers["x-dclaw-content-sha256"] == manifest["sha256"]
    assert downloaded.headers["x-content-type-options"] == "nosniff"


def test_developer_kit_archive_is_reproducible_and_filters_metadata(
    plugin_module,
    tmp_path,
):
    routes = sys.modules["test_dclaw_super_agent_support.routes"]
    (tmp_path / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    (tmp_path / "contract.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "._contract.json").write_bytes(b"apple-double")
    (tmp_path / ".DS_Store").write_bytes(b"finder")
    macos = tmp_path / "__MACOSX"
    macos.mkdir()
    (macos / "contract.json").write_bytes(b"metadata")

    first, version = routes._developer_kit_archive(tmp_path)
    second, repeated_version = routes._developer_kit_archive(tmp_path)
    assert first == second
    assert version == repeated_version == "9.9.9"
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        assert archive.namelist() == [
            "dclaw-super-agent-devkit-9.9.9/VERSION",
            "dclaw-super-agent-devkit-9.9.9/contract.json",
        ]


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
        health = client.get("/health")
        metadata = client.get("/developer-pack")
        downloaded = client.get("/developer-pack/download")

    assert health.status_code == 200
    assert health.json()["version"] == "1.18.19"
    assert metadata.status_code == 200
    payload = metadata.json()
    assert payload["version"] == "1.10.11"
    assert payload["standard"]["version"] == "2.35"
    assert payload["devkit_version"] == "1.9.5"
    assert payload["server_source_required"] is False
    assert payload["download_path"].endswith("/developer-pack/download")
    assert payload["sha256"] == hashlib.sha256(downloaded.content).hexdigest()
    assert payload["content_sha256"] == payload["sha256"]
    assert downloaded.status_code == 200
    assert "dclaw-super-agent-developer-pack-1.10.11.zip" in (
        downloaded.headers["content-disposition"]
    )
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        names = set(archive.namelist())
    prefix = "dclaw-super-agent-developer-pack-1.10.11"
    assert f"{prefix}/PACKAGE-MANIFEST.json" in names
    assert f"{prefix}/SHA256SUMS" in names
    assert f"{prefix}/dclaw_developer.py" in names
    assert f"{prefix}/devkit/dclaw_agent_devkit.py" in names
    assert (
        f"{prefix}/standard/super-agent-development-standard-v1.zh-CN.md"
        in names
    )


@pytest.mark.asyncio
async def test_component_artifact_upload_verification_and_descriptor_binding(
    plugin_module, tmp_path,
):
    store = plugin_module.StateStore(tmp_path / "state.sqlite3")
    manager_cls = sys.modules[
        "test_dclaw_super_agent_support.component_artifacts"
    ].ComponentArtifactManager

    class Storage:
        class config:
            signed_url_ttl_seconds = 900

        def build_object_key(self, path):
            return "prefix/" + path.strip("/")

        def object_url(self, key):
            return "https://objects.example.test/" + key

        def signed_put_url(self, key, mime_type):
            return self.object_url(key) + "?put=1"

        def signed_get_url(self, key, ttl_seconds):
            return self.object_url(key) + "?get=1"

    headers = {"content-range": "bytes 0-0/4", "etag": '"' + "a" * 32 + '"'}
    transport = httpx.MockTransport(
        lambda request: httpx.Response(206, headers=headers, content=b"x"),
    )
    manager = manager_cls(
        store, Storage(),
        http_client_factory=lambda: httpx.AsyncClient(transport=transport),
        public_base_url="https://cdn.example.test/assets",
    )
    upload = manager.create(
        component_id="ffmpeg", platform="windows-x64",
        component_version="7.1", size_bytes=4,
        sha256="b" * 64, md5="a" * 32, created_by="admin-1",
    )
    assert upload["artifact_url"].startswith("https://cdn.example.test/assets/")
    request_schema = json.loads((
        PLUGIN_ROOT / "devkit" / "schemas" / "super-agent-support-v1"
        / "component-artifact-upload-request.schema.json"
    ).read_text(encoding="utf-8"))
    response_schema = json.loads((
        PLUGIN_ROOT / "devkit" / "schemas" / "super-agent-support-v1"
        / "component-artifact-upload-response.schema.json"
    ).read_text(encoding="utf-8"))
    Draft202012Validator(response_schema).validate(upload)
    Draft202012Validator(request_schema).validate({
        "component_id": "ffmpeg", "platform": "windows-x64",
        "component_version": "7.1", "size_bytes": 4,
        "sha256": "b" * 64, "md5": "a" * 32,
    })
    descriptor = {
        "component_id": "ffmpeg", "platform": "windows-x64",
        "component_version": "7.1",
        "artifact": {
            "url": upload["artifact_url"], "sha256": "b" * 64,
            "size_bytes": 4,
        },
    }
    with pytest.raises(ValueError, match="not verified"):
        manager.require_verified_descriptor(descriptor)
    with pytest.raises(ValueError, match="not found"):
        await manager.complete(upload["upload_id"], actor="other-admin")
    receipt = await manager.complete(upload["upload_id"], actor="admin-1")
    completion_schema = json.loads((
        PLUGIN_ROOT / "devkit" / "schemas" / "super-agent-support-v1"
        / "component-artifact-completion-response.schema.json"
    ).read_text(encoding="utf-8"))
    Draft202012Validator(completion_schema).validate(receipt)
    assert receipt["status"] == "verified"
    assert manager.require_verified_descriptor(descriptor) == upload["upload_id"]
    with pytest.raises(ValueError, match="does not match"):
        manager.require_verified_descriptor({
            **descriptor, "artifact": {**descriptor["artifact"], "sha256": "c" * 64},
        })
    assert manager.create(
        component_id="ffmpeg", platform="windows-x64",
        component_version="7.1", size_bytes=4,
        sha256="b" * 64, md5="a" * 32, created_by="admin-1",
    )["upload"]["headers"]["Content-MD5"] == base64.b64encode(
        bytes.fromhex("a" * 32),
    ).decode("ascii")


@pytest.mark.parametrize("failure", ["wrong_size", "private_url"])
@pytest.mark.asyncio
async def test_component_artifact_upload_rejects_wrong_storage_receipt(
    plugin_module, tmp_path, failure,
):
    store = plugin_module.StateStore(tmp_path / "state.sqlite3")
    manager_cls = sys.modules[
        "test_dclaw_super_agent_support.component_artifacts"
    ].ComponentArtifactManager

    class Storage:
        class config:
            signed_url_ttl_seconds = 900

        def build_object_key(self, path):
            return path.strip("/")

        def object_url(self, key):
            return "https://objects.example.test/" + key

        def signed_put_url(self, key, mime_type):
            return self.object_url(key)

        def signed_get_url(self, key, ttl_seconds):
            return self.object_url(key) + "?signed=1"

    def storage_response(request):
        if failure == "private_url" and not request.url.query:
            return httpx.Response(403)
        return httpx.Response(
            206,
            headers={
                "content-range": "bytes 0-0/5" if failure == "wrong_size" else "bytes 0-0/4",
                "etag": '"' + "a" * 32 + '"',
            },
            content=b"x",
        )

    transport = httpx.MockTransport(storage_response)
    manager = manager_cls(
        store, Storage(),
        http_client_factory=lambda: httpx.AsyncClient(transport=transport),
    )
    upload = manager.create(
        component_id="ffmpeg", platform="windows-x64",
        component_version="7.1", size_bytes=4,
        sha256="b" * 64, md5="a" * 32, created_by="admin-1",
    )
    with pytest.raises(ValueError, match=(
        "size or MD5" if failure == "wrong_size" else "not range-readable"
    )):
        await manager.complete(upload["upload_id"], actor="admin-1")
    assert store.get_public_component_upload(upload["upload_id"])[
        "completed_at"
    ] is None


def test_public_component_registry_get_and_admin_set(
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
    component_cls = sys.modules[
        "test_dclaw_super_agent_support.public_components"
    ].PublicComponentRegistry
    component_key = ec.generate_private_key(ec.SECP256R1())
    component_public_key = base64.b64encode(
        component_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
    ).decode("ascii")
    component_registry = component_cls(
        store,
        PLUGIN_ROOT / "schemas" / "public-component-descriptor.schema.json",
        {"official-components": component_public_key},
    )
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
        public_components=component_registry,
    )
    with TestClient(plugin_app) as unauthenticated_client:
        unauthenticated = unauthenticated_client.get("/component-registry")
    assert unauthenticated.status_code == 401

    root = FastAPI()

    @root.middleware("http")
    async def authenticated(request, call_next):
        request.state.user_id = "user-1"
        request.state.role = request.headers.get("x-test-role", "user")
        return await call_next(request)

    root.mount("/api/super-agent-support", plugin_app)
    evidence = {
        "url": "https://components.example.test/evidence.json",
        "sha256": "b" * 64,
    }
    ffmpeg = {
        "descriptor_version": "1",
        "component_id": "ffmpeg",
        "display_name": "FFmpeg",
        "platform": "windows-x64",
        "component_version": "7.1.0",
        "status": "available",
        "provides": ["ffmpeg", "ffprobe"],
        "dependencies": [],
        "artifact": {
            "url": "https://components.example.test/ffmpeg.zip",
            "sha256": "a" * 64,
            "size_bytes": 1024,
            "unpacked_size_bytes": 4096,
            "archive_format": "zip",
        },
        "exports": {"ffmpeg": "bin/ffmpeg.exe", "ffprobe": "bin/ffprobe.exe"},
        "path_entries": ["bin"],
        "environment_paths": {},
        "sbom": evidence,
        "license": {
            "spdx": "GPL-3.0-or-later",
            "evidence_url": evidence["url"],
            "evidence_sha256": evidence["sha256"],
        },
        "cache_key": "ffmpeg/windows-x64/7.1.0",
        "rollback_version": "7.1.0",
        "notes": "Shared media processing tools.",
    }
    ffmpeg_mac = {
        **ffmpeg,
        "platform": "macos-arm64",
        "status": "reserved",
        "artifact": None,
        "sbom": None,
        "license": None,
    }
    python = {
        **ffmpeg,
        "component_id": "python-runtime",
        "display_name": "Python Runtime",
        "component_version": "3.11.9",
        "provides": ["python"],
        "artifact": {
            **ffmpeg["artifact"],
            "url": "https://components.example.test/python.zip",
        },
        "exports": {"python": "python.exe"},
        "path_entries": ["."],
        "environment_paths": {"PYTHONHOME": ["."], "PYTHONPATH": ["Lib"]},
        "cache_key": "python-runtime/windows-x64/3.11.9",
        "rollback_version": "3.11.9",
        "notes": "Shared Python runtime.",
    }

    def envelope(descriptor):
        signature = component_key.sign(
            component_registry.canonical_payload(descriptor),
            ec.ECDSA(hashes.SHA256()),
        )
        return {
            "descriptor": descriptor,
            "signer_id": "official-components",
            "signature": base64.b64encode(signature).decode("ascii"),
        }

    with TestClient(root) as client:
        empty = client.get("/api/super-agent-support/component-registry")
        forbidden = client.put(
            "/api/super-agent-support/admin/component-registry/ffmpeg/"
            "variants/windows-x64",
            json=envelope(ffmpeg),
        )
        first = client.put(
            "/api/super-agent-support/admin/component-registry/ffmpeg/"
            "variants/windows-x64",
            headers={"x-test-role": "admin"},
            json=envelope(ffmpeg),
        )
        second = client.put(
            "/api/super-agent-support/admin/component-registry/ffmpeg/"
            "variants/macos-arm64",
            headers={"x-test-role": "admin"},
            json=envelope(ffmpeg_mac),
        )
        third = client.put(
            "/api/super-agent-support/admin/component-registry/python-runtime/"
            "variants/windows-x64",
            headers={"x-test-role": "admin"},
            json=envelope(python),
        )
        complete = client.get(
            "/api/super-agent-support/component-registry",
        )

    assert empty.status_code == 200
    assert empty.json() == {
        "registry_version": 0,
        "updated_at": 0,
        "components": [],
        "helper_platforms": {
            "windows-x64": {
                "helper": "windows-helper",
                "status": "available",
            },
            "windows-arm64": {
                "helper": "windows-helper",
                "status": "reserved",
            },
            "macos-arm64": {
                "helper": "mac-helper",
                "status": "reserved",
            },
            "macos-x64": {
                "helper": "mac-helper",
                "status": "reserved",
            },
        },
    }
    assert forbidden.status_code == 403
    assert first.status_code == 200
    assert first.json()["registry_version"] == 1
    assert len(first.json()["components"]) == 1
    first_variant = first.json()["components"][0]["variants"][0]
    assert first_variant["platform"] == "windows-x64"
    assert first_variant["status"] == "available"
    assert first_variant["provides"] == [
        "ffmpeg",
        "ffprobe",
    ]
    assert second.status_code == 200
    assert second.json()["registry_version"] == 2
    assert [
        item["platform"]
        for item in second.json()["components"][0]["variants"]
    ] == ["macos-arm64", "windows-x64"]
    assert second.json()["components"][0]["variants"][0]["status"] == (
        "reserved"
    )
    assert third.status_code == 200
    assert third.json()["registry_version"] == 3
    assert [
        item["component_id"] for item in third.json()["components"]
    ] == ["ffmpeg", "python-runtime"]
    assert complete.json() == third.json()


def test_store_disables_legacy_unsigned_available_component(
    plugin_module,
    tmp_path,
):
    path = tmp_path / "state.sqlite3"
    store = plugin_module.StateStore(path)
    with store._connect() as database:
        database.execute(
            """
            INSERT INTO public_components(
                component_id,display_name,notes,updated_by,updated_at
            ) VALUES('legacy-ffmpeg','Legacy FFmpeg','','admin',1)
            """,
        )
        database.execute(
            """
            INSERT INTO public_component_variants(
                component_id,platform,component_version,availability,
                provides_json,descriptor_json,signer_id,signature,
                updated_by,updated_at
            ) VALUES(
                'legacy-ffmpeg','windows-x64','1.0.0','available',
                '["ffmpeg"]','{}','','','admin',1
            )
            """,
        )

    migrated = plugin_module.StateStore(path).get_public_component_registry()
    assert migrated["registry_version"] == 1
    variant = migrated["components"][0]["variants"][0]
    assert variant["status"] == "disabled"
    assert variant["signer_id"] == ""


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
        pairing_code = other_user.json()["pairing_code"]
        with client.websocket_connect(
            "/api/super-agent-support/devices/connect"
            f"?pairing_code={pairing_code}&runner_version=1.0.0",
        ) as socket:
            legacy_ready = socket.receive_json()

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
    assert legacy_ready["protocol_version"] == "1"
    assert (
        store.get_device_for_user(
            legacy_ready["device_id"],
            "user-2",
        )["protocol_version"]
        == "1"
    )


class _FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)

    async def close(self, **_kwargs):
        return None


@pytest.mark.asyncio
async def test_local_file_refs_are_opaque_scoped_and_bound_to_task_start(
    plugin_module,
    tmp_path,
):
    store, signer, _broker, service = _runtime(plugin_module, tmp_path)
    store.upsert_device(
        device_id="device-1",
        user_id="user-1",
        display_name="Windows",
        runner_version="1.1.0",
        protocol_version="2",
        capabilities=[],
    )
    websocket = _FakeWebSocket()
    await service.attach("device-1", websocket)
    unauthorized_token = signer.issue(
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="unauthorized-invocation",
    )
    unauthorized = await service.call(
        "local_file_select",
        {
            "interaction_id": "interaction-unauthorized",
            "selector": {},
            "dclaw_session_token": unauthorized_token,
        },
    )
    assert unauthorized["error"]["code"] == "FILE_SELECTOR.NOT_AUTHORIZED"
    assert websocket.messages == []
    token = signer.issue(
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-1",
        capability_ids=["interaction.file.select/1"],
    )

    selection = asyncio.create_task(
        service.call(
            "local_file_select",
            {
                "interaction_id": "interaction-1",
                "selector": {"accept_extensions": [".mp4"]},
                "dclaw_session_token": token,
            },
        ),
    )
    await asyncio.sleep(0)
    command = websocket.messages[-1]
    assert command["type"] == "file.select"
    assert "path" not in json.dumps(command)
    reference = "lfr_" + "a" * 32
    await service.handle_device_message(
        "device-1",
        "user-1",
        {
            "type": "file.select.result",
            "request_id": command["request_id"],
            "status": "selected",
            "files": [
                {
                    "local_file_ref": reference,
                    "display_name": "source.mp4",
                    "mime_type": "video/mp4",
                    "size_bytes": 12,
                    "device_id": "device-1",
                    "last_modified_ms": 1,
                },
            ],
        },
    )
    selected = await selection
    assert selected["ok"] is True
    assert selected["data"]["files"][0]["local_file_ref"] == reference
    assert "path" not in json.dumps(selected)

    descriptor = {
        "capability_id": "example.file.consume",
        "package_id": "example.file.package",
        "package_version": "1.0.0",
        "limits": {"max_concurrency": 2},
        "schemas": {
            "input": {"document": {"type": "object"}},
            "result": {"document": {"type": "object"}},
            "checkpoint": {"document": {"type": "object"}},
        },
    }
    store.register_package(descriptor, signer_id="test", signature="test")
    store.update_device_capabilities(
        "device-1",
        [
            {
                "capability_id": "example.file.consume",
                "version": "1",
                "package_id": "example.file.package",
                "package_version": "1.0.0",
            },
        ],
    )
    started = await service.call(
        "local_task_start",
        {
            "capability_id": "example.file.consume",
            "input": {},
            "local_file_bindings": {
                "source_video": {
                    "local_file_ref": reference,
                    "access": "read",
                },
            },
            "idempotency_key": "file-task-1",
            "dclaw_session_token": token,
        },
    )
    assert started["ok"] is True
    task_message = websocket.messages[-1]
    assert task_message["task"]["local_file_bindings"]["source_video"] == {
        "local_file_ref": reference,
        "access": "read",
    }
    assert "canonical_path" not in json.dumps(task_message)

    continuation_task = await service.call(
        "local_task_start",
        {
            "capability_id": "example.file.consume",
            "input": {},
            "idempotency_key": "file-task-continue",
            "dclaw_session_token": token,
        },
    )
    continuation_task_id = continuation_task["data"]["task_id"]
    await service.handle_device_message(
        "device-1",
        "user-1",
        {
            "type": "task.event",
            "task_id": continuation_task_id,
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
            "task_id": continuation_task_id,
            "sequence": 2,
            "event_type": "checkpoint",
            "payload": {"checkpoint_id": "wait-for-film"},
        },
    )
    unauthorized_continue = await service.call(
        "local_task_continue",
        {
            "task_id": continuation_task_id,
            "checkpoint_id": "wait-for-film",
            "input": {"confirmed": True},
            "local_file_bindings": {
                "finished_film": {
                    "local_file_ref": reference,
                    "access": "read",
                },
            },
            "dclaw_session_token": unauthorized_token,
        },
    )
    assert unauthorized_continue["error"]["code"] == (
        "FILE_SELECTOR.NOT_AUTHORIZED"
    )

    other_reference = "lfr_" + "b" * 32
    assert store.save_local_file_ref(
        {
            "local_file_ref": other_reference,
            "display_name": "other.mp4",
            "mime_type": "video/mp4",
            "size_bytes": 12,
            "last_modified_ms": 1,
        },
        scope={
            "user_id": "user-1",
            "session_id": "session-1",
            "agent_id": "agent-1",
            "installation_id": "install-1",
            "release_id": "release-1",
            "invocation_id": "invocation-1",
        },
        interaction_id="interaction-other-device",
        device_id="device-2",
        expires_at=9999999999,
    )
    wrong_device = await service.call(
        "local_task_continue",
        {
            "task_id": continuation_task_id,
            "checkpoint_id": "wait-for-film",
            "input": {"confirmed": True},
            "local_file_bindings": {
                "finished_film": {
                    "local_file_ref": other_reference,
                    "access": "read",
                },
            },
            "dclaw_session_token": token,
        },
    )
    assert wrong_device["error"]["code"] == "LOCAL_FILE_REF.WRONG_DEVICE"

    malformed_bindings = await service.call(
        "local_task_continue",
        {
            "task_id": continuation_task_id,
            "checkpoint_id": "wait-for-film",
            "input": {"confirmed": True},
            "local_file_bindings": [],
            "dclaw_session_token": token,
        },
    )
    assert malformed_bindings["error"]["code"] == (
        "LOCAL_GATEWAY.INVALID_ARGUMENTS"
    )

    continued = await service.call(
        "local_task_continue",
        {
            "task_id": continuation_task_id,
            "checkpoint_id": "wait-for-film",
            "input": {"confirmed": True},
            "local_file_bindings": {
                "finished_film": {
                    "local_file_ref": reference,
                    "access": "read",
                },
            },
            "dclaw_session_token": token,
        },
    )
    assert continued["ok"] is True
    continuation_message = websocket.messages[-1]
    assert continuation_message["type"] == "task.continue"
    assert continuation_message["protocol_version"] == "2"
    assert continuation_message["local_file_bindings"] == {
        "finished_film": {"local_file_ref": reference, "access": "read"},
    }
    assert continuation_message["scope"]["invocation_id"] == "invocation-1"
    assert "canonical_path" not in json.dumps(continuation_message)

    wrong_scope_token = signer.issue(
        user_id="user-1",
        session_id="session-2",
        agent_id="agent-1",
        agent_name="Agent",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-2",
        capability_ids=["interaction.file.select/1"],
    )
    rejected = await service.call(
        "local_task_start",
        {
            "capability_id": "example.file.consume",
            "input": {},
            "local_file_bindings": {
                "source_video": {
                    "local_file_ref": reference,
                    "access": "read",
                },
            },
            "idempotency_key": "file-task-2",
            "dclaw_session_token": wrong_scope_token,
        },
    )
    assert rejected["error"]["code"] == "LOCAL_FILE_REF.SCOPE_MISMATCH"

    assert store.revoke_local_file_ref(reference, "user-1") is True
    replayed = await service.call(
        "local_task_start",
        {
            "capability_id": "example.file.consume",
            "input": {},
            "local_file_bindings": {
                "source_video": {
                    "local_file_ref": reference,
                    "access": "read",
                },
            },
            "idempotency_key": "file-task-1",
            "dclaw_session_token": token,
        },
    )
    assert replayed["data"]["idempotent_replay"] is True


@pytest.mark.asyncio
async def test_presigned_upload_is_dispatched_to_device_without_file_bytes(
    plugin_module,
    tmp_path,
):
    store, signer, _broker, service = _runtime(plugin_module, tmp_path)
    store.upsert_device(
        device_id="device-1",
        user_id="user-1",
        display_name="Windows",
        runner_version="1.1.0",
        protocol_version="2",
        device_token="token",
    )
    websocket = _FakeWebSocket()
    await service.attach("device-1", websocket)
    token = signer.issue(
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-1",
        capability_ids=["interaction.file.select/1"],
    )
    reference = "lfr_" + "b" * 32
    store.save_local_file_ref(
        {
            "local_file_ref": reference,
            "display_name": "source.mp4",
            "mime_type": "video/mp4",
            "size_bytes": 12,
            "last_modified_ms": 1,
        },
        scope={
            "user_id": "user-1",
            "session_id": "session-1",
            "agent_id": "agent-1",
            "installation_id": "install-1",
            "release_id": "release-1",
            "invocation_id": "invocation-1",
        },
        interaction_id="interaction-1",
        device_id="device-1",
        expires_at=9999999999,
    )
    upload_base = "https://uploads.example.test"
    pending = asyncio.create_task(
        service.call(
            "local_file_upload",
            {
                "local_file_ref": reference,
                "upload": {
                    "url": f"{upload_base}/object?signature=secret",
                    "method": "PUT",
                    "allowed_domains": ["uploads.example.test"],
                    "max_size_bytes": 20,
                },
                "dclaw_session_token": token,
            },
        ),
    )
    await asyncio.sleep(0)
    command = websocket.messages[-1]
    assert command["type"] == "file.upload"
    serialized_command = json.dumps(command)
    assert "file_bytes" not in serialized_command
    assert "canonical_path" not in serialized_command
    assert '"path"' not in serialized_command
    await service.handle_device_message(
        "device-1",
        "user-1",
        {
            "type": "file.upload.result",
            "request_id": command["request_id"],
            "status": "uploaded",
            "size_bytes": 12,
        },
    )
    result = await pending
    assert result["data"] == {
        "status": "uploaded",
        "local_file_ref": reference,
        "size_bytes": 12,
    }


@pytest.mark.asyncio
async def test_file_bindings_require_protocol_two_but_legacy_tasks_still_run(
    plugin_module,
    tmp_path,
):
    store, signer, _broker, service = _runtime(plugin_module, tmp_path)
    descriptor = {
        "capability_id": "example.file.consume",
        "package_id": "example.file.package",
        "package_version": "1.0.0",
        "limits": {"max_concurrency": 2},
        "schemas": {
            name: {"document": {"type": "object"}}
            for name in ("input", "result", "checkpoint")
        },
    }
    store.register_package(descriptor, signer_id="test", signature="test")
    capability = [
        {
            "capability_id": "example.file.consume",
            "version": "1",
            "package_id": "example.file.package",
            "package_version": "1.0.0",
        },
    ]
    store.upsert_device(
        device_id="legacy-device",
        user_id="user-1",
        display_name="Legacy",
        runner_version="1.0.0",
        protocol_version="1",
        capabilities=capability,
    )
    websocket = _FakeWebSocket()
    await service.attach("legacy-device", websocket)
    token = signer.issue(
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-1",
        capability_ids=["interaction.file.select/1"],
    )

    legacy = await service.call(
        "local_task_start",
        {
            "capability_id": "example.file.consume",
            "input": {},
            "idempotency_key": "legacy-task",
            "dclaw_session_token": token,
        },
    )
    assert legacy["ok"] is True
    assert websocket.messages[-1]["protocol_version"] == "1"
    assert "local_file_bindings" not in websocket.messages[-1]["task"]
    assert "scope" not in websocket.messages[-1]["task"]

    legacy_task_id = legacy["data"]["task_id"]
    await service.handle_device_message(
        "legacy-device",
        "user-1",
        {
            "type": "task.event",
            "task_id": legacy_task_id,
            "sequence": 1,
            "event_type": "started",
            "payload": {},
        },
    )
    await service.handle_device_message(
        "legacy-device",
        "user-1",
        {
            "type": "task.event",
            "task_id": legacy_task_id,
            "sequence": 2,
            "event_type": "checkpoint",
            "payload": {"checkpoint_id": "legacy-checkpoint"},
        },
    )
    legacy_continued = await service.call(
        "local_task_continue",
        {
            "task_id": legacy_task_id,
            "checkpoint_id": "legacy-checkpoint",
            "input": {"confirmed": True},
            "dclaw_session_token": token,
        },
    )
    assert legacy_continued["ok"] is True
    legacy_command = websocket.messages[-1]
    assert legacy_command["type"] == "task.continue"
    assert legacy_command["protocol_version"] == "1"
    assert "local_file_bindings" not in legacy_command
    assert "scope" not in legacy_command

    reference = "lfr_" + "c" * 32
    assert store.save_local_file_ref(
        {
            "local_file_ref": reference,
            "display_name": "source.mp4",
            "mime_type": "video/mp4",
            "size_bytes": 12,
            "last_modified_ms": 1,
        },
        scope={
            "user_id": "user-1",
            "session_id": "session-1",
            "agent_id": "agent-1",
            "installation_id": "install-1",
            "release_id": "release-1",
            "invocation_id": "invocation-1",
        },
        interaction_id="interaction-1",
        device_id="legacy-device",
        expires_at=9999999999,
    )
    with_binding = await service.call(
        "local_task_start",
        {
            "capability_id": "example.file.consume",
            "input": {},
            "local_file_bindings": {
                "source": {
                    "local_file_ref": reference,
                    "access": "read",
                },
            },
            "idempotency_key": "file-task",
            "dclaw_session_token": token,
        },
    )
    assert with_binding["error"]["code"] == "LOCAL_GATEWAY.DEVICE_NOT_READY"


@pytest.mark.asyncio
async def test_file_selection_revalidates_device_metadata_against_limits(
    plugin_module,
    tmp_path,
):
    store, signer, _broker, service = _runtime(plugin_module, tmp_path)
    store.upsert_device(
        device_id="device-1",
        user_id="user-1",
        display_name="Windows",
        runner_version="1.1.0",
        protocol_version="2",
        device_token="token",
    )
    websocket = _FakeWebSocket()
    await service.attach("device-1", websocket)
    token = signer.issue(
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-1",
        capability_ids=["interaction.file.select/1"],
    )
    pending = asyncio.create_task(
        service.call(
            "local_file_select",
            {
                "interaction_id": "interaction-1",
                "selector": {
                    "accept_mime_types": ["video/mp4"],
                    "accept_extensions": [".mp4"],
                    "max_file_size_bytes": 10,
                    "max_total_size_bytes": 10,
                },
                "dclaw_session_token": token,
            },
        ),
    )
    await asyncio.sleep(0)
    command = websocket.messages[-1]
    await service.handle_device_message(
        "device-1",
        "user-1",
        {
            "type": "file.select.result",
            "request_id": command["request_id"],
            "status": "selected",
            "files": [
                {
                    "local_file_ref": "lfr_" + "d" * 32,
                    "display_name": "source.mp4",
                    "mime_type": "video/mp4",
                    "size_bytes": 11,
                    "device_id": "device-1",
                    "last_modified_ms": 1,
                },
            ],
        },
    )
    assert (await pending)["error"]["code"] == "FILE_SELECTOR.FILE_TOO_LARGE"


@pytest.mark.asyncio
async def test_device_request_response_must_come_from_expected_device(
    plugin_module,
    tmp_path,
):
    store, signer, _broker, service = _runtime(plugin_module, tmp_path)
    for device_id in ("device-1", "device-2"):
        store.upsert_device(
            device_id=device_id,
            user_id="user-1",
            display_name=device_id,
            runner_version="1.1.0",
            protocol_version="2",
            device_token="token",
        )
        await service.attach(device_id, _FakeWebSocket())
    token = signer.issue(
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-1",
        capability_ids=["interaction.file.select/1"],
    )
    pending = asyncio.create_task(
        service.call(
            "local_file_select",
            {
                "interaction_id": "interaction-1",
                "selector": {},
                "dclaw_session_token": token,
            },
        ),
    )
    await asyncio.sleep(0)
    expected_device_id = next(
        device_id
        for device_id, socket in service._connections.items()
        if socket.messages
    )
    other_device_id = (
        "device-2" if expected_device_id == "device-1" else "device-1"
    )
    command = service._connections[expected_device_id].messages[-1]
    cancelled = {
        "type": "file.select.result",
        "request_id": command["request_id"],
        "status": "cancelled",
        "files": [],
    }
    await service.handle_device_message(other_device_id, "user-1", cancelled)
    await asyncio.sleep(0)
    assert not pending.done()
    await service.handle_device_message(
        expected_device_id,
        "user-1",
        cancelled,
    )
    assert (await pending)["data"] == {"status": "cancelled", "files": []}


@pytest.mark.asyncio
async def test_managed_artifact_list_select_and_delete_are_user_scoped(
    plugin_module,
    tmp_path,
):
    store, signer, _broker, service = _runtime(plugin_module, tmp_path)
    store.upsert_device(
        device_id="device-1",
        user_id="user-1",
        display_name="Windows",
        runner_version="1.1.0",
        protocol_version="2",
        device_token="token",
    )
    websocket = _FakeWebSocket()
    await service.attach("device-1", websocket)
    token = signer.issue(
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-1",
        tenant_id="tenant-1",
        capability_ids=["interaction.file.select/1"],
    )
    unauthorized_token = signer.issue(
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="unauthorized",
        tenant_id="tenant-1",
    )
    unauthorized = await service.call(
        "managed_artifacts_list",
        {"dclaw_session_token": unauthorized_token},
    )
    assert unauthorized["error"]["code"] == "FILE_SELECTOR.NOT_AUTHORIZED"
    artifact_id = "artifact_" + "e" * 32

    listing = asyncio.create_task(
        service.call(
            "managed_artifacts_list",
            {"dclaw_session_token": token},
        ),
    )
    await asyncio.sleep(0)
    command = websocket.messages[-1]
    await service.handle_device_message(
        "device-1",
        "user-1",
        {
            "type": "managed_artifacts.result",
            "request_id": command["request_id"],
            "artifacts": [
                {
                    "artifact_id": artifact_id,
                    "task_id": "task-1",
                    "display_name": "result.mp4",
                    "mime_type": "video/mp4",
                    "size_bytes": 12,
                    "created_at": 1,
                },
            ],
        },
    )
    listed = await listing
    assert listed["data"]["artifacts"][0]["artifact_id"] == artifact_id
    assert "path" not in json.dumps(listed)

    selecting = asyncio.create_task(
        service.call(
            "managed_artifact_action",
            {
                "artifact_id": artifact_id,
                "action": "select",
                "dclaw_session_token": token,
            },
        ),
    )
    await asyncio.sleep(0)
    command = websocket.messages[-1]
    reference = "lfr_" + "f" * 32
    await service.handle_device_message(
        "device-1",
        "user-1",
        {
            "type": "managed_artifact.result",
            "request_id": command["request_id"],
            "status": "ok",
            "artifact_id": artifact_id,
            "action": "select",
            "file": {
                "local_file_ref": reference,
                "display_name": "result.mp4",
                "mime_type": "video/mp4",
                "size_bytes": 12,
                "device_id": "device-1",
                "last_modified_ms": 1,
            },
        },
    )
    selected = await selecting
    assert selected["data"]["file"]["local_file_ref"] == reference
    assert store.get_local_file_ref(reference)["tenant_id"] == "tenant-1"

    other_token = signer.issue(
        user_id="user-2",
        session_id="session-2",
        agent_id="agent-1",
        agent_name="Agent",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-2",
        tenant_id="tenant-1",
        capability_ids=["interaction.file.select/1"],
    )
    denied = await service.call(
        "managed_artifact_action",
        {
            "artifact_id": artifact_id,
            "action": "delete",
            "dclaw_session_token": other_token,
        },
    )
    assert denied["error"]["code"] == "LOCAL_GATEWAY.TASK_NOT_FOUND"

    deleting = asyncio.create_task(
        service.call(
            "managed_artifact_action",
            {
                "artifact_id": artifact_id,
                "action": "delete",
                "dclaw_session_token": token,
            },
        ),
    )
    await asyncio.sleep(0)
    command = websocket.messages[-1]
    await service.handle_device_message(
        "device-1",
        "user-1",
        {
            "type": "managed_artifact.result",
            "request_id": command["request_id"],
            "status": "ok",
            "artifact_id": artifact_id,
            "action": "delete",
        },
    )
    assert (await deleting)["data"]["status"] == "ok"
    assert (
        store.get_managed_artifact(
            artifact_id,
            "tenant-1",
            "user-1",
        )
        is None
    )


def test_public_and_devkit_contract_schemas_are_byte_identical():
    pairs = [
        (
            ROOT / "docs" / "contracts" / "local-execution" / "v1" / name,
            PLUGIN_ROOT / "devkit" / "schemas" / "local-execution-v1" / name,
        )
        for name in (
            "error-envelope.schema.json",
            "tool-call.schema.json",
            "tool-response.schema.json",
        )
    ] + [
        (
            PLUGIN_ROOT / "schemas" / name,
            PLUGIN_ROOT
            / "devkit"
            / "schemas"
            / "super-agent-support-v1"
            / name,
        )
        for name in (
            "capability-descriptor.schema.json",
            "device-command.schema.json",
            "device-message.schema.json",
            "public-component-descriptor.schema.json",
        )
    ]
    for public, bundled in pairs:
        assert public.read_bytes() == bundled.read_bytes()


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
    assert outdated["data"]["user_action"] == "update_local_helper"

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
    assert websocket.messages[-1]["public_components"] == []

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
async def test_runtime_prepare_resolves_signed_public_component_closure(
    plugin_module,
    tmp_path,
):
    store, signer, broker, _service = _runtime(plugin_module, tmp_path)
    component_cls = sys.modules[
        "test_dclaw_super_agent_support.public_components"
    ].PublicComponentRegistry
    service_cls = sys.modules[
        "test_dclaw_super_agent_support.service"
    ].LocalExecutionService
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
    ).decode("ascii")
    components = component_cls(
        store,
        PLUGIN_ROOT / "schemas" / "public-component-descriptor.schema.json",
        {"official-components": public_key},
    )
    service = service_cls(
        store,
        signer,
        broker,
        public_components=components,
    )

    def descriptor(component_id, version, dependencies):
        return {
            "descriptor_version": "1",
            "component_id": component_id,
            "display_name": component_id,
            "platform": "windows-x64",
            "component_version": version,
            "status": "available",
            "provides": [component_id.replace("-", ".")],
            "dependencies": dependencies,
            "artifact": {
                "url": f"https://components.example.test/{component_id}.zip",
                "sha256": "a" * 64,
                "size_bytes": 1024,
                "unpacked_size_bytes": 4096,
                "archive_format": "zip",
            },
            "exports": {},
            "path_entries": ["."],
            "environment_paths": {},
            "sbom": {
                "url": f"https://components.example.test/{component_id}.spdx.json",
                "sha256": "b" * 64,
            },
            "license": {
                "spdx": "MIT",
                "evidence_url": f"https://components.example.test/{component_id}.license.txt",
                "evidence_sha256": "c" * 64,
            },
            "cache_key": f"{component_id}/windows-x64/{version}",
            "rollback_version": version,
            "notes": "test component",
        }

    python = descriptor("python-runtime", "3.12.14", [])
    whisper = descriptor(
        "faster-whisper",
        "1.2.1",
        [{"component_id": "python-runtime", "version": "3.12.14"}],
    )
    for value in (python, whisper):
        signature = private_key.sign(
            components.canonical_payload(value),
            ec.ECDSA(hashes.SHA256()),
        )
        components.register(
            value,
            signer_id="official-components",
            signature=base64.b64encode(signature).decode("ascii"),
            updated_by="admin-1",
        )

    store.upsert_device(
        device_id="device-1",
        user_id="user-1",
        display_name="Windows",
        runner_version="1.2.0",
        protocol_version="2",
        platform="windows-x64",
        device_token="token",
    )
    websocket = _FakeWebSocket()
    await service.attach("device-1", websocket)
    package = {
        "capability_id": "example.video.compose",
        "package_id": "example.video.package",
        "package_version": "1.0.0",
        "min_runner_version": "1.2.0",
        "operating_systems": ["windows-x64"],
        "public_components": [
            {"component_id": "faster-whisper", "version": "1.2.1"},
        ],
        "schemas": {
            name: {"document": {"type": "object"}}
            for name in ("input", "result", "checkpoint")
        },
        "limits": {"max_concurrency": 1},
    }
    store.register_package(package, signer_id="test", signature="test")
    token = signer.issue(
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Video Agent",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-1",
    )

    prepared = await service.call(
        "local_runtime_prepare",
        {
            "capability": "example.video.compose",
            "dclaw_session_token": token,
        },
    )
    assert prepared["data"]["state"] == "preparing"
    envelopes = websocket.messages[-1]["public_components"]
    assert [
        item["descriptor"]["component_id"] for item in envelopes
    ] == ["python-runtime", "faster-whisper"]
    assert all(item["canonical_payload"] for item in envelopes)
    assert all(item["signer_public_key"] == public_key for item in envelopes)

    package["public_components"][0]["version"] = "1.2.2"
    store.register_package(package, signer_id="test", signature="test")
    unavailable = await service.call(
        "local_runtime_prepare",
        {
            "capability": "example.video.compose",
            "dclaw_session_token": token,
        },
    )
    assert unavailable["error"]["code"] == "PUBLIC_COMPONENT.UNAVAILABLE"


def test_public_component_registry_rejects_untrusted_signer(
    plugin_module,
    tmp_path,
):
    store, _signer, _broker, _service = _runtime(plugin_module, tmp_path)
    component_cls = sys.modules[
        "test_dclaw_super_agent_support.public_components"
    ].PublicComponentRegistry
    error_cls = sys.modules[
        "test_dclaw_super_agent_support.public_components"
    ].PublicComponentError
    components = component_cls(
        store,
        PLUGIN_ROOT / "schemas" / "public-component-descriptor.schema.json",
        {},
    )
    descriptor = {
        "descriptor_version": "1",
        "component_id": "example-runtime",
        "display_name": "Example Runtime",
        "platform": "macos-arm64",
        "component_version": "1.0.0",
        "status": "reserved",
        "provides": ["example.runtime"],
        "dependencies": [],
        "artifact": None,
        "exports": {},
        "path_entries": [],
        "environment_paths": {},
        "sbom": None,
        "license": None,
        "cache_key": "example-runtime/macos-arm64/1.0.0",
        "rollback_version": "1.0.0",
        "notes": "reserved",
    }
    with pytest.raises(error_cls, match="not trusted"):
        components.register(
            descriptor,
            signer_id="unknown",
            signature=base64.b64encode(b"invalid").decode("ascii"),
            updated_by="admin-1",
        )


def test_component_signer_trust_is_loaded_from_plugin_state(
    plugin_module,
    tmp_path,
):
    state_trust = {
        "state-signer": base64.b64encode(b"state-key").decode("ascii"),
    }
    (tmp_path / "trusted_component_signers.json").write_text(
        json.dumps(state_trust),
        encoding="utf-8",
    )

    loaded = plugin_module._trusted_component_signers(
        tmp_path,
        {"configured-signer": "configured-key"},
    )

    assert loaded == {
        **state_trust,
        "configured-signer": "configured-key",
    }


def test_component_signer_trust_rejects_invalid_state(
    plugin_module,
    tmp_path,
):
    (tmp_path / "trusted_component_signers.json").write_text(
        "[]",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="signer trust"):
        plugin_module._trusted_component_signers(tmp_path, None)


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
    assert "local_file_bindings" not in websocket.messages[-1]
    assert "scope" not in websocket.messages[-1]


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


@pytest.mark.asyncio
async def test_agent_outbound_injects_only_at_transport_and_redacts_echo(
    plugin_module,
    tmp_path,
):
    store, signer, broker, _service = _runtime(plugin_module, tmp_path)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"accepted": True, "echo": request.headers["x-api-key"]},
        )

    manager_cls = sys.modules[
        "test_dclaw_super_agent_support.agent_outbound"
    ].AgentOutboundManager
    manager = manager_cls(
        broker,
        signer,
        transport=httpx.MockTransport(handler),
    )
    reference = manager.bind_credential(
        user_id="user-1",
        provider="sync.so",
        authorization={
            "type": "header",
            "name": "x-api-key",
            "value": "sync-secret-value",
        },
        scopes=["sync.so.api"],
        agent_ids=["agent-1"],
        installation_ids=["install-1"],
        allowed_domains=["8.8.8.8"],
        allowed_methods=["GET", "POST"],
    )
    token = signer.issue(
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Digital Human",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-1",
        capability_ids=["agent.outbound/1"],
    )

    result = await manager.request(
        dclaw_session_token=token,
        credential_ref=reference,
        credential_scope="sync.so.api",
        method="POST",
        url="https://8.8.8.8/v2/generate",
        headers={"Accept": "application/json"},
        json_body={"model": "sync-3"},
    )

    assert len(requests) == 1
    assert requests[0].headers["x-api-key"] == "sync-secret-value"
    assert requests[0].headers.get("authorization") is None
    assert json.loads(requests[0].content) == {"model": "sync-3"}
    assert result["body_json"] == {
        "accepted": True,
        "echo": "[REDACTED]",
    }
    row = store.get_credential(reference)
    assert b"sync-secret-value" not in row["ciphertext"]
    assert "sync-secret-value" not in repr(result)


@pytest.mark.asyncio
async def test_agent_outbound_enforces_installation_scope_domain_and_method(
    plugin_module,
    tmp_path,
):
    _store, signer, broker, _service = _runtime(plugin_module, tmp_path)
    outbound_module = sys.modules[
        "test_dclaw_super_agent_support.agent_outbound"
    ]
    manager = outbound_module.AgentOutboundManager(
        broker,
        signer,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"ok": True}),
        ),
    )
    reference = manager.bind_credential(
        user_id="user-1",
        provider="sync.so",
        authorization={"type": "bearer", "value": "provider-token"},
        scopes=["sync.so.api"],
        agent_ids=["agent-1"],
        installation_ids=["install-1"],
        allowed_domains=["8.8.8.8"],
        allowed_methods=["POST"],
    )

    def token(*, agent_id="agent-1", installation_id="install-1"):
        return signer.issue(
            user_id="user-1",
            session_id="session-1",
            agent_id=agent_id,
            agent_name="Digital Human",
            installation_id=installation_id,
            release_id="release-1",
            invocation_id="invocation-1",
            capability_ids=["agent.outbound/1"],
        )

    with pytest.raises(outbound_module.AgentOutboundError) as wrong_agent:
        await manager.request(
            dclaw_session_token=token(agent_id="agent-2"),
            credential_ref=reference,
            credential_scope="sync.so.api",
            method="POST",
            url="https://8.8.8.8/v2/generate",
        )
    assert wrong_agent.value.code == "AGENT_OUTBOUND.CREDENTIAL_DENIED"

    with pytest.raises(outbound_module.AgentOutboundError) as wrong_method:
        await manager.request(
            dclaw_session_token=token(),
            credential_ref=reference,
            credential_scope="sync.so.api",
            method="GET",
            url="https://8.8.8.8/v2/generate",
        )
    assert wrong_method.value.code == "AGENT_OUTBOUND.POLICY_DENIED"

    with pytest.raises(outbound_module.AgentOutboundError) as private_target:
        await manager.request(
            dclaw_session_token=token(),
            credential_ref=reference,
            credential_scope="sync.so.api",
            method="POST",
            url="https://127.0.0.1/v2/generate",
        )
    assert private_target.value.code == "AGENT_OUTBOUND.URL_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_agent_outbound_rejects_redirects_and_missing_capability(
    plugin_module,
    tmp_path,
):
    _store, signer, broker, _service = _runtime(plugin_module, tmp_path)
    outbound_module = sys.modules[
        "test_dclaw_super_agent_support.agent_outbound"
    ]
    manager = outbound_module.AgentOutboundManager(
        broker,
        signer,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                302,
                headers={"location": "https://8.8.4.4/redirected"},
            ),
        ),
    )
    reference = manager.bind_credential(
        user_id="user-1",
        provider="sync.so",
        authorization={"type": "header", "name": "x-api-key", "value": "secret"},
        scopes=["sync.so.api"],
        agent_ids=["agent-1"],
        installation_ids=["install-1"],
        allowed_domains=["8.8.8.8"],
        allowed_methods=["POST"],
    )
    token_kwargs = {
        "user_id": "user-1",
        "session_id": "session-1",
        "agent_id": "agent-1",
        "agent_name": "Digital Human",
        "installation_id": "install-1",
        "release_id": "release-1",
        "invocation_id": "invocation-1",
    }
    without_grant = signer.issue(**token_kwargs, capability_ids=[])
    with pytest.raises(outbound_module.AgentOutboundError) as not_granted:
        await manager.request(
            dclaw_session_token=without_grant,
            credential_ref=reference,
            credential_scope="sync.so.api",
            method="POST",
            url="https://8.8.8.8/v2/generate",
        )
    assert not_granted.value.code == "AGENT_OUTBOUND.NOT_GRANTED"

    granted = signer.issue(
        **token_kwargs,
        capability_ids=["agent.outbound/1"],
    )
    with pytest.raises(outbound_module.AgentOutboundError) as redirected:
        await manager.request(
            dclaw_session_token=granted,
            credential_ref=reference,
            credential_scope="sync.so.api",
            method="POST",
            url="https://8.8.8.8/v2/generate",
        )
    assert redirected.value.code == "AGENT_OUTBOUND.REDIRECT_REJECTED"


@pytest.mark.asyncio
async def test_agent_outbound_credential_slot_is_release_and_installation_scoped(
    plugin_module,
    tmp_path,
):
    _store, signer, broker, _service = _runtime(plugin_module, tmp_path)
    outbound_module = sys.modules[
        "test_dclaw_super_agent_support.agent_outbound"
    ]
    manager = outbound_module.AgentOutboundManager(
        broker,
        signer,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"ok": True}),
        ),
    )
    manager.bind_credential(
        tenant_id="tenant-1",
        user_id="user-1",
        provider="sync.so",
        authorization={"type": "header", "name": "x-api-key", "value": "secret"},
        scopes=["sync.so.api"],
        agent_ids=["agent-1"],
        installation_ids=["install-1"],
        release_ids=["release-1"],
        credential_slot="sync.primary",
        allowed_domains=["8.8.8.8"],
        allowed_methods=["POST"],
    )

    def token(release_id):
        return signer.issue(
            tenant_id="tenant-1",
            user_id="user-1",
            session_id="session-1",
            agent_id="agent-1",
            agent_name="Agent",
            installation_id="install-1",
            release_id=release_id,
            invocation_id="invocation-1",
            capability_ids=["agent.outbound/1"],
        )

    result = await manager.request(
        dclaw_session_token=token("release-1"),
        credential_slot="sync.primary",
        credential_scope="sync.so.api",
        method="POST",
        url="https://8.8.8.8/v2/generate",
    )
    assert result["body_json"] == {"ok": True}
    with pytest.raises(outbound_module.AgentOutboundError) as denied:
        await manager.request(
            dclaw_session_token=token("release-2"),
            credential_slot="sync.primary",
            credential_scope="sync.so.api",
            method="POST",
            url="https://8.8.8.8/v2/generate",
        )
    assert denied.value.code == "AGENT_OUTBOUND.CREDENTIAL_DENIED"


class _TemporaryStorage:
    def __init__(self):
        self.uploads = []

    def build_object_key(self, relative_path):
        return "root/" + relative_path

    def signed_put_url(self, object_key, _mime_type):
        return "https://8.8.8.8/" + object_key + "?put=1"

    def signed_get_url(self, object_key, ttl_seconds=None):
        return "https://8.8.8.8/" + object_key + f"?ttl={ttl_seconds}"

    async def upload(self, *, relative_path, content, mime_type):
        self.uploads.append((relative_path, content, mime_type))
        return {"object_key": self.build_object_key(relative_path)}


def test_temporary_resource_exchange_is_invocation_scoped(plugin_module, tmp_path):
    store, signer, _broker, _service = _runtime(plugin_module, tmp_path)
    resource_module = sys.modules[
        "test_dclaw_super_agent_support.temporary_resources"
    ]
    resources = resource_module.TemporaryResourceBroker(
        store,
        signer,
        _TemporaryStorage(),
    )

    def token(invocation_id):
        return signer.issue(
            tenant_id="tenant-1",
            user_id="user-1",
            session_id="session-1",
            agent_id="agent-1",
            agent_name="Agent",
            installation_id="install-1",
            release_id="release-1",
            invocation_id=invocation_id,
            capability_ids=["resource.exchange/1"],
        )

    created = resources.create_upload(
        dclaw_session_token=token("invocation-1"),
        mime_type="image/png",
        max_size_bytes=1024,
        purpose="ark.review.frame",
    )
    assert created["upload"]["allowed_domains"] == ["8.8.8.8"]
    ready = resources.complete_upload(
        dclaw_session_token=token("invocation-1"),
        resource_ref=created["resource_ref"],
        size_bytes=8,
        sha256="a" * 64,
    )
    assert ready["status"] == "ready"
    read = resources.read(
        dclaw_session_token=token("invocation-1"),
        resource_ref=created["resource_ref"],
    )
    assert read["status"] == "ready"
    assert read["read_url"].startswith("https://8.8.8.8/")
    revoked = resources.revoke(
        dclaw_session_token=token("invocation-1"),
        resource_ref=created["resource_ref"],
    )
    assert revoked["status"] == "revoked"
    with pytest.raises(resource_module.TemporaryResourceError) as revoked_read:
        resources.read(
            dclaw_session_token=token("invocation-1"),
            resource_ref=created["resource_ref"],
        )
    assert revoked_read.value.code == "RESOURCE_EXCHANGE.REVOKED"
    with pytest.raises(resource_module.TemporaryResourceError) as denied:
        resources.read(
            dclaw_session_token=token("invocation-2"),
            resource_ref=created["resource_ref"],
        )
    assert denied.value.code == "RESOURCE_EXCHANGE.NOT_FOUND"


@pytest.mark.asyncio
async def test_agent_outbound_websocket_stream_returns_resource_not_bytes(
    plugin_module,
    tmp_path,
):
    store, signer, broker, _service = _runtime(plugin_module, tmp_path)
    resource_module = sys.modules[
        "test_dclaw_super_agent_support.temporary_resources"
    ]
    stream_module = sys.modules[
        "test_dclaw_super_agent_support.agent_outbound_stream"
    ]
    storage = _TemporaryStorage()
    resources = resource_module.TemporaryResourceBroker(store, signer, storage)

    class FakeSocket:
        def __init__(self):
            self.messages = iter(
                [
                    b"X-Test: 1\r\nPath:audio\r\n\r\nMP3-DATA",
                    "Path:turn.end",
                ],
            )
            self.sent = []

        async def send(self, value):
            self.sent.append(value)

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.messages)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class FakeConnect:
        def __init__(self, *_args, **_kwargs):
            self.socket = FakeSocket()

        async def __aenter__(self):
            return self.socket

        async def __aexit__(self, *_args):
            return None

    manager = stream_module.AgentOutboundStreamManager(
        broker,
        signer,
        resources,
        websocket_connect=FakeConnect,
    )
    manager_ref = sys.modules[
        "test_dclaw_super_agent_support.agent_outbound"
    ].AgentOutboundManager(broker, signer)
    manager_ref.bind_credential(
        tenant_id="tenant-1",
        user_id="user-1",
        provider="edge-tts",
        authorization={"type": "none"},
        scopes=["edge.tts"],
        agent_ids=["agent-1"],
        installation_ids=["install-1"],
        release_ids=["release-1"],
        credential_slot="edge.primary",
        allowed_domains=["8.8.8.8"],
        allowed_methods=["GET"],
    )
    token = signer.issue(
        tenant_id="tenant-1",
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-1",
        capability_ids=["agent.outbound.stream/1"],
    )
    result = await manager.request(
        dclaw_session_token=token,
        protocol="wss",
        url="wss://8.8.8.8/tts",
        credential_scope="edge.tts",
        credential_slot="edge.primary",
        output_mime_type="audio/mpeg",
        purpose="tts.edge.audio",
        send_frames=[{"kind": "text", "data": "synthesis request"}],
        completion_text="Path:turn.end",
        binary_filter_contains="Path:audio",
        binary_strip_through="\r\n\r\n",
    )
    assert result["resource_ref"].startswith("res_")
    assert "body" not in result
    assert storage.uploads[0][1] == b"MP3-DATA"


@pytest.mark.asyncio
async def test_agent_outbound_https_stream_rejects_empty_output(
    plugin_module,
    tmp_path,
):
    store, signer, broker, _service = _runtime(plugin_module, tmp_path)
    resource_module = sys.modules[
        "test_dclaw_super_agent_support.temporary_resources"
    ]
    stream_module = sys.modules[
        "test_dclaw_super_agent_support.agent_outbound_stream"
    ]
    storage = _TemporaryStorage()
    resources = resource_module.TemporaryResourceBroker(store, signer, storage)
    manager = stream_module.AgentOutboundStreamManager(
        broker,
        signer,
        resources,
        http_transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b""),
        ),
    )
    outbound_cls = sys.modules[
        "test_dclaw_super_agent_support.agent_outbound"
    ].AgentOutboundManager
    credential_ref = outbound_cls(broker, signer).bind_credential(
        tenant_id="tenant-1",
        user_id="user-1",
        provider="fixture",
        authorization={"type": "none"},
        scopes=["media.read"],
        agent_ids=["agent-1"],
        installation_ids=["install-1"],
        allowed_domains=["8.8.8.8"],
        allowed_methods=["GET"],
    )
    token = signer.issue(
        tenant_id="tenant-1",
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-1",
        capability_ids=["agent.outbound.stream/1"],
    )

    with pytest.raises(stream_module.AgentOutboundStreamError) as exc_info:
        await manager.request(
            dclaw_session_token=token,
            protocol="https",
            url="https://8.8.8.8/empty",
            credential_scope="media.read",
            output_mime_type="audio/mpeg",
            purpose="empty.test",
            credential_ref=credential_ref,
        )

    assert exc_info.value.code == "AGENT_OUTBOUND_STREAM.EMPTY_OUTPUT"
    assert storage.uploads == []


@pytest.mark.asyncio
async def test_agent_outbound_https_stream_extracts_json_base64_to_resource(
    plugin_module,
    tmp_path,
):
    store, signer, broker, _service = _runtime(plugin_module, tmp_path)
    resource_module = sys.modules[
        "test_dclaw_super_agent_support.temporary_resources"
    ]
    stream_module = sys.modules[
        "test_dclaw_super_agent_support.agent_outbound_stream"
    ]
    storage = _TemporaryStorage()
    resources = resource_module.TemporaryResourceBroker(store, signer, storage)
    payload = base64.b64encode(b"MP3-DATA").decode("ascii")
    manager = stream_module.AgentOutboundStreamManager(
        broker,
        signer,
        resources,
        http_transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"Content-Type": "application/json; charset=utf-8"},
                json={"result": {"audio": payload}},
            ),
        ),
    )
    outbound_cls = sys.modules[
        "test_dclaw_super_agent_support.agent_outbound"
    ].AgentOutboundManager
    outbound_cls(broker, signer).bind_credential(
        tenant_id="tenant-1",
        user_id="user-1",
        provider="fixture",
        authorization={"type": "none"},
        scopes=["tts.create"],
        agent_ids=["agent-1"],
        installation_ids=["install-1"],
        release_ids=["release-1"],
        credential_slot="tts.primary",
        allowed_domains=["8.8.8.8"],
        allowed_methods=["POST"],
    )
    token = signer.issue(
        tenant_id="tenant-1",
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-1",
        capability_ids=["agent.outbound.stream/1"],
    )

    result = await manager.request(
        dclaw_session_token=token,
        protocol="https",
        method="POST",
        url="https://8.8.8.8/tts",
        credential_scope="tts.create",
        credential_slot="tts.primary",
        output_mime_type="audio/mpeg",
        purpose="tts.audio",
        json_body={"text": "hello"},
        response_transform={
            "type": "json_base64",
            "json_pointer": "/result/audio",
        },
    )

    assert result["status"] == "ready"
    assert "body" not in result
    assert storage.uploads[0][1] == b"MP3-DATA"


@pytest.mark.parametrize(
    ("content_type", "payload", "transform", "reason"),
    [
        (
            "text/plain",
            b"{}",
            {"type": "json_base64", "json_pointer": "/audio"},
            "TRANSFORM_FAILED",
        ),
        (
            "application/json",
            b"{}",
            {"type": "json_base64", "json_pointer": "/audio"},
            "TRANSFORM_FAILED",
        ),
        (
            "application/json",
            b'{"audio":"***"}',
            {"type": "json_base64", "json_pointer": "/audio"},
            "TRANSFORM_FAILED",
        ),
        (
            "application/json",
            b'{"audio":"QQ=="}',
            {"type": "json_base64", "json_pointer": "/bad~2pointer"},
            "TRANSFORM_FAILED",
        ),
        (
            "application/json",
            b'{"audio":"QQ=="}',
            {"type": "json_base64", "json_pointer": "/audio", "extra": True},
            "INVALID_REQUEST",
        ),
    ],
)
def test_agent_outbound_https_transform_fails_closed(
    plugin_module,
    content_type,
    payload,
    transform,
    reason,
):
    stream_module = sys.modules[
        "test_dclaw_super_agent_support.agent_outbound_stream"
    ]
    with pytest.raises(stream_module.AgentOutboundStreamError) as exc_info:
        stream_module._transform_https_response(
            payload,
            content_type,
            transform,
            1024,
        )
    assert exc_info.value.reason == reason


def test_agent_outbound_https_transform_enforces_decoded_size(plugin_module):
    stream_module = sys.modules[
        "test_dclaw_super_agent_support.agent_outbound_stream"
    ]
    with pytest.raises(stream_module.AgentOutboundStreamError) as exc_info:
        stream_module._transform_https_response(
            b'{"audio":"QUI="}',
            "application/json",
            {"type": "json_base64", "json_pointer": "/audio"},
            1,
        )
    assert exc_info.value.reason == "OUTPUT_TOO_LARGE"


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


BUSINESS_IDENTITY_CAPABILITY = "business.service.installation-identity/1"
BUSINESS_ISSUER = "https://8.8.8.8/business-identity"
BUSINESS_AUDIENCE = "https://8.8.8.8/business/v1"
BUSINESS_VERIFY = {
    "audience": BUSINESS_AUDIENCE,
    "installation_id": "install-1",
    "release_id": "release-1",
    "agent_id": "agent-1",
    "service_id": "service-1",
    "required_scopes": ["orders.read"],
}


def _business_identity_runtime(plugin_module, tmp_path, *, transport=None):
    store = plugin_module.StateStore(tmp_path / "business-identity.sqlite3")
    signer = plugin_module.SessionSigner(b"i" * 32)
    manager_cls = sys.modules[
        "test_dclaw_super_agent_support.business_identity"
    ].BusinessIdentityManager
    manager = manager_cls(
        store,
        b"i" * 32,
        signer,
        issuer=BUSINESS_ISSUER,
        transport=transport,
    )
    manager.register_service(
        actor_id="admin-1",
        developer_id="developer-1",
        service_id="service-1",
        audience=BUSINESS_AUDIENCE,
        allowed_domains=["8.8.8.8"],
        allowed_scopes=["orders.read", "orders.write"],
    )
    manager.grant_installation(
        actor_id="admin-1",
        tenant_id="tenant-1",
        user_id="user-1",
        agent_id="agent-1",
        release_id="release-1",
        installation_id="install-1",
        service_id="service-1",
        audience=BUSINESS_AUDIENCE,
        scopes=["orders.read"],
    )
    token = signer.issue(
        tenant_id="tenant-1",
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent One",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-1",
        capability_ids=[BUSINESS_IDENTITY_CAPABILITY],
    )
    return store, signer, manager, token


@pytest.mark.asyncio
async def test_business_identity_issue_inject_verify_and_replay(
    plugin_module,
    tmp_path,
):
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["authorization"]
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"accepted": True},
        )

    store, _signer, manager, token = _business_identity_runtime(
        plugin_module,
        tmp_path,
        transport=httpx.MockTransport(handler),
    )
    issued = manager.issue(
        dclaw_session_token=token,
        service_id="service-1",
        audience=BUSINESS_AUDIENCE,
        scopes=["orders.read"],
        idempotency_key="request-00000001",
    )
    assert set(issued) == {
        "binding_ref",
        "service_id",
        "audience",
        "scopes",
        "issued_at",
        "expires_at",
        "issuer",
        "key_id",
        "audit_id",
    }
    assert "token" not in json.dumps(issued).lower()
    response = await manager.outbound_request(
        dclaw_session_token=token,
        binding_ref=issued["binding_ref"],
        method="POST",
        url=f"{BUSINESS_AUDIENCE}/orders",
        json_body={"order_id": "order-1"},
    )
    assert response == {
        "status_code": 200,
        "content_type": "application/json",
        "body_text": '{"accepted":true}',
    }
    assertion = captured["authorization"].removeprefix("Bearer ")
    with pytest.raises(
        Exception,
        match="BUSINESS_IDENTITY.ASSERTION_SCOPE_MISMATCH",
    ):
        manager.verify_assertion(
            assertion,
            **{**BUSINESS_VERIFY, "installation_id": "install-2"},
        )
    claims = manager.verify_assertion(assertion, **BUSINESS_VERIFY)
    assert claims["installation_id"] == "install-1"
    assert claims["release_id"] == "release-1"
    assert claims["aud"] == BUSINESS_AUDIENCE
    assert claims["scopes"] == ["orders.read"]
    with pytest.raises(Exception, match="BUSINESS_IDENTITY.ASSERTION_REPLAYED"):
        manager.verify_assertion(assertion, **BUSINESS_VERIFY)
    with pytest.raises(Exception, match="BUSINESS_IDENTITY.BINDING_REPLAYED"):
        await manager.outbound_request(
            dclaw_session_token=token,
            binding_ref=issued["binding_ref"],
            method="GET",
            url=f"{BUSINESS_AUDIENCE}/orders",
            text_body="",
        )
    audit = manager.audit_records()
    encoded_audit = json.dumps(audit)
    assert {item["action"] for item in audit} >= {"issue", "inject"}
    assert assertion not in encoded_audit
    assert "Bearer " not in encoded_audit
    with store._connect() as db:
        columns = {
            row[1]
            for row in db.execute(
                "PRAGMA table_info(business_identity_keys)",
            ).fetchall()
        }
    assert "private_key" not in columns


@pytest.mark.asyncio
async def test_business_identity_outbound_body_and_header_transport(
    plugin_module,
    tmp_path,
):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(204)

    _store, _signer, manager, token = _business_identity_runtime(
        plugin_module,
        tmp_path,
        transport=httpx.MockTransport(handler),
    )

    def issue(key: str) -> dict:
        return manager.issue(
            dclaw_session_token=token,
            service_id="service-1",
            audience=BUSINESS_AUDIENCE,
            scopes=["orders.read"],
            idempotency_key=key,
        )

    no_body = issue("bodyless-request-01")
    await manager.outbound_request(
        dclaw_session_token=token,
        binding_ref=no_body["binding_ref"],
        method="GET",
        url=f"{BUSINESS_AUDIENCE}/orders",
    )
    assert captured[-1].content == b""
    assert captured[-1].headers.get_list("authorization") == [
        captured[-1].headers["authorization"],
    ]
    assert captured[-1].headers["authorization"].startswith("Bearer ")

    json_request = issue("json-request-00001")
    await manager.outbound_request(
        dclaw_session_token=token,
        binding_ref=json_request["binding_ref"],
        method="POST",
        url=f"{BUSINESS_AUDIENCE}/orders",
        headers={"Content-Type": "application/vnd.example+json"},
        json_body={"order_id": "order-1"},
    )
    assert captured[-1].headers.get_list("content-type") == [
        "application/vnd.example+json",
    ]

    duplicate = issue("duplicate-header-01")
    with pytest.raises(Exception, match="BUSINESS_IDENTITY.INVALID_REQUEST"):
        await manager.outbound_request(
            dclaw_session_token=token,
            binding_ref=duplicate["binding_ref"],
            method="GET",
            url=f"{BUSINESS_AUDIENCE}/orders",
            headers={"Accept": "application/json", "accept": "text/plain"},
            text_body="",
        )
    authorization = issue("authorization-req-1")
    with pytest.raises(Exception, match="BUSINESS_IDENTITY.INVALID_REQUEST"):
        await manager.outbound_request(
            dclaw_session_token=token,
            binding_ref=authorization["binding_ref"],
            method="GET",
            url=f"{BUSINESS_AUDIENCE}/orders",
            headers={"Authorization": "Bearer forged"},
            text_body="",
        )
    both = issue("both-bodies-req-1")
    with pytest.raises(Exception, match="BUSINESS_IDENTITY.INVALID_REQUEST"):
        await manager.outbound_request(
            dclaw_session_token=token,
            binding_ref=both["binding_ref"],
            method="POST",
            url=f"{BUSINESS_AUDIENCE}/orders",
            json_body={},
            text_body="",
        )


def test_business_identity_public_keys_cache_rotation_and_bounded_rate_limit(
    plugin_module,
    tmp_path,
):
    store, _signer, broker, service = _runtime(plugin_module, tmp_path)
    _identity_store, _identity_signer, manager, _token = (
        _business_identity_runtime(plugin_module, tmp_path / "identity")
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
        mcp=mcp_cls(service, manager),
        packages=package_cls(
            store,
            PLUGIN_ROOT / "schemas" / "capability-descriptor.schema.json",
            {},
        ),
        credentials=broker,
        business_identity=manager,
    )
    with TestClient(plugin_app) as client:
        first = client.get("/business-identities/verification-keys")
        cached = client.get(
            "/business-identities/verification-keys",
            headers={"If-None-Match": first.headers["etag"]},
        )
        manager.rotate_key(actor_id="admin-1", emergency=False)
        rotated = client.get(
            "/business-identities/verification-keys",
            headers={"If-None-Match": first.headers["etag"]},
        )
    assert first.status_code == 200
    assert first.headers["cache-control"] == "public, max-age=60, must-revalidate"
    assert cached.status_code == 304
    assert rotated.status_code == 200
    assert rotated.headers["etag"] != first.headers["etag"]

    limiter = routes._PublicKeysRateLimiter()
    for index in range(routes.PUBLIC_KEYS_RATE_LIMIT_MAX_CLIENTS):
        assert limiter.allow(f"client-{index}", now=0.0)
    assert not limiter.allow("overflow", now=0.0)
    assert limiter.allow("after-expiry", now=61.0)
    assert len(limiter._requests) == 1


@pytest.mark.asyncio
async def test_business_identity_rotation_and_live_assertion_revocation(
    plugin_module,
    tmp_path,
):
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["assertion"] = request.headers["authorization"].removeprefix(
            "Bearer ",
        )
        return httpx.Response(204)

    _store, _signer, manager, token = _business_identity_runtime(
        plugin_module,
        tmp_path,
        transport=httpx.MockTransport(handler),
    )
    issued = manager.issue(
        dclaw_session_token=token,
        service_id="service-1",
        audience=BUSINESS_AUDIENCE,
        scopes=["orders.read"],
        idempotency_key="rotation-request-1",
    )
    await manager.outbound_request(
        dclaw_session_token=token,
        binding_ref=issued["binding_ref"],
        method="GET",
        url=f"{BUSINESS_AUDIENCE}/orders",
        text_body="",
    )
    assertion = captured["assertion"]
    manager.rotate_key(actor_id="admin-1", emergency=False)
    assert manager.verify_assertion(assertion, **BUSINESS_VERIFY)["jti"]
    next_issued = manager.issue(
        dclaw_session_token=token,
        service_id="service-1",
        audience=BUSINESS_AUDIENCE,
        scopes=["orders.read"],
        idempotency_key="rotation-request-2",
    )
    await manager.outbound_request(
        dclaw_session_token=token,
        binding_ref=next_issued["binding_ref"],
        method="GET",
        url=f"{BUSINESS_AUDIENCE}/orders",
        text_body="",
    )
    next_assertion = captured["assertion"]
    manager.rotate_key(actor_id="admin-1", emergency=True)
    with pytest.raises(Exception, match="BUSINESS_IDENTITY.ASSERTION_INVALID"):
        manager.verify_assertion(next_assertion, **BUSINESS_VERIFY)
    keys = manager.verification_keys()["keys"]
    assert {item["status"] for item in keys} >= {"active", "revoked"}


@pytest.mark.asyncio
async def test_business_identity_online_verify_consumes_jti_atomically(
    plugin_module,
    tmp_path,
):
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["assertion"] = request.headers["authorization"].removeprefix(
            "Bearer ",
        )
        return httpx.Response(204)

    _store, _signer, manager, token = _business_identity_runtime(
        plugin_module,
        tmp_path,
        transport=httpx.MockTransport(handler),
    )
    issued = manager.issue(
        dclaw_session_token=token,
        service_id="service-1",
        audience=BUSINESS_AUDIENCE,
        scopes=["orders.read"],
        idempotency_key="concurrent-verify-1",
    )
    await manager.outbound_request(
        dclaw_session_token=token,
        binding_ref=issued["binding_ref"],
        method="GET",
        url=f"{BUSINESS_AUDIENCE}/orders",
        text_body="",
    )
    assertion = captured["assertion"]

    def verify_once() -> str:
        try:
            manager.verify_assertion(assertion, **BUSINESS_VERIFY)
            return "verified"
        except Exception as exc:  # stable public code is the assertion here
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: verify_once(), range(2)))
    assert sorted(results) == [
        "BUSINESS_IDENTITY.ASSERTION_REPLAYED",
        "verified",
    ]


@pytest.mark.asyncio
async def test_business_identity_rejects_scope_release_path_and_large_response(
    plugin_module,
    tmp_path,
):
    def large_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-length": str(1_048_577)},
            content=b"x",
        )

    _store, signer, manager, token = _business_identity_runtime(
        plugin_module,
        tmp_path,
        transport=httpx.MockTransport(large_handler),
    )
    with pytest.raises(Exception, match="BUSINESS_IDENTITY.SCOPE_NOT_ALLOWED"):
        manager.issue(
            dclaw_session_token=token,
            service_id="service-1",
            audience=BUSINESS_AUDIENCE,
            scopes=["orders.write"],
            idempotency_key="scope-denied-0001",
        )
    wrong_release = signer.issue(
        tenant_id="tenant-1",
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent One",
        installation_id="install-1",
        release_id="release-2",
        invocation_id="invocation-2",
        capability_ids=[BUSINESS_IDENTITY_CAPABILITY],
    )
    with pytest.raises(Exception, match="BUSINESS_IDENTITY.RELEASE_MISMATCH"):
        manager.issue(
            dclaw_session_token=wrong_release,
            service_id="service-1",
            audience=BUSINESS_AUDIENCE,
            scopes=["orders.read"],
            idempotency_key="release-denied-01",
        )
    issued = manager.issue(
        dclaw_session_token=token,
        service_id="service-1",
        audience=BUSINESS_AUDIENCE,
        scopes=["orders.read"],
        idempotency_key="path-denied-00001",
    )
    with pytest.raises(Exception, match="BUSINESS_IDENTITY.AUDIENCE_NOT_ALLOWED"):
        await manager.outbound_request(
            dclaw_session_token=token,
            binding_ref=issued["binding_ref"],
            method="GET",
            url="https://8.8.8.8/admin",
            text_body="",
        )
    encoded = manager.issue(
        dclaw_session_token=token,
        service_id="service-1",
        audience=BUSINESS_AUDIENCE,
        scopes=["orders.read"],
        idempotency_key="encoded-path-0001",
    )
    with pytest.raises(Exception, match="BUSINESS_IDENTITY.AUDIENCE_NOT_ALLOWED"):
        await manager.outbound_request(
            dclaw_session_token=token,
            binding_ref=encoded["binding_ref"],
            method="GET",
            url=f"{BUSINESS_AUDIENCE}/%2e%2e/admin",
            text_body="",
        )
    large = manager.issue(
        dclaw_session_token=token,
        service_id="service-1",
        audience=BUSINESS_AUDIENCE,
        scopes=["orders.read"],
        idempotency_key="large-response-01",
    )
    with pytest.raises(Exception, match="BUSINESS_IDENTITY.RESPONSE_TOO_LARGE"):
        await manager.outbound_request(
            dclaw_session_token=token,
            binding_ref=large["binding_ref"],
            method="GET",
            url=f"{BUSINESS_AUDIENCE}/orders",
            text_body="",
        )
    denied = [
        item for item in manager.audit_records() if item["result"] == "denied"
    ]
    assert {item["reason_code"] for item in denied} >= {
        "BUSINESS_IDENTITY.SCOPE_NOT_ALLOWED",
        "BUSINESS_IDENTITY.RELEASE_MISMATCH",
        "BUSINESS_IDENTITY.AUDIENCE_NOT_ALLOWED",
        "BUSINESS_IDENTITY.RESPONSE_TOO_LARGE",
    }


def test_business_identity_service_change_revocation_and_independent_capability(
    plugin_module,
    tmp_path,
):
    _store, signer, manager, token = _business_identity_runtime(
        plugin_module,
        tmp_path,
    )
    with pytest.raises(
        Exception,
        match="BUSINESS_IDENTITY.SERVICE_UPDATE_REQUIRES_NEW_ID",
    ):
        manager.register_service(
            actor_id="admin-1",
            developer_id="developer-1",
            service_id="service-1",
            audience=BUSINESS_AUDIENCE,
            allowed_domains=["8.8.8.8"],
            allowed_scopes=["orders.read", "orders.write", "admin"],
        )
    with pytest.raises(Exception, match="BUSINESS_IDENTITY.AUDIENCE_NOT_ALLOWED"):
        manager.register_service(
            actor_id="admin-1",
            developer_id="developer-1",
            service_id="reserved-service",
            audience="https://api.example/business/v1",
            allowed_domains=["api.example"],
            allowed_scopes=["orders.read"],
        )
    unauthorized = signer.issue(
        tenant_id="tenant-1",
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_name="Agent One",
        installation_id="install-1",
        release_id="release-1",
        invocation_id="invocation-1",
        capability_ids=["local.execution.session/1"],
    )
    with pytest.raises(Exception, match="BUSINESS_IDENTITY.NOT_GRANTED"):
        manager.issue(
            dclaw_session_token=unauthorized,
            service_id="service-1",
            audience=BUSINESS_AUDIENCE,
            scopes=["orders.read"],
            idempotency_key="not-granted-00001",
        )
    manager.revoke(
        actor_id="admin-1",
        kind="installation",
        tenant_id="tenant-1",
        subject_id="install-1",
        reason="administrative revocation",
    )
    with pytest.raises(
        Exception,
        match="BUSINESS_IDENTITY.INSTALLATION_REVOKED",
    ):
        manager.issue(
            dclaw_session_token=token,
            service_id="service-1",
            audience=BUSINESS_AUDIENCE,
            scopes=["orders.read"],
            idempotency_key="revoked-install-1",
        )


def test_business_identity_schemas_are_closed_and_published_to_devkit():
    names = {
        "issue-request.schema.json",
        "issue-response.schema.json",
        "outbound-request.schema.json",
        "outbound-response.schema.json",
        "error.schema.json",
        "service-registration.schema.json",
        "grant-registration.schema.json",
        "verify-request.schema.json",
        "verify-response.schema.json",
    }
    source = PLUGIN_ROOT / "schemas" / "business-identity-v1"
    published = PLUGIN_ROOT / "devkit" / "schemas" / "business-identity-v1"
    for name in names:
        source_schema = json.loads((source / name).read_text(encoding="utf-8"))
        published_schema = json.loads(
            (published / name).read_text(encoding="utf-8"),
        )
        Draft202012Validator.check_schema(source_schema)
        assert source_schema == published_schema
        assert source_schema["additionalProperties"] is False
    issue_schema = json.loads(
        (source / "issue-request.schema.json").read_text(encoding="utf-8"),
    )
    validator = Draft202012Validator(issue_schema)
    valid = {
        "service_id": "service-1",
        "audience": BUSINESS_AUDIENCE,
        "scopes": ["orders.read"],
        "idempotency_key": "schema-request-01",
    }
    assert not list(validator.iter_errors(valid))
    assert list(validator.iter_errors({**valid, "tenant_id": "forged"}))
    outbound_schema = json.loads(
        (source / "outbound-request.schema.json").read_text(encoding="utf-8"),
    )
    outbound_validator = Draft202012Validator(outbound_schema)
    outbound = {
        "binding_ref": "bir_" + "a" * 32,
        "method": "GET",
        "url": BUSINESS_AUDIENCE,
    }
    assert not list(outbound_validator.iter_errors(outbound))
    assert not list(
        outbound_validator.iter_errors({**outbound, "json_body": {}}),
    )
    assert not list(
        outbound_validator.iter_errors({**outbound, "text_body": ""}),
    )
    assert list(
        outbound_validator.iter_errors(
            {**outbound, "json_body": {}, "text_body": ""},
        ),
    )
    assert list(
        outbound_validator.iter_errors(
            {
                **outbound,
                "headers": {
                    "Accept": "application/json",
                    "accept": "text/plain",
                },
            },
        ),
    ) == []
