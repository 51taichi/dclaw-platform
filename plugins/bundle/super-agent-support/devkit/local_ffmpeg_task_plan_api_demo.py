"""Submit a structured timeline to the shared local video renderer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

CAPABILITY_ID = "dclaw.ffmpeg.task.plan"
PACKAGE_VERSION = "0.1.0"
ROOT = Path(__file__).parent
SCHEMA = json.loads((ROOT / "schemas/local-ffmpeg-task-plan-v1/input.schema.json").read_text(encoding="utf-8"))
START_SCHEMA = json.loads((ROOT / "schemas/local-task-host-v1/start-request.schema.json").read_text(encoding="utf-8"))
RECEIPT_SCHEMA = json.loads((ROOT / "schemas/local-task-host-v1/receipt.schema.json").read_text(encoding="utf-8"))


async def start_ffmpeg_task_plan(
    host: Any, *, timeline: dict[str, Any],
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
        raise ValueError("platform video renderer is not ready")
    Draft202012Validator(SCHEMA).validate(timeline)
    if any(
        clip["trim_end_ms"] <= clip["trim_start_ms"]
        for clip in timeline["clips"]
    ):
        raise ValueError("clip trim end must follow start")
    slots = {clip["slot"] for clip in timeline["clips"]}
    if slots != set(local_file_bindings):
        raise ValueError("timeline slots and file bindings differ")
    request = {
        "capability_id": CAPABILITY_ID,
        "input": timeline,
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
        raise ValueError("platform video render task was not accepted")
    return receipt["task_id"]
