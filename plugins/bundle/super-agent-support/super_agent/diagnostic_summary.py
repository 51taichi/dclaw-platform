"""Combine authorized runtime and local-task evidence by invocation ID."""

from __future__ import annotations

from typing import Any


CONTRACT = "developer.runtime.diagnostics.by-reference/6"


def _runtime_finding(runtime: dict[str, Any]) -> dict[str, Any] | None:
    if runtime["status"] != "found":
        return None
    blocker = runtime["blocker"]
    first = runtime["first_failure"]
    failed_operation = next((item for item in runtime["host_operations"]
                             if item["event"] == "host.operation.failed"), None)
    if (runtime["runtime_outcome"] == "completed" and failed_operation is None
            and blocker["error_code"] is None and first["phase"] is None):
        return None
    source = runtime["first_failure_source"]
    layer = ("platform_preflight" if source == "platform_preflight"
             else "agent" if source == "agent_trace"
             else "host" if source == "host_stage" or failed_operation else "unknown")
    code = blocker["error_code"] or (failed_operation or {}).get("error_code")
    if blocker["evidence"] == "recorded" and code not in {None, "HOST_INTERNAL_ERROR"}:
        evidence = "specific_recorded"
    elif code or first["phase"] or failed_operation:
        evidence = "first_observed_only"
    else:
        evidence = "historical_detail_not_recorded"
    return {
        "layer": layer, "task_id": None,
        "capability": (failed_operation or {}).get("capability"),
        "phase": blocker["phase"] if blocker["phase"] != "not_recorded" else first["phase"],
        "category": first["category"] or (failed_operation or {}).get("category"),
        "error_code": code,
        "field_path": blocker["field_path"] if blocker["field_path"] != "not_recorded" else None,
        "constraint": blocker["constraint"] if blocker["constraint"] != "not_recorded" else None,
        "responsibility": blocker["responsibility"],
        "recovery_action": blocker["recovery_action"],
        "evidence": evidence,
        "observed_at": runtime["ended_at"],
    }


def _local_finding(task: dict[str, Any]) -> dict[str, Any]:
    phase = task["first_failure_phase"]
    category = task["exception_category"]
    code = task["error_code"]
    if (task["phase_evidence"] == "recorded"
            and task["category_evidence"] == "recorded" and code):
        evidence = "specific_recorded"
    elif phase or category or code:
        evidence = "first_observed_only"
    else:
        evidence = "historical_detail_not_recorded"
    return {
        "layer": "helper" if task["helper_received"] else "host",
        "task_id": task["task_id"], "capability": task["capability"],
        "phase": phase, "category": category, "error_code": code,
        "field_path": None, "constraint": None,
        "responsibility": task["responsibility"],
        "recovery_action": task["recovery_action"],
        "evidence": evidence, "observed_at": task["updated_at"],
    }


def summarize_invocation(
    *, invocation_id: str, runtime: dict[str, Any],
    local_tasks: dict[str, Any] | None,
) -> dict[str, Any]:
    """Project recorded evidence; never infer a specific cause from a generic error."""
    if runtime["status"] == "no_record" and (
        local_tasks is None or local_tasks["status"] == "no_record"
    ):
        return {"contract": CONTRACT, "status": "no_record", "retention_days": 30}

    task_rows = local_tasks["tasks"] if local_tasks is not None else []
    findings = []
    runtime_finding = _runtime_finding(runtime)
    if runtime_finding is not None:
        findings.append(runtime_finding)
    findings.extend(_local_finding(task) for task in task_rows
                    if task["task_status"] == "failed")
    if len(findings) > 1:
        diagnosis_status = "multiple_failures"
    elif findings:
        diagnosis_status = findings[0]["evidence"]
    else:
        diagnosis_status = "no_failure_recorded"
    return {
        "contract": CONTRACT, "status": "found", "retention_days": 30,
        "invocation_id": invocation_id,
        "runtime_evidence": runtime["status"],
        "local_task_evidence": ("available" if local_tasks is not None
                                else "unavailable"),
        "release_id": runtime["release_id"] if runtime["status"] == "found" else None,
        "installation_id": runtime["installation_id"] if runtime["status"] == "found" else None,
        "runtime_outcome": (runtime["runtime_outcome"] if runtime["status"] == "found"
                            else "not_recorded"),
        "transaction_status": (runtime["transaction_status"] if runtime["status"] == "found"
                               else "not_recorded"),
        "task_acceptance": (runtime["task_acceptance"] if runtime["status"] == "found"
                            else "not_recorded"),
        "local_tasks": [{
            "task_id": task["task_id"], "capability": task["capability"],
            "task_status": task["task_status"], "release_id": task["release_id"],
            "installation_id": task["installation_id"],
            "host_dispatched": task["host_dispatched"],
            "helper_received": task["helper_received"],
            "helper_version": task["helper_version"],
            "first_failure_phase": task["first_failure_phase"],
            "phase_evidence": task["phase_evidence"],
            "exception_category": task["exception_category"],
            "category_evidence": task["category_evidence"],
            "error_code": task["error_code"],
            "responsibility": task["responsibility"],
            "recovery_action": task["recovery_action"],
        } for task in task_rows],
        "diagnosis_status": diagnosis_status,
        "findings": findings,
    }
