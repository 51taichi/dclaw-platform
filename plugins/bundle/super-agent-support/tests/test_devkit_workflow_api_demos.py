from __future__ import annotations

from copy import deepcopy
import io
import json
from pathlib import Path
import zipfile

import pytest

from devkit.aigc_workflow_api_demo import (
    AigcContractError, create_workflow, read_submitted_asset,
    recover_existing_task,
)
from devkit.local_task_api_demo import (
    LocalTaskContractError, read_local_result, start_local_task,
)
from qwenpaw.aigc.workflow_contract import WorkflowBlueprint
from developer_pack.archive import build_archive
from jsonschema import Draft202012Validator


PLUGIN_ROOT = Path(__file__).parents[1]


WORKFLOW = {
    "schema_version": 1, "title": "Image task",
    "execution_preference": "CUSTOMER_TRIGGERED",
    "nodes": [{
        "node_id": "image", "kind": "image_generate", "title": "Image",
        "capability": "text_to_image", "provider_id": "image-provider",
        "model_id": "image-v1", "inputs": {"prompt": "A classroom"},
        "parameters": {"aspect_ratio": "9:16", "count": 1},
        "customer_action": "CLICK_GENERATE", "optional": False,
    }],
    "edges": [], "output_node_id": "image", "review_node_ids": ["image"],
    "fallback_policy": "FAIL_CLOSED",
}
CATALOG = {
    "catalog": {"nodes": [{
        "kind": "image_generate", "provisioning": "AUTO_PROVISIONABLE",
        "requires_model": True,
    }], "available_models": [{
        "capability": "text_to_image", "provider_id": "image-provider",
        "model_id": "image-v1",
    }]},
    "workflow_schema": WorkflowBlueprint.model_json_schema(),
}
CREATE_RESULT = {
    "event": {
        "event_type": "aigc.task.created", "material_task_id": "material-1",
        "canvas_id": "canvas-1", "installation_id": "install-1",
        "conversation_id": "conversation-1", "content_revision": 1,
    },
    "task": {"binding": {
        "material_task_id": "material-1", "canvas_id": "canvas-1",
        "installation_id": "install-1", "conversation_id": "conversation-1",
    }},
}
SNAPSHOT = {
    "contract": "aigc.task.snapshot/1", "status": "found",
    "material_task_id": "material-1", "workflow_id": "workflow-1",
    "canvas_id": "canvas-1", "task_status": "SUBMITTED", "task_version": 2,
    "submitted_asset_id": "asset-1",
    "node_jobs": [{"node_id": "node-1", "job_id": "job-1", "job_status": "succeeded"}],
    "generation_assets": [{
        "node_id": "node-1", "job_id": "job-1", "asset_id": "asset-1",
        "asset_kind": "image",
    }],
}
LOCAL_RECEIPT = {
    "contract": "local.task.receipt/1", "task_id": "task-1",
    "capability_id": "video.render", "idempotency_key": "render-rev-1",
    "status": "succeeded", "error_code": None,
    "artifact_ids": ["artifact_" + "a" * 32], "result_sha256": "b" * 64,
}


@pytest.mark.asyncio
async def test_recover_existing_task_uses_closed_host_contract():
    class Host:
        async def call(self, capability, arguments):
            assert capability == "aigc.task.binding.resolve/1"
            assert arguments == {"task_key": "production", "content_revision": 1}
            return {
                "contract": capability, "status": "found",
                "material_task_id": "material-1",
                "source_installation_id": "installation-1",
                "content_revision": 1, "task_status": "ACCEPTED",
            }

    result = await recover_existing_task(
        Host(), task_key="production", content_revision=1,
    )
    assert result["material_task_id"] == "material-1"


@pytest.mark.asyncio
async def test_aigc_demo_uses_live_catalog_then_checks_bound_creation():
    calls = []

    async def catalog_tool(kinds):
        calls.append(("catalog", kinds))
        return CATALOG

    async def create_tool(task_key, revision, workflow):
        calls.append(("create", task_key, revision, workflow))
        return CREATE_RESULT

    result = await create_workflow(
        catalog_tool, create_tool, node_kinds=["image_generate"],
        workflow=WORKFLOW, task_key="campaign-image", content_revision=1,
    )
    assert result == {"material_task_id": "material-1", "canvas_id": "canvas-1"}
    assert [call[0] for call in calls] == ["catalog", "create"]

    calls.clear()
    wrong = deepcopy(WORKFLOW)
    wrong["nodes"][0]["model_id"] = "guessed-model"
    with pytest.raises(AigcContractError, match="live catalog"):
        await create_workflow(
            catalog_tool, create_tool, node_kinds=["image_generate"],
            workflow=wrong, task_key="campaign-image", content_revision=1,
        )
    assert [call[0] for call in calls] == ["catalog"]

    async def wrong_create(*_args):
        result = deepcopy(CREATE_RESULT)
        result["event"]["canvas_id"] = "another-canvas"
        return result

    with pytest.raises(AigcContractError, match="binding mismatch"):
        await create_workflow(
            catalog_tool, wrong_create, node_kinds=["image_generate"],
            workflow=WORKFLOW, task_key="campaign-image", content_revision=1,
        )


@pytest.mark.asyncio
async def test_aigc_demo_requires_submitted_owned_successful_asset():
    class Host:
        value = SNAPSHOT

        async def call(self, name, request):
            assert (name, request) == (
                "aigc.task.snapshot/1", {"material_task_id": "material-1"},
            )
            return self.value

    host = Host()
    args = dict(material_task_id="material-1", canvas_id="canvas-1",
                node_id="node-1", asset_kind="image")
    assert await read_submitted_asset(host, **args) == "asset-1"
    host.value = {**SNAPSHOT, "task_status": "WAITING_TO_START"}
    with pytest.raises(AigcContractError, match="not submitted"):
        await read_submitted_asset(host, **args)
    host.value = {**SNAPSHOT, "canvas_id": "another-canvas"}
    with pytest.raises(AigcContractError, match="expected canvas"):
        await read_submitted_asset(host, **args)


@pytest.mark.asyncio
async def test_local_demo_requires_stable_key_and_terminal_verified_artifact():
    class Host:
        value = LOCAL_RECEIPT
        calls = []

        async def call(self, name, request):
            self.calls.append((name, request))
            return self.value

    host = Host()
    task_id = await start_local_task(
        host, capability_id="video.render", input_data={"timeline_ref": "ref-1"},
        idempotency_key="render-rev-1",
    )
    assert task_id == "task-1"
    assert host.calls[0] == ("local.task.start/1", {
        "capability_id": "video.render", "input": {"timeline_ref": "ref-1"},
        "idempotency_key": "render-rev-1",
    })
    assert await read_local_result(
        host, task_id=task_id, capability_id="video.render",
        idempotency_key="render-rev-1",
    ) == LOCAL_RECEIPT["artifact_ids"]
    host.value = {**LOCAL_RECEIPT, "status": "running", "artifact_ids": [], "result_sha256": None}
    with pytest.raises(LocalTaskContractError, match="not complete"):
        await read_local_result(
            host, task_id=task_id, capability_id="video.render",
            idempotency_key="render-rev-1",
        )
    host.value = {**LOCAL_RECEIPT, "idempotency_key": "another-key"}
    with pytest.raises(LocalTaskContractError, match="binding mismatch"):
        await read_local_result(
            host, task_id=task_id, capability_id="video.render",
            idempotency_key="render-rev-1",
        )


def test_pack_exposes_aigc_and_local_api_references():
    payload, metadata = build_archive(PLUGIN_ROOT)
    assert metadata["standard"]["version"] == "2.54"
    assert metadata["devkit_version"] == "1.9.21"
    prefix = f"dclaw-super-agent-developer-pack-{metadata['version']}/"
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        for path in (
            "devkit/aigc_workflow_api_demo.py",
            "devkit/aigc_binding_api_demo.py",
            "devkit/runtime_diagnostics_api_demo.py",
            "devkit/schemas/runtime-diagnostics-v4/by-reference-response.schema.json",
            "devkit/local_task_api_demo.py",
            "devkit/examples/aigc-workflow-v1/README.md",
            "devkit/examples/aigc-workflow-v1/submitted-snapshot.sample.json",
            "devkit/examples/local-task-host-v1/README.md",
            "devkit/examples/local-task-host-v1/task-success.sample.json",
            "devkit/schemas/aigc-task-snapshot-v1/response.schema.json",
            "devkit/schemas/aigc-task-binding-v1/request.schema.json",
            "devkit/schemas/aigc-task-binding-v1/response.schema.json",
            "devkit/schemas/developer-aigc-binding-v1/request.schema.json",
            "devkit/schemas/developer-aigc-binding-v1/response.schema.json",
            "devkit/schemas/aigc-task-assets-v1/list-request.schema.json",
            "devkit/schemas/aigc-task-assets-v1/list-response.schema.json",
            "devkit/schemas/aigc-task-assets-v1/localize-request.schema.json",
            "devkit/schemas/local-task-host-v1/receipt.schema.json",
        ):
            assert prefix + path in names
        standard = archive.read(
            prefix
            + "standard/super-agent-development-standard-v1.zh-CN.md",
        ).decode("utf-8")
        for reference in (
            "aigc.task.assets.list/1",
            "aigc.task.assets.localize/1",
            "schemas/aigc-task-assets-v1/",
            "examples/aigc-workflow-v1/README.md",
            "Helper `1.4.5`",
        ):
            assert reference in standard
        catalog = json.loads(archive.read(prefix + "devkit/operation-catalog.json"))
        assert catalog["aigc_workflow_host"]["api_demo"] == "aigc_workflow_api_demo.py"
        assert catalog["local_task_host"]["api_demo"] == "local_task_api_demo.py"
        snapshot = json.loads(archive.read(
            prefix + catalog["aigc_workflow_host"]["snapshot_example"].replace(
                "examples/", "devkit/examples/", 1,
            ),
        ))
        local = json.loads(archive.read(
            prefix + catalog["local_task_host"]["receipt_example"].replace(
                "examples/", "devkit/examples/", 1,
            ),
        ))
        for example, schema_path in (
            (snapshot, "aigc-task-snapshot-v1/response.schema.json"),
            (local["start_request"], "local-task-host-v1/start-request.schema.json"),
            (local["read_request"], "local-task-host-v1/task-request.schema.json"),
            (local["accepted_receipt"], "local-task-host-v1/receipt.schema.json"),
            (local["success_receipt"], "local-task-host-v1/receipt.schema.json"),
        ):
            schema = json.loads(archive.read(prefix + "devkit/schemas/" + schema_path))
            Draft202012Validator(schema).validate(example)
