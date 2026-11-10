"""Reference Host calls for a Super Agent that genuinely needs local work."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


class LocalTaskContractError(ValueError):
    """A local task request or trusted receipt failed verification."""


_SCHEMA_ROOT = Path(__file__).parent / "schemas/local-task-host-v1"
_START_SCHEMA = json.loads((_SCHEMA_ROOT / "start-request.schema.json").read_text(encoding="utf-8"))
_TASK_SCHEMA = json.loads((_SCHEMA_ROOT / "task-request.schema.json").read_text(encoding="utf-8"))
_RECEIPT_SCHEMA = json.loads((_SCHEMA_ROOT / "receipt.schema.json").read_text(encoding="utf-8"))


async def start_local_task(
    host: Any, *, capability_id: str, input_data: dict[str, Any],
    idempotency_key: str, local_file_bindings: dict[str, Any] | None = None,
) -> str:
    """Use the same key when the acceptance result is uncertain."""
    request = {
        "capability_id": capability_id,
        "input": input_data,
        "idempotency_key": idempotency_key,
    }
    if local_file_bindings is not None:
        request["local_file_bindings"] = local_file_bindings
    Draft202012Validator(_START_SCHEMA).validate(request)
    receipt = await host.call("local.task.start/1", request)
    Draft202012Validator(_RECEIPT_SCHEMA).validate(receipt)
    if receipt["status"] in {"not_found", "unavailable", "rejected"}:
        raise LocalTaskContractError(f"local task {receipt['status']}")
    if (
        not receipt["task_id"]
        or receipt["capability_id"] != capability_id
        or receipt["idempotency_key"] != idempotency_key
    ):
        raise LocalTaskContractError("local task acceptance binding mismatch")
    return receipt["task_id"]


async def read_local_result(
    host: Any, *, task_id: str, capability_id: str, idempotency_key: str,
) -> list[str]:
    """Return opaque artifact IDs only after a terminal success receipt."""
    request = {"task_id": task_id}
    Draft202012Validator(_TASK_SCHEMA).validate(request)
    receipt = await host.call("local.task.read/1", request)
    Draft202012Validator(_RECEIPT_SCHEMA).validate(receipt)
    if receipt["status"] in {"not_found", "unavailable", "rejected"}:
        raise LocalTaskContractError(f"local task {receipt['status']}")
    if (
        receipt["task_id"] != task_id
        or receipt["capability_id"] != capability_id
        or receipt["idempotency_key"] != idempotency_key
    ):
        raise LocalTaskContractError("local task read binding mismatch")
    if receipt["status"] != "succeeded":
        raise LocalTaskContractError(f"local task not complete: {receipt['status']}")
    if not receipt["artifact_ids"] or not receipt["result_sha256"]:
        raise LocalTaskContractError("local success has no verified artifact")
    return receipt["artifact_ids"]
