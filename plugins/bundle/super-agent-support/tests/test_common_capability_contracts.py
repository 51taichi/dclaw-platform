from __future__ import annotations

import base64
import importlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import validate

from super_agent.aigc_snapshot import project_owned_aigc_snapshot
from super_agent.local_host import bind_local_service, dispatch_local_task


ROOT = Path(__file__).parents[1]


def test_aigc_snapshot_returns_only_owned_asset_ids():
    binding = SimpleNamespace(
        installation_id="installation", conversation_id="task",
        material_task_id="material", canvas_id="canvas", workflow_id="workflow",
        node_bindings={"shot": "node"}, node_id="node",
    )
    asset = SimpleNamespace(id="asset-1", kind="image")
    class Assets:
        def resolve_owned(self, user_id, asset_id):
            assert (user_id, asset_id) == ("customer", "asset-1")
            return asset

        def validate_review_binding(self, resolved, **kwargs):
            assert resolved is asset
            assert kwargs == {"canvas_id": "canvas", "node_ids": {"node"}}

    adapter = SimpleNamespace(
        assets=Assets(),
        workflow_context=lambda **kwargs: (
            SimpleNamespace(id="canvas", meta={"workflow_id": "workflow"},
                            nodes=[SimpleNamespace(id="node")]), [SimpleNamespace(
                id="job-1", canvas_id="canvas", node_id="node", status="succeeded",
                updated_at="2026-11-08T00:00:00+00:00",
                outputs=[SimpleNamespace(id="asset-1", path="/private/customer.png")],
            )],
        ),
    )
    task = SimpleNamespace(
        binding=binding, status=SimpleNamespace(value="IN_PROGRESS"),
        version=2, asset_id=None,
    )
    result = project_owned_aigc_snapshot(
        task=task, adapter=adapter, user_id="customer",
        installation_id="installation", conversation_id="task",
    )
    assert result["generation_assets"] == [
        {"node_id": "node", "job_id": "job-1", "asset_id": "asset-1", "asset_kind": "image"},
    ]
    assert result["node_jobs"] == [
        {"node_id": "node", "job_id": "job-1", "job_status": "succeeded"},
    ]
    assert "/private" not in json.dumps(result)
    validate(result, json.loads((ROOT / "devkit/schemas/aigc-task-snapshot-v1/response.schema.json").read_text()))
    assert project_owned_aigc_snapshot(
        task=task, adapter=adapter, user_id="customer",
        installation_id="another", conversation_id="task",
    )["status"] == "not_found"


@pytest.mark.asyncio
async def test_local_task_receipt_scopes_replay_and_hides_local_result(tmp_path):
    class Store:
        task = None

        def get_task(self, task_id, user_id):
            return self.task if self.task and self.task["task_id"] == task_id and user_id == "customer" else None

    class Service:
        store = Store()

        async def _local_task_start(self, arguments, identity, trace):
            if self.store.task is None:
                self.store.task = {
                    "task_id": "task-1", "tenant_id": "tenant", "user_id": "customer",
                    "session_id": "chat", "agent_id": "expert", "installation_id": "install",
                    "capability_id": arguments["capability_id"],
                    "idempotency_key": arguments["idempotency_key"],
                    "status": "succeeded", "error": None,
                    "result": {"path": "/private/customer.mp4", "artifact_id": "artifact_" + "a" * 32},
                }
            return self.store.task

    bind_local_service(Service())
    scope = dict(tenant_id="tenant", user_id="customer", session_id="chat",
                 agent_id="expert", installation_id="install", release_id="release",
                 invocation_id="invocation")
    started = await dispatch_local_task(
        capability="local.task.start/1",
        arguments={"capability_id": "video.cut", "input": {}, "idempotency_key": "edit-1"},
        **scope,
    )
    assert started["idempotency_key"] == "edit-1"
    assert started["artifact_ids"] == ["artifact_" + "a" * 32]
    assert "/private" not in json.dumps(started)
    validate(started, json.loads((ROOT / "devkit/schemas/local-task-host-v1/receipt.schema.json").read_text()))
    assert (await dispatch_local_task(
        capability="local.task.read/1", arguments={"task_id": "task-1"},
        **{**scope, "session_id": "another"},
    ))["status"] == "not_found"


def test_capability_package_signer_registration_is_admin_backed_and_immutable(tmp_path):
    name = "capability_signer_contract_test"
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    assert spec and spec.loader
    spec.loader.exec_module(package)
    signer_module = importlib.import_module(f"{name}.packages")
    CapabilityPackageRegistry = signer_module.CapabilityPackageRegistry
    PackageError = signer_module.PackageError
    private = Ed25519PrivateKey.generate()
    public = base64.b64encode(private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )).decode()
    registry = CapabilityPackageRegistry(
        SimpleNamespace(), ROOT / "schemas/capability-descriptor.schema.json",
        {}, trust_path=tmp_path / "trusted.json",
    )
    receipt = registry.trust_signer("developer-1", public)
    assert receipt["status"] == "registered"
    assert registry.trust_signer("developer-1", public)["status"] == "already_registered"
    with pytest.raises(PackageError, match="already trusted"):
        other = Ed25519PrivateKey.generate().public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        registry.trust_signer("developer-1", base64.b64encode(other).decode())
    assert json.loads((tmp_path / "trusted.json").read_text())["developer-1"] == public
