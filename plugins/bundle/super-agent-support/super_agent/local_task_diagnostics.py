"""Owner-scoped, redacted diagnostics for plugin-owned local tasks."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable


RETENTION_DAYS = 30
_REFERENCE = re.compile(r"[0-9a-f]{32}\Z")
_CODE = re.compile(r"[A-Z][A-Z0-9_.]{0,63}\Z")
_PHASES = {
    "helper_receive", "download_prepare", "download_transfer", "manifest_write",
    "completion_event", "file_binding", "input_write", "capability_prepare",
    "capability_execute", "resource_limit", "result_registration", "host_dispatch",
}
_CATEGORIES = {
    "json_lifetime", "invalid_input", "network_failure", "asset_validation",
    "file_io", "helper_internal", "file_binding", "capability_execution",
    "resource_limit",
}
_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){1,3}\Z")


def sanitize_localize_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Keep only fixed diagnostic tokens before persisting Helper events."""
    version = payload.get("helper_version")
    version = version if isinstance(version, str) and _VERSION.fullmatch(version) else None
    if event_type == "started":
        return {"helper_version": version}
    if event_type != "failed":
        return payload
    code = payload.get("code")
    phase = payload.get("phase")
    category = payload.get("category")
    return {
        "code": code if isinstance(code, str) and code in {
            "HELPER_JSON_LIFETIME_ERROR", "AIGC_LOCALIZE_INVALID_INPUT",
            "AIGC_ASSET_DOWNLOAD_FAILED",
        } else "AIGC_ASSET_DOWNLOAD_FAILED",
        "phase": phase if isinstance(phase, str) and phase in _PHASES else None,
        "category": category if isinstance(category, str) and category in _CATEGORIES else None,
        "helper_version": version,
    }


def _at(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _failure(error: Any) -> tuple[str | None, str | None, str | None]:
    if not isinstance(error, dict):
        return None, None, None
    code = error.get("code")
    phase = error.get("phase")
    category = error.get("category")
    return (
        code if isinstance(code, str) and _CODE.fullmatch(code) else None,
        phase if isinstance(phase, str) and phase in _PHASES else None,
        category if isinstance(category, str) and category in _CATEGORIES else None,
    )


def _responsibility(category: str | None, code: str | None = None) -> tuple[str, str]:
    if category == "file_binding" and code in {
        "LOCAL_FILE_REF.FILE_MISSING", "LOCAL_FILE_REF.FILE_CHANGED",
        "LOCAL_FILE_REF.EXPIRED", "LOCAL_FILE_REF.REVOKED",
    }:
        return "environment", "rebind_files"
    return {
        "json_lifetime": ("platform", "upgrade_helper"),
        "invalid_input": ("platform", "contact_platform_with_task_id"),
        "network_failure": ("environment", "check_asset_access"),
        "asset_validation": ("environment", "check_asset_integrity"),
        "file_io": ("environment", "check_local_storage"),
        "helper_internal": ("platform", "contact_platform_with_task_id"),
    }.get(category, ("undetermined", "contact_platform_with_task_id"))


def read_local_task_diagnostics(
    *, agent_id: str, tenant_id: str, reference: str, reference_type: str,
    grants: Any, owner_resolver: Callable[[str], dict[str, Any] | None],
    task_lookup: Callable[..., list[dict[str, Any]] | None],
    device_lookup: Callable[[str, str], dict[str, Any] | None],
    now: int | None = None,
    include_all_capabilities: bool = False,
) -> dict[str, Any]:
    """Return only task and Helper evidence from the authorized expert's sessions."""
    if reference_type not in {"task", "invocation"} or not _REFERENCE.fullmatch(reference):
        raise ValueError("invalid local diagnostic reference")
    current = int(time.time()) if now is None else now
    response = {
        "contract": ("developer.local-task.diagnostics.read/2"
                     if include_all_capabilities else "developer.local-task.diagnostics.read/1"),
        "status": "no_record",
        "retention_days": RETENTION_DAYS,
        "tasks": [],
    }
    records = task_lookup(
        tenant_id=tenant_id, agent_id=agent_id, reference=reference,
        reference_type=reference_type, cutoff=current - RETENTION_DAYS * 86400,
    )
    if records is None:
        raise RuntimeError("local task diagnostics unavailable")
    allowed = {
        (grant.installation_id, grant.release_id)
        for grant in grants.list_grants()
        if grant.tenant_id == tenant_id and grant.agent_id == agent_id
    }
    for record in records:
        if (
            (not include_all_capabilities
             and record["capability_id"] != "aigc.task.assets.localize/1")
            or (record["installation_id"], record["release_id"]) not in allowed
        ):
            continue
        owner = owner_resolver(record["session_id"])
        if not owner or any((
            owner.get("tenant_id") != tenant_id,
            owner.get("agent_id") != agent_id,
            str(owner.get("user_id")) != record["user_id"],
        )):
            continue
        events = record["events"]
        started = next((item for item in events if item["event_type"] == "started"), None)
        failed = next((item for item in events if item["event_type"] == "failed"), None)
        payload = json.loads(failed["payload_json"]) if failed else None
        code, phase, category = _failure(payload)
        if (include_all_capabilities and category is None
                and code == "RUNNER.EXECUTION_FAILED"
                and payload.get("message") == "ObjectDisposedException"):
            category = "json_lifetime"
        if code is None and record["error_json"]:
            code, error_phase, error_category = _failure(json.loads(record["error_json"]))
            if include_all_capabilities:
                phase = phase or error_phase
                category = category or error_category
        version = None
        for event in (started, failed):
            if event is None:
                continue
            value = json.loads(event["payload_json"]).get("helper_version")
            if isinstance(value, str) and _VERSION.fullmatch(value):
                version = value
                break
        device = device_lookup(record["user_id"], record["device_id"])
        responsibility, recovery = _responsibility(category, code)
        evidence = "recorded" if phase and category else "historical_detail_not_recorded"
        if code == "LOCAL_GATEWAY.DEVICE_NOT_READY" and not failed:
            phase, responsibility, recovery = "host_dispatch", "environment", "reconnect_helper"
            evidence = "recorded"
        elif record["status"] != "failed" and code is None:
            recovery, evidence = "none", "not_applicable"
        item = {
            "task_id": record["task_id"],
            "invocation_id": record["invocation_id"],
            "release_id": record["release_id"],
            "installation_id": record["installation_id"],
            "capability": record["capability_id"],
            "host_accepted": True,
            "host_dispatched": (True if record["dispatched_at"] is not None or started or failed else None),
            "helper_received": bool(started or failed) if record["dispatched_at"] is not None else (True if started or failed else None),
            "helper_version": version,
            "helper_version_evidence": "recorded" if version else "historical_detail_not_recorded",
            "device_online_now": device["online"] if device is not None else None,
            "task_status": record["status"],
            "first_failure_phase": phase,
            "error_code": code,
            "exception_category": category,
            "failure_evidence": evidence,
            "responsibility": responsibility,
            "recovery_action": recovery,
            "accepted_at": _at(record["created_at"]),
            "helper_started_at": _at(started["created_at"]) if started else None,
            "updated_at": _at(record["updated_at"]),
        }
        if include_all_capabilities:
            item["phase_evidence"] = (
                "recorded" if phase else "historical_detail_not_recorded"
                if record["status"] == "failed" else "not_applicable"
            )
            item["category_evidence"] = (
                "recorded" if category else "historical_detail_not_recorded"
                if record["status"] == "failed" else "not_applicable"
            )
        response["tasks"].append(item)
    if response["tasks"]:
        response["status"] = "found"
    return response


def read_local_task_diagnostics_v2(**kwargs: Any) -> dict[str, Any]:
    return read_local_task_diagnostics(**kwargs, include_all_capabilities=True)
