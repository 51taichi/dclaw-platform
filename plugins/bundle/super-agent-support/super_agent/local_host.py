"""Trusted sealed-runtime bridge to plugin-owned local tasks."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

if __package__ == "super_agent":
    from contracts import PublicError
else:
    from ..contracts import PublicError

_service: Any | None = None
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_ARTIFACT = re.compile(r"artifact_[A-Za-z0-9_-]{32,156}\Z")
_CAPABILITY = re.compile(r"[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]*)+\Z")


def bind_local_service(service: Any) -> None:
    global _service
    _service = service


def read_invocation_task_summaries(**scope: str) -> list[dict[str, Any]] | None:
    if _service is None:
        return None
    return _service.store.invocation_task_summaries(**scope)


def read_diagnostic_tasks(**scope: Any) -> list[dict[str, Any]] | None:
    if _service is None:
        return None
    return _service.store.diagnostic_tasks(**scope)


def read_diagnostic_device(user_id: str, device_id: str) -> dict[str, Any] | None:
    if _service is None:
        return None
    device = _service.store.get_device_for_user(device_id, user_id)
    if device is None:
        return None
    return {
        "online": device_id in _service._connections and device["status"] == "online",
        "runner_version": device["runner_version"],
    }


def _scope_key(identity: dict[str, Any]) -> str:
    scope = {key: identity[key] for key in (
        "t", "u", "s", "a", "g",
    )}
    return hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()


def _owned(task: dict[str, Any] | None, identity: dict[str, Any]) -> bool:
    return bool(task and all((
        str(task.get("tenant_id") or "local") == identity["t"],
        task.get("user_id") == identity["u"],
        task.get("session_id") == identity["s"],
        task.get("agent_id") == identity["a"],
        task.get("installation_id") == identity["g"],
    )))


def _receipt(task: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    scoped_prefix = _scope_key(identity) + ":"
    key = str(task.get("idempotency_key") or "")
    result = task.get("result")
    artifact_ids = []
    if isinstance(result, dict):
        candidates = result.get("artifacts")
        if isinstance(candidates, list):
            artifact_ids.extend(
                item.get("artifact_id") for item in candidates
                if isinstance(item, dict)
            )
        artifact_ids.append(result.get("artifact_id"))
    error = task.get("error")
    error_code = error.get("code") if isinstance(error, dict) else None
    return {
        "contract": "local.task.receipt/1",
        "task_id": task["task_id"],
        "capability_id": task["capability_id"],
        "idempotency_key": key[len(scoped_prefix):] if key.startswith(scoped_prefix) else None,
        "status": task["status"],
        "error_code": error_code if isinstance(error_code, str) and _TOKEN.fullmatch(error_code) else None,
        "artifact_ids": sorted({value for value in artifact_ids if isinstance(value, str) and _ARTIFACT.fullmatch(value)}),
        "result_sha256": (
            hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if result is not None else None
        ),
    }


async def prepare_local_runtime(
    *, arguments: dict[str, Any], tenant_id: str, user_id: str,
    session_id: str, agent_id: str, installation_id: str,
    release_id: str, invocation_id: str,
    granted_capabilities: tuple[str, ...] = (),
) -> dict[str, Any]:
    contract = "local.runtime.prepare/1"
    capability_id = (
        arguments.get("capability_id")
        if isinstance(arguments, dict) else None
    )
    if (
        not isinstance(arguments, dict)
        or set(arguments) not in ({"capability_id"}, {"capability_id", "device_id"})
        or not isinstance(capability_id, str) or len(capability_id) > 128
        or not _CAPABILITY.fullmatch(capability_id)
        or ("device_id" in arguments and (
            not isinstance(arguments["device_id"], str)
            or not 1 <= len(arguments["device_id"]) <= 128
        ))
    ):
        return {
            "contract": contract, "status": "invalid_request",
            "user_action": "correct_request",
        }
    if contract not in granted_capabilities:
        return {
            "contract": contract, "status": "rejected",
            "capability_id": capability_id,
            "error_code": "LOCAL_GATEWAY.CAPABILITY_NOT_AUTHORIZED",
            "user_action": "contact_administrator",
        }
    service = _service
    if service is None:
        return {
            "contract": contract, "status": "unavailable",
            "user_action": "contact_administrator",
        }
    identity = {
        "t": tenant_id, "u": user_id, "s": session_id, "a": agent_id,
        "g": installation_id, "r": release_id, "i": invocation_id,
        "n": agent_id, "c": granted_capabilities,
    }
    try:
        request = {"capability": capability_id}
        if "device_id" in arguments:
            request["device_id"] = arguments["device_id"]
        result = await service._local_runtime_prepare(
            request, identity, invocation_id,
        )
    except PublicError as exc:
        return {
            "contract": contract, "status": "rejected",
            "capability_id": capability_id, "error_code": exc.code,
            "user_action": exc.user_action,
        }
    return {
        "contract": contract, "status": result["state"],
        "capability_id": result["capability_id"],
        "package_id": result["package_id"],
        "package_version": result["package_version"],
        "min_runner_version": result["min_runner_version"],
        "device_id": result["device_id"],
        "runner_version": result["runner_version"],
        "user_action": result["user_action"],
    }


async def dispatch_local_task(
    *, capability: str, arguments: dict[str, Any],
    tenant_id: str, user_id: str, session_id: str, agent_id: str,
    installation_id: str, release_id: str, invocation_id: str,
    granted_capabilities: tuple[str, ...] = (),
) -> dict[str, Any]:
    service = _service
    if service is None:
        return {"contract": "local.task.receipt/1", "status": "unavailable"}
    identity = {
        "t": tenant_id, "u": user_id, "s": session_id, "a": agent_id,
        "g": installation_id, "r": release_id, "i": invocation_id,
        "n": agent_id,
        "c": granted_capabilities,
    }
    if capability == "local.task.start/1":
        if set(arguments) not in (
            {"capability_id", "input", "idempotency_key"},
            {"capability_id", "input", "idempotency_key", "local_file_bindings"},
        ):
            raise ValueError("invalid local task request")
        key = arguments["idempotency_key"]
        if not isinstance(key, str) or not 1 <= len(key) <= 160:
            raise ValueError("invalid local task idempotency key")
        try:
            task = await service._local_task_start(
                {**arguments, "idempotency_key": _scope_key(identity) + ":" + key},
                identity, invocation_id,
            )
        except PublicError as exc:
            return {
                "contract": "local.task.receipt/1", "status": "rejected",
                "error_code": exc.code,
            }
        stored = service.store.get_task(task["task_id"], user_id)
    elif capability in {"local.task.read/1", "local.task.cancel/1"}:
        if set(arguments) != {"task_id"} or not isinstance(arguments["task_id"], str):
            raise ValueError("invalid local task request")
        stored = service.store.get_task(arguments["task_id"], user_id)
        if not _owned(stored, identity):
            return {"contract": "local.task.receipt/1", "status": "not_found"}
        if capability == "local.task.cancel/1":
            try:
                await service._local_task_cancel(arguments, identity, invocation_id)
            except PublicError as exc:
                return {
                    "contract": "local.task.receipt/1", "status": "rejected",
                    "error_code": exc.code,
                }
            stored = service.store.get_task(arguments["task_id"], user_id)
    else:
        raise ValueError("unknown local task capability")
    if not _owned(stored, identity):
        return {"contract": "local.task.receipt/1", "status": "not_found"}
    return _receipt(stored, identity)


async def bind_localized_task_outputs(
    *, arguments: dict[str, Any], tenant_id: str, user_id: str,
    session_id: str, agent_id: str, installation_id: str,
    release_id: str, invocation_id: str,
    compatible_installation_releases: dict[str, str],
) -> dict[str, Any]:
    contract = "local.task.outputs.bind/1"
    service = _service
    if service is None:
        return {"contract": contract, "status": "unavailable"}
    if set(arguments) != {"source_task_id", "slots"}:
        return {"contract": contract, "status": "invalid_request"}
    source_task_id, slots = arguments["source_task_id"], arguments["slots"]
    if (
        not isinstance(source_task_id, str) or not 1 <= len(source_task_id) <= 160
        or not isinstance(slots, list) or not 1 <= len(slots) <= 20
        or any(not isinstance(slot, str) or not _TOKEN.fullmatch(slot) for slot in slots)
        or len(set(slots)) != len(slots)
    ):
        return {"contract": contract, "status": "invalid_request"}
    identity = {
        "t": tenant_id, "u": user_id, "s": session_id, "a": agent_id,
        "g": installation_id, "r": release_id, "i": invocation_id,
    }
    source = service.store.get_task(source_task_id, user_id)
    if not source or any((
        str(source.get("tenant_id") or "local") != tenant_id,
        source.get("user_id") != user_id,
        source.get("session_id") != session_id,
        source.get("agent_id") != agent_id,
        source.get("installation_id") not in compatible_installation_releases,
        source.get("release_id") != compatible_installation_releases.get(
            source.get("installation_id")),
    )):
        return {"contract": contract, "status": "not_found"}
    if source.get("capability_id") != "aigc.task.assets.localize/1" or source.get("status") != "succeeded":
        return {"contract": contract, "status": "source_not_ready"}
    result = source.get("result")
    original = source.get("input")
    if not isinstance(result, dict) or not isinstance(result.get("files"), list) or not isinstance(original, dict):
        return {"contract": contract, "status": "unavailable"}
    expected_assets = original.get("assets")
    files = result["files"]
    if (
        not isinstance(expected_assets, list) or len(files) != len(expected_assets)
        or any(not isinstance(item, dict) or not isinstance(item.get("slot"), str)
               for item in expected_assets)
    ):
        return {"contract": contract, "status": "unavailable"}
    by_slot: dict[str, dict[str, Any]] = {}
    for file in files:
        if (
            not isinstance(file, dict) or not isinstance(file.get("slot"), str)
            or file["slot"] in by_slot or type(file.get("order")) is not int
            or not isinstance(file.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", file["sha256"])
            or type(file.get("size_bytes")) is not int or file["size_bytes"] < 0
            or not isinstance(file.get("relative_path"), str)
            or len(file["relative_path"]) > 512
        ):
            return {"contract": contract, "status": "unavailable"}
        by_slot[file["slot"]] = file
    if {item.get("slot") for item in expected_assets} != set(by_slot):
        return {"contract": contract, "status": "unavailable"}
    for asset in expected_assets:
        file = by_slot[asset["slot"]]
        if any(file.get(field) != asset.get(field) for field in (
            "asset_id", "slot", "order", "usage",
        )):
            return {"contract": contract, "status": "unavailable"}
        relative = file["relative_path"]
        expected_root = "res/" if asset.get("destination") == "res" else ""
        if (
            asset.get("destination") not in {"res", "task_root"}
            or not relative.startswith(expected_root)
            or len(relative[len(expected_root):].split("/")) != 1
            or relative[len(expected_root):] in {"", ".", ".."}
            or "\\" in relative
        ):
            return {"contract": contract, "status": "unavailable"}
    if any(slot not in by_slot for slot in slots):
        return {"contract": contract, "status": "invalid_request"}
    selected = sorted((by_slot[slot] for slot in slots), key=lambda item: item["order"])
    try:
        bound = await service.bind_localized_outputs(identity=identity, source_task=source, files=selected)
    except PublicError as exc:
        return {"contract": contract, "status": "rejected", "error_code": exc.code}
    return {"contract": contract, **bound}


async def dispatch_aigc_asset_localization(
    *, material_task_id: str, assets: list[dict[str, Any]],
    idempotency_key: str, tenant_id: str, user_id: str, session_id: str,
    agent_id: str, agent_name: str, installation_id: str, release_id: str,
    invocation_id: str,
) -> dict[str, Any]:
    service = _service
    if service is None:
        return {"contract": "local.task.receipt/1", "status": "unavailable"}
    identity = {
        "t": tenant_id, "u": user_id, "s": session_id, "a": agent_id,
        "g": installation_id, "r": release_id, "i": invocation_id,
        "n": agent_name, "c": ("aigc.task.assets.localize/1",),
    }
    if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 160:
        raise ValueError("invalid AIGC localization idempotency key")
    scoped_key = _scope_key(identity) + ":" + idempotency_key
    try:
        task = await service._aigc_assets_localize(
            {
                "material_task_id": material_task_id,
                "assets": assets,
                "idempotency_key": scoped_key,
            },
            identity,
            invocation_id,
        )
    except PublicError as exc:
        return {
            "contract": "local.task.receipt/1",
            "status": "rejected",
            "error_code": exc.code,
        }
    stored = service.store.get_task(task["task_id"], user_id)
    if not _owned(stored, identity):
        return {"contract": "local.task.receipt/1", "status": "not_found"}
    return _receipt(stored, identity)
