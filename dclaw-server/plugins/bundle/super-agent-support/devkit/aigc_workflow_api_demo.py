"""Reference AIGC workflow calls for a signed Super Agent.

The catalog/create callables are the granted runtime model tools. The Host
snapshot is a separate read after the customer has completed the task. Legacy
review states remain readable for experts created against earlier contracts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker


class AigcContractError(ValueError):
    """A live catalog, workflow result or owned asset failed verification."""


_SNAPSHOT_SCHEMA = json.loads((
    Path(__file__).parent / "schemas/aigc-task-snapshot-v1/response.schema.json"
).read_text(encoding="utf-8"))
_BINDING_SCHEMA = json.loads((
    Path(__file__).parent / "schemas/aigc-task-binding-v1/response.schema.json"
).read_text(encoding="utf-8"))


async def recover_existing_task(
    host: Any, *, task_key: str | None = None,
    content_revision: int | None = None,
) -> dict[str, Any]:
    """Read a unique owned task after a compatible installation upgrade."""
    request: dict[str, Any] = {}
    if task_key is not None:
        request["task_key"] = task_key
    if content_revision is not None:
        request["content_revision"] = content_revision
    reply = await host.call("aigc.task.binding.resolve/1", request)
    Draft202012Validator(_BINDING_SCHEMA).validate(reply)
    if reply["status"] != "found":
        raise AigcContractError(f"AIGC binding {reply['status']}")
    return reply


def _tool_payload(reply: Any) -> dict[str, Any]:
    if isinstance(reply, dict):
        return reply
    content = getattr(reply, "content", None)
    if not isinstance(content, list) or len(content) != 1:
        raise AigcContractError("invalid AIGC tool response")
    block = content[0]
    raw = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise AigcContractError("invalid AIGC tool JSON") from exc
    if not isinstance(value, dict):
        raise AigcContractError("AIGC tool result must be an object")
    return value


async def create_workflow(
    catalog_tool: Any,
    create_tool: Any,
    *,
    node_kinds: list[str],
    workflow: dict[str, Any],
    task_key: str,
    content_revision: int,
) -> dict[str, str]:
    """Return only Host-bound IDs after a validated workflow is created."""
    if not task_key or type(content_revision) is not int or content_revision < 1:
        raise AigcContractError("invalid stable workflow identity")
    if not node_kinds or any(not isinstance(kind, str) or not kind for kind in node_kinds):
        raise AigcContractError("explicit node kinds are required")
    listed = _tool_payload(await catalog_tool(node_kinds))
    if listed.get("error"):
        raise AigcContractError("AIGC catalog unavailable")
    catalog = listed.get("catalog")
    schema = listed.get("workflow_schema")
    if not isinstance(catalog, dict) or not isinstance(schema, dict):
        raise AigcContractError("missing live workflow catalog or schema")
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(workflow)
    available_nodes = {
        item.get("kind"): item for item in catalog.get("nodes", [])
        if isinstance(item, dict) and item.get("provisioning") == "AUTO_PROVISIONABLE"
    }
    models = {
        (item.get("capability"), item.get("provider_id"), item.get("model_id"))
        for item in catalog.get("available_models", []) if isinstance(item, dict)
    }
    for node in workflow["nodes"]:
        registration = available_nodes.get(node["kind"])
        if node["kind"] not in node_kinds or registration is None:
            raise AigcContractError("workflow node is unavailable")
        selected_model = (node.get("capability"), node.get("provider_id"), node.get("model_id"))
        if (registration.get("requires_model") or any(selected_model)) and selected_model not in models:
            raise AigcContractError("workflow model is absent from live catalog")
    created = _tool_payload(await create_tool(task_key, content_revision, workflow))
    if created.get("error"):
        raise AigcContractError(f"AIGC create rejected: {created['error']}")
    event = created.get("event")
    task = created.get("task")
    binding = task.get("binding") if isinstance(task, dict) else None
    if not isinstance(event, dict) or not isinstance(binding, dict):
        raise AigcContractError("missing persisted AIGC task or event")
    material_id = binding.get("material_task_id")
    canvas_id = binding.get("canvas_id")
    if (
        event.get("event_type") != "aigc.task.created"
        or not isinstance(material_id, str) or not material_id
        or not isinstance(canvas_id, str) or not canvas_id
        or event.get("material_task_id") != material_id
        or event.get("canvas_id") != canvas_id
        or event.get("installation_id") != binding.get("installation_id")
        or event.get("conversation_id") != binding.get("conversation_id")
        or event.get("content_revision") != content_revision
    ):
        raise AigcContractError("AIGC creation binding mismatch")
    return {"material_task_id": material_id, "canvas_id": canvas_id}


async def read_submitted_asset(
    host: Any, *, material_task_id: str, canvas_id: str,
    node_id: str, asset_kind: str,
) -> str:
    """Return an owned completed/legacy asset ID, never a guessed URL or path."""
    snapshot = await host.call("aigc.task.snapshot/1", {"material_task_id": material_task_id})
    Draft202012Validator(_SNAPSHOT_SCHEMA).validate(snapshot)
    if snapshot["status"] != "found":
        raise AigcContractError(f"AIGC snapshot {snapshot['status']}")
    if (
        snapshot["material_task_id"] != material_task_id
        or snapshot["canvas_id"] != canvas_id
        or snapshot["task_status"] not in {"SUBMITTED", "REVIEWING", "ACCEPTED"}
    ):
        raise AigcContractError("AIGC task is not submitted in the expected canvas")
    successful = {
        (job["node_id"], job["job_id"])
        for job in snapshot["node_jobs"] if job["job_status"] == "succeeded"
    }
    matches = [
        asset["asset_id"] for asset in snapshot["generation_assets"]
        if asset["node_id"] == node_id and asset["asset_kind"] == asset_kind
        and (asset["node_id"], asset["job_id"]) in successful
        and asset["asset_id"] == snapshot["submitted_asset_id"]
    ]
    if len(matches) != 1:
        raise AigcContractError("no unique submitted asset in a successful node")
    return matches[0]
