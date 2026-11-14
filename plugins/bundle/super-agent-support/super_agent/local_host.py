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
