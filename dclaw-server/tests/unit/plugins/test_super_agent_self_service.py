from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from qwenpaw.app.guards import require_user
from qwenpaw.app.sealed_agents.package import build_signed_package_bytes
from qwenpaw.app.sealed_agents.registry import SealedAgentRegistry
from qwenpaw.app.sealed_agents.service import SealedAgentService
from qwenpaw.bundled_plugins import load_bundled_plugin_module


def _plugin_module(name: str):
    return load_bundled_plugin_module(
        "dclaw.super-agent-support", "super-agent-support",
        f"super_agent.{name}",
    )


capabilities = _plugin_module("capabilities")
package_handlers = _plugin_module("package_handler")
publication_module = _plugin_module("publication")
publishers = _plugin_module("publishers")
public_runtime = _plugin_module("public_runtime")


def _signed_package(signer_id: str, key: Ed25519PrivateKey, *, version="0.1.0"):
    declared = [
        {"capability_id": name, "contract_version": "1"}
        for name in (
            "workspace.turn.orchestrate/1", "agent.execute", "session.context",
            "runtime.trace", "runtime.complete", "runtime.fail",
        )
    ]
    manifest = {
        "schema_version": 3,
        "agent_id": "self-service-example",
        "name": "Self Service Example",
        "version": version,
        "agent_type": "sealed",
        "scope": "global",
        "entrypoint": "agent/agent.json",
        "package_type": "super_expert_public",
        "orchestration": {
            "capability_id": "workspace.turn.orchestrate/1",
            "contract_version": "1",
            "entrypoint": "runtime.py:create_runtime",
            "required_host_capabilities": [
                "agent.execute", "session.context", "runtime.trace",
                "runtime.complete", "runtime.fail",
            ],
        },
        "platform_contract_versions": {"runtime": "1", "runtime_host": "1"},
        "capabilities": declared,
        "signer_id": signer_id,
    }
    manifest["capability_digest"] = (
        capabilities.compute_capability_set_digest(manifest)
    )
    files = {
        "agent/agent.json": json.dumps({
            "id": "self-service-example", "name": "Self Service Example",
            "orchestration": {
                "enabled": True, "contract_version": "1",
                "entrypoint": "runtime.py:create_runtime",
                "required_host_capabilities": [
                    "agent.execute", "session.context", "runtime.trace",
                    "runtime.complete", "runtime.fail",
                ],
            },
        }).encode(),
        "agent/runtime.py": (
            b"class Runtime:\n"
            b"    async def handle(self, request, host):\n"
            b"        await host.call('runtime.complete', "
            b"{'invocation_id': request.invocation_id, "
            b"'message': {'name': 'assistant', 'role': 'assistant', "
            b"'content': 'ok'}})\n"
            b"def create_runtime(): return Runtime()\n"
        ),
    }
    return build_signed_package_bytes(manifest, files, key)


def _public_key(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def test_public_type_has_restricted_tools_and_official_type_is_unchanged(tmp_path):
    repository = publishers.PublisherRepository(tmp_path / "publishers.sqlite3")
    public = package_handlers.PublicSuperAgentPackageHandler(
        tmp_path, publisher_repository=repository,
    )
    official = package_handlers.SuperAgentPackageHandler(
        tmp_path, official_signer_ids=frozenset({"official"}),
    )

    assert public.supports_runtime_feature("unrestricted_tools") is False
    assert public.supports_runtime_feature("mcp_client") is False
    assert official.supports_runtime_feature("unrestricted_tools") is True
    assert official.supports_runtime_feature("mcp_client") is True


def test_public_runtime_fails_closed_without_isolator(tmp_path):
    async def run():
        await public_runtime.invoke_public_runtime(
            source_root=tmp_path,
            entrypoint="runtime.py:create_runtime",
            request=SimpleNamespace(),
            host=SimpleNamespace(),
            timeout_seconds=1,
            bwrap_path=tmp_path / "missing-bwrap",
        )

    with pytest.raises(public_runtime.PublicRuntimeError, match="isolation"):
        import asyncio
        asyncio.run(run())


def test_public_runtime_local_probe_requires_live_worker(tmp_path, monkeypatch):
    bwrap = tmp_path / "bwrap"
    bwrap.write_bytes(b"executable")
    worker = tmp_path / "public_worker.py"

    assert public_runtime.isolation_available(
        bwrap_path=bwrap, socket_path="", worker_path=worker,
    ) is False

    worker.write_text("# runtime worker\n", encoding="utf-8")
    monkeypatch.setattr(
        public_runtime.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )
    assert public_runtime.isolation_available(
        bwrap_path=bwrap, socket_path="", worker_path=worker,
    ) is True


def test_public_runtime_relays_host_calls_over_unix_socket(tmp_path, monkeypatch):
    import asyncio

    socket_path = Path("/tmp") / f"dclaw-{uuid.uuid4().hex[:8]}.sock"
    monkeypatch.setenv(
        "DCLAW_SUPER_AGENT_SANDBOX_SOCKET", str(socket_path),
    )

    class Request:
        state_root = tmp_path / "state"
        transaction_root = tmp_path / "transaction"

        def model_dump(self, *, mode):
            assert mode == "json"
            return {
                "state_root": str(self.state_root),
                "transaction_root": str(self.transaction_root),
            }

    class Host:
        async def call(self, capability, arguments):
            assert capability == "session.context"
            assert arguments == {}
            return {"session_id": "session-1"}

    async def handle(reader, writer):
        start = json.loads(await reader.readline())
        assert start["type"] == "start"
        assert start["source_root"] == str(tmp_path)
        writer.write(
            b'{"type":"call","capability":"session.context",'
            b'"arguments":{}}\n'
        )
        await writer.drain()
        result = json.loads(await reader.readline())
        assert result["value"] == {"session_id": "session-1"}
        writer.write(b'{"type":"done"}\n')
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def run():
        server = await asyncio.start_unix_server(handle, path=str(socket_path))
        async with server:
            await public_runtime.invoke_public_runtime(
                source_root=tmp_path,
                entrypoint="runtime.py:create_runtime",
                request=Request(), host=Host(), timeout_seconds=2,
            )

    try:
        asyncio.run(run())
    finally:
        socket_path.unlink(missing_ok=True)


def test_normal_user_registers_publishes_and_cannot_take_another_agent(
    tmp_path, monkeypatch,
):
    repository = publishers.PublisherRepository(tmp_path / "publishers.sqlite3")
    handler = package_handlers.PublicSuperAgentPackageHandler(
        tmp_path / "sealed", publisher_repository=repository,
    )
    service = SealedAgentService(
        root=tmp_path / "sealed",
        registry=SealedAgentRegistry(tmp_path / "sealed"),
        trusted_signers={},
        package_type_handlers={"super_expert_public": handler},
    )
    monkeypatch.setattr(
        publication_module, "get_sealed_agent_service", lambda: service,
    )
    config = SimpleNamespace(agents=SimpleNamespace(profiles={}))
    monkeypatch.setattr(publication_module, "load_config", lambda: config)
    monkeypatch.setattr(publication_module, "save_config", lambda _: None)

    publication = publication_module.PublisherPublication(
        repository, handler, tmp_path, isolation_available=lambda: True,
    )
    app = FastAPI()

    @app.middleware("http")
    async def identity(request, call_next):
        request.state.user_id = request.headers.get("x-user")
        request.state.tenant_id = "local"
        return await call_next(request)

    class Manager:
        def is_agent_loaded(self, _agent_id):
            return False

        async def preload_agent(self, _agent_id):
            return True

    app.state.multi_agent_manager = Manager()
    secured = APIRouter(dependencies=[Depends(require_user)])
    secured.include_router(publication.router)
    app.include_router(secured, prefix="/api/user/super-expert-publishing")
    client = TestClient(app)
    path = "/api/user/super-expert-publishing"

    key_a = Ed25519PrivateKey.generate()
    registration = client.post(
        f"{path}/signers", json={"public_key": _public_key(key_a)},
        headers={"x-user": "alice"},
    )
    assert registration.status_code == 200
    signer_a = registration.json()["signer_id"]
    archive = _signed_package(signer_a, key_a)

    wrong_user = client.post(
        f"{path}/releases",
        files={"file": ("agent.zip", archive, "application/zip")},
        headers={"x-user": "bob"},
    )
    assert wrong_user.status_code == 403

    published = client.post(
        f"{path}/releases",
        files={"file": ("agent.zip", archive, "application/zip")},
        headers={"x-user": "alice"},
    )
    assert published.status_code == 200, published.text
    assert published.json()["state"] == "active"
    assert published.json()["visibility"] == "public"
    response_schema = json.loads((
        Path(publication_module.__file__).parents[1]
        / "devkit" / "schemas" / "publishing-v1"
        / "release-response.schema.json"
    ).read_text(encoding="utf-8"))
    Draft202012Validator(response_schema).validate(published.json())
    record = service.get_agent("self-service-example")
    assert record.active_release.package_type == "super_expert_public"
    grant = handler.grant_repository.find_release_grant(
        record.agent_id, record.active_release, tenant_id="local",
    )
    assert grant.authorization_source == "publisher"

    key_b = Ed25519PrivateKey.generate()
    signer_b = client.post(
        f"{path}/signers", json={"public_key": _public_key(key_b)},
        headers={"x-user": "bob"},
    ).json()["signer_id"]
    takeover = client.post(
        f"{path}/releases",
        files={"file": (
            "agent.zip", _signed_package(signer_b, key_b, version="0.2.0"),
            "application/zip",
        )},
        headers={"x-user": "bob"},
    )
    assert takeover.status_code == 409
    assert service.get_agent("self-service-example").active_release_id == (
        record.active_release_id
    )
    assert client.get(
        f"{path}/agents", headers={"x-user": "bob"},
    ).json() == {"agents": []}

    class UnavailableManager(Manager):
        async def preload_agent(self, _agent_id):
            return False

    app.state.multi_agent_manager = UnavailableManager()
    failed_update = client.post(
        f"{path}/releases",
        files={"file": (
            "agent.zip", _signed_package(signer_a, key_a, version="0.2.0"),
            "application/zip",
        )},
        headers={"x-user": "alice"},
    )
    assert failed_update.status_code == 422
    detail = failed_update.json()["detail"]
    assert detail["uploaded"] is True
    assert detail["granted"] is True
    assert detail["active"] is False
    assert detail["release_id"]
    assert service.get_agent("self-service-example").active_release_id == (
        record.active_release_id
    )

    app.state.multi_agent_manager = Manager()
    retry = client.post(
        f"{path}/agents/self-service-example/releases/"
        f"{detail['release_id']}/activate",
        headers={"x-user": "alice"},
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["release_id"] == detail["release_id"]

    StateContinuityError = _plugin_module("state_continuity").StateContinuityError

    def incompatible(**_):
        raise StateContinuityError("state_schema_incompatible")

    monkeypatch.setattr(publication_module, "preview_activation_continuity", incompatible)
    previous_active = service.get_agent("self-service-example").active_release_id
    blocked = client.post(
        f"{path}/releases",
        files={"file": (
            "agent.zip", _signed_package(signer_a, key_a, version="0.3.0"),
            "application/zip",
        )},
        headers={"x-user": "alice"},
    )
    assert blocked.status_code == 422
    blocked_detail = blocked.json()["detail"]
    assert blocked_detail["category"] == "state_schema_incompatible"
    assert blocked_detail["uploaded"] is True
    assert blocked_detail["active"] is False
    assert service.get_agent("self-service-example").active_release_id == previous_active

    monkeypatch.setattr(
        publication_module, "preview_activation_continuity",
        lambda **_: {"contract": "workspace.state.continuity/1",
                    "status": "ready", "checked_tasks": 1},
    )
    resumed = client.post(
        f"{path}/agents/self-service-example/releases/"
        f"{blocked_detail['release_id']}/activate",
        headers={"x-user": "alice"},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["state_continuity"]["checked_tasks"] == 1
