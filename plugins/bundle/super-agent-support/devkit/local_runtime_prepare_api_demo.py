"""Sealed Host reference for preparing one signed local capability package."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import validate


SCHEMAS = Path(__file__).parent / "schemas/local-runtime-prepare-v1"


async def prepare_local_runtime(
    host, *, capability_id: str, package_id: str, package_version: str,
    device_id: str | None = None,
) -> dict:
    request = {"capability_id": capability_id}
    if device_id is not None:
        request["device_id"] = device_id
    validate(request, json.loads((SCHEMAS / "request.schema.json").read_text(encoding="utf-8")))
    receipt = await host.call("local.runtime.prepare/1", request)
    validate(receipt, json.loads((SCHEMAS / "response.schema.json").read_text(encoding="utf-8")))
    if receipt.get("capability_id") not in (None, capability_id):
        raise ValueError("local runtime preparation returned a different capability")
    if receipt["status"] in {
        "ready", "preparing", "device_not_ready", "runner_update_required",
    } and (
        receipt["package_id"] != package_id
        or receipt["package_version"] != package_version
    ):
        raise ValueError("registered local package differs from the pinned version")
    return receipt
