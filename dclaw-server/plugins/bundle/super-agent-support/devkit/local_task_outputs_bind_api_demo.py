"""Minimal sealed Host sequence for reusing localized files in another task."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import validate


SCHEMAS = Path(__file__).parent / "schemas"


def _validate(document, schema):
    validate(document, json.loads((SCHEMAS / schema).read_text(encoding="utf-8")))


async def start_from_localized_outputs(
    host, *, source_task_id, slots, capability_id, input_data, idempotency_key,
):
    request = {"source_task_id": source_task_id, "slots": slots}
    _validate(request, "local-task-outputs-bind-v1/request.schema.json")
    bound = await host.call("local.task.outputs.bind/1", request)
    _validate(bound, "local-task-outputs-bind-v1/response.schema.json")
    if bound["status"] != "bound":
        return bound
    bindings = {
        item["slot"]: {"local_file_ref": item["file"]["local_file_ref"], "access": "read"}
        for item in bound["files"]
    }
    start = {
        "capability_id": capability_id, "input": input_data,
        "idempotency_key": idempotency_key,
        "local_file_bindings": bindings,
    }
    _validate(start, "local-task-host-v1/start-request.schema.json")
    receipt = await host.call("local.task.start/1", start)
    _validate(receipt, "local-task-host-v1/receipt.schema.json")
    return receipt
