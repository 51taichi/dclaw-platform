"""Submit FFmpeg argv through the registered platform local capability."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

CAPABILITY_ID = "dclaw.ffmpeg.command"
PACKAGE_VERSION = "0.1.0"
ROOT = Path(__file__).parent
SCHEMA = json.loads((ROOT / "schemas/local-ffmpeg-command-v1/input.schema.json").read_text(encoding="utf-8"))
START_SCHEMA = json.loads((ROOT / "schemas/local-task-host-v1/start-request.schema.json").read_text(encoding="utf-8"))
RECEIPT_SCHEMA = json.loads((ROOT / "schemas/local-task-host-v1/receipt.schema.json").read_text(encoding="utf-8"))


async def start_ffmpeg_command(
    host: Any, *, arguments: list[str], output_files: list[str],
    local_file_bindings: dict[str, Any], idempotency_key: str,
) -> str:
    preparation = await host.call(
        "local.runtime.prepare/1", {"capability_id": CAPABILITY_ID},
    )
    if (
        preparation.get("status") != "ready"
        or preparation.get("capability_id") != CAPABILITY_ID
        or preparation.get("package_version") != PACKAGE_VERSION
    ):
        raise ValueError("platform FFmpeg command package is not ready")
    task_input = {"arguments": arguments, "output_files": output_files}
    Draft202012Validator(SCHEMA).validate(task_input)
    request = {
        "capability_id": CAPABILITY_ID,
        "input": task_input,
        "local_file_bindings": local_file_bindings,
        "idempotency_key": idempotency_key,
    }
    Draft202012Validator(START_SCHEMA).validate(request)
    receipt = await host.call("local.task.start/1", request)
    Draft202012Validator(RECEIPT_SCHEMA).validate(receipt)
    if (
        receipt["status"] in {"not_found", "rejected", "unavailable"}
        or receipt.get("capability_id") != CAPABILITY_ID
        or receipt.get("idempotency_key") != idempotency_key
        or not receipt.get("task_id")
    ):
        raise ValueError("platform FFmpeg command task was not accepted")
    return receipt["task_id"]
