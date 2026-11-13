"""Owner-scoped projection of prior workspace failures."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from .interaction_cards import InteractionError
from .interaction_contract import InteractionValidationError


READ_CONTRACT = "runtime.failure.read/1"
READ_WINDOW = timedelta(days=30)
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_FIELD_PATH = re.compile(r"[A-Za-z][A-Za-z0-9_.\[\]-]{0,127}\Z")
_CAPABILITY_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}/[0-9]{1,3}\Z")
_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_.]{0,63}\Z")
_INTERACTION_FIELDS = frozenset({
    "request", "task_key", "interaction_revision", "component_type", "card",
    "input_policy", "replaces_interaction_id", "expires_at", "title",
    "description", "options", "supplement", "layout", "id", "text",
    "recommended", "default_selected", "action_url", "auto_submit_on_desktop",
    "enabled", "label", "placeholder", "required", "max_length",
    "min_selections", "max_selections", "items", "question", "button_label",
    "accept_mime_types", "accept_extensions", "multiple", "min_files",
    "max_files", "max_file_size_bytes", "max_total_size_bytes",
    "selected", "answers",
})
_CONSTRAINTS = {
    "missing": "FIELD_REQUIRED", "extra_forbidden": "EXTRA_FIELD",
    "string_type": "STRING_REQUIRED", "int_type": "INTEGER_REQUIRED",
    "greater_than": "OUT_OF_RANGE", "greater_than_equal": "OUT_OF_RANGE",
    "less_than": "OUT_OF_RANGE", "less_than_equal": "OUT_OF_RANGE",
    "string_too_short": "TOO_SHORT", "string_too_long": "TOO_LONG",
    "too_short": "TOO_SHORT", "too_long": "TOO_LONG",
    "literal_error": "INVALID_VALUE", "enum": "INVALID_VALUE",
}


class FailureDiagnosticsUnauthorized(ValueError):
    pass


class FailureDiagnosticsUnavailable(ValueError):
    pass


def _safe_interaction_field(value: Any) -> str:
    if (
        isinstance(value, str) and _FIELD_PATH.fullmatch(value)
        and all(part in _INTERACTION_FIELDS for part in re.findall(r"[A-Za-z][A-Za-z0-9_]*", value))
    ):
        return value
    return "not_recorded"


def classify_interaction_failure(exc: Exception, capability: str) -> dict[str, str]:
    """Capture only stable contract metadata; never serialize exception text or input."""
    result = {
        "error_code": "HOST_INTERNAL_ERROR",
        "field_path": "not_recorded",
        "constraint": "not_recorded",
        "recovery_action": "contact_platform_with_invocation_id",
        "contract": capability,
    }
    source = exc
    if not isinstance(source, (InteractionError, InteractionValidationError, ValidationError)):
        source = exc.__cause__ if isinstance(exc.__cause__, ValidationError) else exc
    if isinstance(source, InteractionError):
        result["error_code"] = source.code if _ERROR_CODE.fullmatch(source.code) else "INTERACTION_REJECTED"
        result["field_path"] = _safe_interaction_field(source.field)
        result["constraint"] = result["error_code"]
        result["recovery_action"] = (
            "correct_request" if result["error_code"].startswith("INVALID_") else
            "correct_request_or_resolve_conflict" if "CONFLICT" in result["error_code"]
            or result["error_code"] == "ACTIVE_BLOCKING_INTERACTION_EXISTS" else
            "retry_same_idempotency_key" if source.retryable else
            "contact_platform_with_invocation_id"
        )
    elif isinstance(source, InteractionValidationError):
        result["error_code"] = source.code if _ERROR_CODE.fullmatch(source.code) else "INVALID_INTERACTION_REQUEST"
        issue = source.issues[0] if source.issues else {}
        field = issue.get("field")
        constraint = issue.get("code")
        result["field_path"] = _safe_interaction_field(field)
        result["constraint"] = constraint if isinstance(constraint, str) and _ERROR_CODE.fullmatch(constraint) else "INVALID_VALUE"
        result["recovery_action"] = "correct_request"
    elif isinstance(source, ValidationError):
        result["error_code"] = "INVALID_INTERACTION_REQUEST"
        issue = source.errors(include_url=False, include_context=False, include_input=False)[0]
        parts = issue.get("loc", ())
        field = "".join(
            f"[{part}]" if isinstance(part, int) else ("." if index else "") + part
            for index, part in enumerate(parts) if isinstance(part, (int, str))
        )
        result["field_path"] = _safe_interaction_field(field)
        result["constraint"] = _CONSTRAINTS.get(issue.get("type"), "INVALID_VALUE")
        result["recovery_action"] = "correct_request"
    return result


def _scope(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _token(value: Any) -> str | None:
    return value if isinstance(value, str) and _TOKEN.fullmatch(value) else None


def _timestamp(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is not None:
            return result.astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass
    raise FailureDiagnosticsUnavailable("invalid failure trace timestamp")


def _trace_failure(
    path: Path, installation_id: str, session_id: str, *,
    include_completed: bool = False,
) -> list[dict[str, Any]]:
    if path.is_symlink() or path.parent.is_symlink() or path.parent.parent.is_symlink():
        raise FailureDiagnosticsUnavailable("unsafe failure trace")
    if not path.exists():
        return []
    if not path.is_file():
        raise FailureDiagnosticsUnavailable("unsafe failure trace")
    invocations: dict[str, dict[str, Any]] = {}
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                if (
                    not isinstance(record, dict)
                    or record.get("installation_id") != installation_id
                    or record.get("session_id") != session_id
                    or not isinstance(record.get("invocation_id"), str)
                ):
                    raise FailureDiagnosticsUnavailable("failure trace scope mismatch")
                event = record.get("event_type")
                if event not in {
                    "orchestration.started", "runtime.trace", "orchestration.failed",
                    "orchestration.completed", "host.operation.started",
                    "host.operation.completed", "host.operation.failed",
                    "orchestration.preflight_failed", "orchestration.message_staged",
                    "agent.execute.safe_started", "agent.execute.safe_completed",
                    "agent.execute.safe_failed",
                    "interaction.operation.started", "interaction.operation.completed",
                    "interaction.operation.failed", "interaction.tool.invoked",
                    "interaction.tool.rejected",
                }:
                    continue
                invocation = invocations.setdefault(record["invocation_id"], {})
                when = _timestamp(record.get("timestamp"))
                payload = record.get("payload") or {}
                stage_name = event
                if event == "runtime.trace":
                    source = "host" if payload.get("origin") == "host" else "agent"
                    stage_name = _token((payload.get("payload") or {}).get("event"))
                    payload = payload.get("payload") or {}
                else:
                    source = "host"
                if stage_name:
                    duration = payload.get("duration_ms")
                    call_number = payload.get("call_number")
                    text_length = payload.get("text_length")
                    stage = {
                        "event": stage_name,
                        "source": source,
                        "at": when.isoformat(),
                        "duration_ms": (
                            duration if type(duration) is int and 0 <= duration <= 900_000
                            else None
                        ),
                    }
                    if type(call_number) is int and 1 <= call_number <= 100:
                        stage["call_number"] = call_number
                    if type(payload.get("has_text")) is bool:
                        stage["has_text"] = payload["has_text"]
                    if type(text_length) is int and 0 <= text_length <= 1_000_000:
                        stage["text_length"] = text_length
                    if type(payload.get("complete_json_object")) is bool:
                        stage["complete_json_object"] = payload["complete_json_object"]
                    if _token(payload.get("execution_mode")):
                        stage["execution_mode"] = payload["execution_mode"]
                    if _token(payload.get("response_format")):
                        stage["response_format"] = payload["response_format"]
                    invocation.setdefault("stages", []).append(stage)
                    extended_stage = dict(stage)
                    if isinstance(payload.get("capability"), str) and _CAPABILITY_ID.fullmatch(payload["capability"]):
                        extended_stage["capability"] = payload["capability"]
                    if _token(payload.get("category")):
                        extended_stage["category"] = payload["category"]
                    if isinstance(payload.get("field_path"), str) and _FIELD_PATH.fullmatch(payload["field_path"]):
                        extended_stage["field_path"] = payload["field_path"]
                    if _token(payload.get("constraint")):
                        extended_stage["constraint"] = payload["constraint"]
                    invocation.setdefault("stages_v2", []).append(extended_stage)
                if event == "orchestration.started":
                    invocation["started_at"] = when
                elif event == "orchestration.message_staged":
                    invocation["assistant_message_id"] = _token(
                        payload.get("assistant_message_id"),
                    )
                elif event == "orchestration.preflight_failed":
                    invocation["started_at"] = _timestamp(payload.get("started_at"))
                    invocation["failed_at"] = when
                    invocation["error_code"] = _token(payload.get("error_code"))
                    invocation["first_failure"] = {
                        "phase": _token(payload.get("phase")),
                        "category": _token(payload.get("category")),
                        "attempt": None,
                    }
                    invocation["first_failure_source"] = "platform_preflight"
                    invocation.setdefault("failure_events", []).append({
                        "phase": _token(payload.get("phase")) or "not_recorded",
                        "category": _token(payload.get("category")) or "not_recorded",
                        "attempt": None, "source": "platform_preflight", "at": when.isoformat(),
                        "status_code": None, "provider_code": None,
                        "provider_param": None,
                    })
                elif event == "orchestration.failed":
                    invocation["failed_at"] = when
                    invocation["error_code"] = _token(payload.get("error_code"))
                elif event == "orchestration.completed":
                    invocation["completed_at"] = when
                elif event in {"host.operation.started", "host.operation.completed", "host.operation.failed"}:
                    operation = {
                        "event": event,
                        "at": when.isoformat(),
                        "capability": payload.get("capability") if isinstance(payload.get("capability"), str) and _CAPABILITY_ID.fullmatch(payload["capability"]) else "not_recorded",
                    }
                    if event != "host.operation.started":
                        operation["category"] = _token(payload.get("category"))
                        operation["error_code"] = _token(payload.get("error_code"))
                        operation["status"] = _token(payload.get("status"))
                        operation["task_accepted"] = payload.get("task_accepted") if type(payload.get("task_accepted")) is bool else None
                        duration = payload.get("duration_ms")
                        operation["duration_ms"] = duration if type(duration) is int and 0 <= duration <= 900_000 else None
                    invocation.setdefault("host_operations", []).append(operation)
                    if event == "host.operation.failed":
                        detail = {
                            "host_stage": _token(payload.get("host_stage")),
                            "error_code": _token(payload.get("error_code")),
                            "field_path": _safe_interaction_field(payload.get("field_path"))
                            if isinstance(payload.get("capability"), str)
                            and payload["capability"].startswith("interaction.")
                            else payload.get("field_path") if payload.get("field_path") in {
                                "request", "assets", "idempotency_key",
                            } else "not_recorded",
                            "constraint": _token(payload.get("constraint")),
                            "responsibility": payload.get("responsibility")
                            if payload.get("responsibility") in {"developer", "platform", "environment"}
                            else None,
                            "recovery_action": _token(payload.get("recovery_action")),
                        }
                        invocation.setdefault("host_failure_details", []).append(detail)
                        if "first_failure" not in invocation:
                            invocation["first_failure"] = {
                                "phase": detail["host_stage"] or "host_operation",
                                "category": operation.get("category"), "attempt": None,
                            }
                            invocation["first_failure_source"] = "host_stage"
                elif event == "runtime.trace":
                    trace = payload
                    if trace.get("event") == "agent.turn.failure":
                        attempt = trace.get("attempt")
                        invocation.setdefault("failure_events", []).append({
                            "phase": _token(trace.get("phase")) or "not_recorded",
                            "category": _token(trace.get("category")) or "not_recorded",
                            "attempt": attempt if type(attempt) is int and 0 <= attempt <= 100 else None,
                            "source": "agent",
                            "at": when.isoformat(),
                            "status_code": None,
                            "provider_code": None,
                            "provider_param": None,
                        })
                    if trace.get("event") == "agent.turn.failure" and "first_failure" not in invocation:
                        attempt = trace.get("attempt")
                        invocation["first_failure"] = {
                            "phase": _token(trace.get("phase")),
                            "category": _token(trace.get("category")),
                            "attempt": attempt if type(attempt) is int and 0 <= attempt <= 100 else None,
                        }
                elif event == "agent.execute.safe_failed":
                    attempt = payload.get("call_number")
                    failure = {
                        "phase": "agent_execute",
                        "category": _token(payload.get("category")) or "not_recorded",
                        "attempt": attempt if type(attempt) is int and 1 <= attempt <= 100 else None,
                        "source": "host",
                        "at": when.isoformat(),
                        "status_code": payload.get("status_code") if type(payload.get("status_code")) is int and 400 <= payload["status_code"] <= 599 else None,
                        "provider_code": _token(payload.get("provider_code")),
                        "provider_param": _token(payload.get("provider_param")),
                    }
                    invocation.setdefault("failure_events", []).append(failure)
                    if "first_failure" not in invocation:
                        invocation["first_failure"] = {
                            "phase": failure["phase"], "category": failure["category"],
                            "attempt": failure["attempt"],
                        }
                        invocation["first_failure_source"] = "host_stage"
                elif event == "interaction.operation.failed":
                    invocation.setdefault("failure_events", []).append({
                        "phase": "interaction_operation",
                        "category": _token(payload.get("category")) or "not_recorded",
                        "attempt": None, "source": "host", "at": when.isoformat(),
                        "status_code": None, "provider_code": None,
                        "provider_param": None,
                        "contract": payload.get("capability") if isinstance(payload.get("capability"), str) and _CAPABILITY_ID.fullmatch(payload["capability"]) else None,
                    })
                    detail = {key: _token(payload.get(key)) for key in (
                        "error_code", "constraint", "recovery_action",
                    )}
                    detail["field_path"] = (
                        _safe_interaction_field(payload.get("field_path"))
                    )
                    detail["contract"] = (
                        payload["contract"] if isinstance(payload.get("contract"), str)
                        and _CAPABILITY_ID.fullmatch(payload["contract"]) else None
                    )
                    invocation.setdefault("host_failure_details", []).append(detail)
                elif event == "interaction.tool.rejected":
                    invocation.setdefault("failure_events", []).append({
                        "phase": "interaction_tool_validation",
                        "category": _token(payload.get("category")) or "not_recorded",
                        "attempt": None, "source": "host", "at": when.isoformat(),
                        "status_code": None, "provider_code": None,
                        "provider_param": None,
                        "field_path": payload.get("field_path") if isinstance(payload.get("field_path"), str) and _FIELD_PATH.fullmatch(payload["field_path"]) else None,
                        "constraint": _token(payload.get("constraint")),
                        "contract": payload.get("capability") if isinstance(payload.get("capability"), str) and _CAPABILITY_ID.fullmatch(payload["capability"]) else None,
                    })
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError) as exc:
        raise FailureDiagnosticsUnavailable("failure trace cannot be read") from exc
    return [
        {"invocation_id": invocation_id, "session_id": session_id, **value}
        for invocation_id, value in invocations.items()
        if "failed_at" in value or (include_completed and "completed_at" in value)
    ]


def read_invocation_failure(
    *, storage_root: Path, installation_id: str, session_id: str,
    invocation_id: str,
) -> dict[str, Any] | None:
    path = Path(storage_root) / "traces" / _scope(installation_id) / f"{_scope(session_id)}.ndjson"
    return next(
        (
            failure for failure in _trace_failure(path, installation_id, session_id)
            if failure["invocation_id"] == invocation_id
        ),
        None,
    )


def read_latest_failure(
    *,
    storage_root: Path,
    grants: Any,
    installation_id: str,
    release_id: str,
    agent_id: str,
    user_id: str,
    session_id: str,
    owner_resolver: Callable[[str], dict[str, Any] | None],
    exclude_invocation_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read only the latest sanitized failure for the trusted task owner."""
    current = grants.get(installation_id)
    owner = owner_resolver(session_id)
    if (
        current is None
        or current.release_id != release_id
        or current.agent_id != agent_id
        or owner is None
        or str(owner.get("user_id")) != user_id
        or owner.get("agent_id") != agent_id
        or owner.get("tenant_id") != current.tenant_id
    ):
        raise FailureDiagnosticsUnauthorized("failure diagnostic scope denied")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = now - READ_WINDOW
    candidates = []
    for grant in grants.list_grants():
        if grant.tenant_id != current.tenant_id or grant.agent_id != agent_id:
            continue
        path = Path(storage_root) / "traces" / _scope(grant.installation_id) / f"{_scope(session_id)}.ndjson"
        for failure in _trace_failure(path, grant.installation_id, session_id):
            when = failure["failed_at"]
            if (
                failure["invocation_id"] != exclude_invocation_id
                and cutoff <= when <= now
            ):
                candidates.append((when, grant, failure))
    if not candidates:
        return {"contract": READ_CONTRACT, "status": "no_record", "reason": "no_failure_in_retention_window"}
    _, grant, failure = max(candidates, key=lambda item: item[0])
    first_failure = failure.get("first_failure")
    return {
        "contract": READ_CONTRACT,
        "status": "found",
        "invocation_id": failure["invocation_id"],
        "installation_id": grant.installation_id,
        "release_id": grant.release_id,
        "started_at": failure.get("started_at").isoformat() if failure.get("started_at") else None,
        "failed_at": failure["failed_at"].isoformat(),
        "first_failure": first_failure or {"phase": None, "category": None, "attempt": None},
        "first_failure_source": failure.get("first_failure_source") or (
            "agent_trace" if first_failure else "not_recorded"
        ),
        "error_code": failure.get("error_code"),
        "transaction_status": "discarded",
    }


def read_owner_failures(
    *,
    storage_root: Path,
    grants: Any,
    agent_id: str,
    user_id: str,
    session_id: str,
    owner_resolver: Callable[[str], dict[str, Any] | None],
    now: datetime | None = None,
    limit: int = 50,
    persisted_message_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Developer-facing history, scoped to the authenticated chat owner."""
    owner = owner_resolver(session_id)
    if (
        owner is None
        or str(owner.get("user_id")) != user_id
        or owner.get("agent_id") != agent_id
        or not owner.get("tenant_id")
    ):
        raise FailureDiagnosticsUnauthorized("failure diagnostic scope denied")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = now - READ_WINDOW
    candidates = []
    for grant in grants.list_grants():
        if grant.tenant_id != owner["tenant_id"] or grant.agent_id != agent_id:
            continue
        path = Path(storage_root) / "traces" / _scope(grant.installation_id) / f"{_scope(session_id)}.ndjson"
        for failure in _trace_failure(path, grant.installation_id, session_id):
            when = failure["failed_at"]
            if cutoff <= when <= now:
                first = failure.get("first_failure")
                message_id = failure.get("assistant_message_id")
                candidates.append({
                    "invocation_id": failure["invocation_id"],
                    "installation_id": grant.installation_id,
                    "release_id": grant.release_id,
                    "started_at": failure.get("started_at").isoformat() if failure.get("started_at") else None,
                    "failed_at": when.isoformat(),
                    "first_failure": first or {"phase": None, "category": None, "attempt": None},
                    "first_failure_source": failure.get("first_failure_source") or (
                        "agent_trace" if first else "not_recorded"
                    ),
                    "error_code": failure.get("error_code"),
                    "transaction_status": "discarded",
                    "stages": failure.get("stages", [])[:100],
                    "message_status": (
                        "unknown" if message_id is None or persisted_message_ids is None
                        else "persisted" if message_id in persisted_message_ids
                        else "missing"
                    ),
                })
    candidates.sort(key=lambda item: item["failed_at"], reverse=True)
    return {
        "contract": "developer.runtime.diagnostics.read/1",
        "status": "found" if candidates else "no_record",
        "retention_days": READ_WINDOW.days,
        "failures": candidates[:limit],
    }


def read_developer_failure_by_reference(
    *,
    storage_root: Path,
    grants: Any,
    agent_id: str,
    tenant_id: str,
    invocation_id: str,
    owner_resolver: Callable[[str], dict[str, Any] | None],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resolve a customer-visible ID only inside one developer-owned expert."""
    if re.fullmatch(r"(?:[0-9a-f]{32}|preflight-[0-9a-f]{32})", invocation_id) is None:
        raise FailureDiagnosticsUnauthorized("invalid diagnostic reference")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current - READ_WINDOW
    matches: list[tuple[Any, str, dict[str, Any]]] = []
    inspected = 0
    for grant in grants.list_grants():
        if grant.tenant_id != tenant_id or grant.agent_id != agent_id:
            continue
        directory = Path(storage_root) / "traces" / _scope(grant.installation_id)
        if directory.is_symlink():
            raise FailureDiagnosticsUnavailable("unsafe failure trace directory")
        if not directory.exists():
            continue
        for path in directory.glob("*.ndjson"):
            inspected += 1
            if inspected > 5000:
                raise FailureDiagnosticsUnavailable("failure trace search limit exceeded")
            if path.is_symlink() or not path.is_file():
                raise FailureDiagnosticsUnavailable("unsafe failure trace")
            try:
                if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff:
                    continue
                matching_row = None
                with path.open(encoding="utf-8") as stream:
                    for line in stream:
                        if invocation_id not in line:
                            continue
                        candidate = json.loads(line)
                        if not isinstance(candidate, dict):
                            raise FailureDiagnosticsUnavailable("failure trace cannot be read")
                        if candidate.get("invocation_id") == invocation_id:
                            matching_row = candidate
                            break
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise FailureDiagnosticsUnavailable("failure trace cannot be read") from exc
            if not isinstance(matching_row, dict) or matching_row.get("invocation_id") != invocation_id:
                continue
            session_id = matching_row.get("session_id")
            if (
                not isinstance(session_id, str)
                or matching_row.get("installation_id") != grant.installation_id
                or path.name != f"{_scope(session_id)}.ndjson"
            ):
                raise FailureDiagnosticsUnavailable("failure trace scope mismatch")
            owner = owner_resolver(session_id)
            if (
                owner is None
                or owner.get("tenant_id") != tenant_id
                or owner.get("agent_id") != agent_id
            ):
                raise FailureDiagnosticsUnauthorized("failure diagnostic scope denied")
            failure = read_invocation_failure(
                storage_root=storage_root,
                installation_id=grant.installation_id,
                session_id=session_id,
                invocation_id=invocation_id,
            )
            if failure is not None and cutoff <= failure["failed_at"] <= current:
                matches.append((grant, session_id, failure))
    if not matches:
        return {
            "contract": "developer.runtime.diagnostics.by-reference/1",
            "status": "no_record",
            "retention_days": READ_WINDOW.days,
        }
    if len(matches) != 1:
        raise FailureDiagnosticsUnavailable("diagnostic reference is ambiguous")
    grant, session_id, failure = matches[0]
    first = failure.get("first_failure")
    return {
        "contract": "developer.runtime.diagnostics.by-reference/1",
        "status": "found",
        "retention_days": READ_WINDOW.days,
        "task_id": session_id,
        "invocation_id": invocation_id,
        "installation_id": grant.installation_id,
        "release_id": grant.release_id,
        "started_at": failure.get("started_at").isoformat() if failure.get("started_at") else None,
        "failed_at": failure["failed_at"].isoformat(),
        "first_failure": first or {"phase": None, "category": None, "attempt": None},
        "first_failure_source": failure.get("first_failure_source") or (
            "agent_trace" if first else "not_recorded"
        ),
        "error_code": failure.get("error_code"),
        "transaction_status": "discarded",
        "stages": failure.get("stages", [])[:100],
    }


def read_developer_failure_by_reference_v2(**kwargs: Any) -> dict[str, Any]:
    """Expose the final recorded blocker separately from recoverable failures."""
    prior = read_developer_failure_by_reference(**kwargs)
    result = {**prior, "contract": "developer.runtime.diagnostics.by-reference/2"}
    if prior["status"] == "no_record":
        return result
    failure = read_invocation_failure(
        storage_root=kwargs["storage_root"],
        installation_id=prior["installation_id"],
        session_id=prior["task_id"],
        invocation_id=prior["invocation_id"],
    )
    if failure is None:
        raise FailureDiagnosticsUnavailable("diagnostic reference disappeared")
    events = list(failure.get("failure_events", []))[-50:]
    stages = failure.get("stages", [])
    result["stages"] = failure.get("stages_v2", [])[:100]
    last_success_at = max(
        (stage["at"] for stage in stages if stage["event"] == "agent.execute.safe_completed"),
        default="",
    )
    unresolved = [event for event in events if event["at"] >= last_success_at]
    terminal = next((
        event for event in reversed(unresolved)
        if event["phase"] in {"agent_execute", "interaction_operation"}
    ), None)
    if terminal is None and unresolved:
        terminal = unresolved[-1]
    for event in events:
        event["outcome"] = (
            "recovered" if event["at"] < last_success_at
            else "terminal" if event is terminal
            else "not_recorded"
        )
    if terminal is None:
        blocker = {"status": "not_recorded", "phase": "not_recorded", "category": "not_recorded",
                   "attempt": None, "responsibility": "not_recorded", "reason": "not_recorded"}
    else:
        provider_rejection = terminal["status_code"] is not None or terminal["category"] in {
            "BadRequestError", "AuthenticationError", "PermissionDeniedError",
            "RateLimitError", "UnprocessableEntityError", "APIStatusError",
        }
        responsibility = (
            "model_provider" if provider_rejection
            else "platform_preflight" if terminal["source"] == "platform_preflight"
            else "request_validation" if terminal["phase"] == "interaction_tool_validation"
            else "agent" if terminal["source"] == "agent"
            else "host_or_tool"
        )
        reason = (
            "provider_rejected_request" if provider_rejection
            else "preflight_rejected" if terminal["source"] == "platform_preflight"
            else "request_rejected" if terminal["phase"] == "interaction_tool_validation"
            else "agent_reported_failure" if terminal["source"] == "agent"
            else "host_call_failed"
        )
        blocker = {
            "status": "recorded", "phase": terminal["phase"],
            "category": terminal["category"], "attempt": terminal["attempt"],
            "responsibility": responsibility, "reason": reason,
        }
        if terminal.get("field_path"):
            blocker["field_path"] = terminal["field_path"]
        if terminal.get("constraint"):
            blocker["constraint"] = terminal["constraint"]
        if terminal.get("contract"):
            blocker["contract"] = terminal["contract"]
    result["failure_events"] = events
    result["final_blocker"] = blocker
    result["unrecorded_fields"] = (
        [field for field in ("provider_code", "provider_param") if terminal.get(field) is None]
        if terminal is not None and blocker["responsibility"] == "model_provider" else []
    )
    return result


def read_developer_failure_by_reference_v3(**kwargs: Any) -> dict[str, Any]:
    """Return a stable Host rejection detail without changing the v2 envelope."""
    prior = read_developer_failure_by_reference_v2(**kwargs)
    result = {"contract": "developer.runtime.diagnostics.by-reference/3",
              "status": prior["status"], "retention_days": READ_WINDOW.days}
    if prior["status"] == "no_record":
        return result
    failure = read_invocation_failure(
        storage_root=kwargs["storage_root"],
        installation_id=prior["installation_id"],
        session_id=prior["task_id"], invocation_id=prior["invocation_id"],
    )
    if failure is None:
        raise FailureDiagnosticsUnavailable("diagnostic reference disappeared")
    blocker = prior["final_blocker"]
    details = failure.get("host_failure_details", [])
    detail = details[-1] if details and blocker["phase"] == "interaction_operation" else None
    result.update({key: prior[key] for key in (
        "task_id", "invocation_id", "installation_id", "release_id",
        "started_at", "failed_at", "transaction_status", "final_blocker",
    )})
    result["host_failure_detail"] = {
        "status": (
            "recorded" if detail and detail.get("error_code") else
            "not_recorded" if blocker["phase"] == "interaction_operation" else
            "not_applicable"
        ),
        **{key: detail.get(key) if detail else None for key in (
            "error_code", "field_path", "constraint", "recovery_action", "contract",
        )},
    }
    return result


def read_developer_invocation_by_reference_v4(
    *, storage_root: Path, grants: Any, agent_id: str, tenant_id: str,
    invocation_id: str,
    owner_resolver: Callable[[str], dict[str, Any] | None],
    task_lookup: Callable[..., list[dict[str, Any]] | None] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read a redacted Host timeline, including business-blocked committed turns."""
    if re.fullmatch(r"(?:[0-9a-f]{32}|preflight-[0-9a-f]{32})", invocation_id) is None:
        raise FailureDiagnosticsUnauthorized("invalid diagnostic reference")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current - READ_WINDOW
    matches = []
    inspected = 0
    for grant in grants.list_grants():
        if grant.tenant_id != tenant_id or grant.agent_id != agent_id:
            continue
        directory = Path(storage_root) / "traces" / _scope(grant.installation_id)
        if directory.is_symlink():
            raise FailureDiagnosticsUnavailable("unsafe diagnostic directory")
        if not directory.exists():
            continue
        for path in directory.glob("*.ndjson"):
            inspected += 1
            if inspected > 5000:
                raise FailureDiagnosticsUnavailable("diagnostic search limit exceeded")
            if path.is_symlink() or not path.is_file():
                raise FailureDiagnosticsUnavailable("unsafe diagnostic trace")
            try:
                if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff:
                    continue
                session_id = None
                with path.open(encoding="utf-8") as stream:
                    for line in stream:
                        if invocation_id not in line:
                            continue
                        row = json.loads(line)
                        if isinstance(row, dict) and row.get("invocation_id") == invocation_id:
                            session_id = row.get("session_id")
                            if (not isinstance(session_id, str)
                                    or row.get("installation_id") != grant.installation_id
                                    or path.name != f"{_scope(session_id)}.ndjson"):
                                raise FailureDiagnosticsUnavailable("diagnostic trace scope mismatch")
                            break
                if session_id is None:
                    continue
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise FailureDiagnosticsUnavailable("diagnostic trace cannot be read") from exc
            records = _trace_failure(
                path, grant.installation_id, session_id,
                include_completed=True,
            )
            for record in records:
                if record["invocation_id"] != invocation_id:
                    continue
                session_id = record["session_id"]
                owner = owner_resolver(session_id)
                if owner is None or owner.get("tenant_id") != tenant_id or owner.get("agent_id") != agent_id:
                    raise FailureDiagnosticsUnauthorized("diagnostic scope denied")
                ended_at = record.get("failed_at") or record.get("completed_at")
                if cutoff <= ended_at <= current:
                    matches.append((grant, session_id, record))
    if not matches:
        return {"contract": "developer.runtime.diagnostics.by-reference/4",
                "status": "no_record", "retention_days": READ_WINDOW.days}
    if len(matches) != 1:
        raise FailureDiagnosticsUnavailable("diagnostic reference is ambiguous")
    grant, session_id, record = matches[0]
    owner = owner_resolver(session_id)
    if owner is None or owner.get("tenant_id") != tenant_id or owner.get("agent_id") != agent_id:
        raise FailureDiagnosticsUnauthorized("diagnostic scope denied")
    tasks = None
    if task_lookup is not None:
        try:
            tasks = task_lookup(
                tenant_id=tenant_id, user_id=str(owner["user_id"]),
                agent_id=agent_id, session_id=session_id,
                installation_id=grant.installation_id, invocation_id=invocation_id,
            )
        except Exception as exc:
            raise FailureDiagnosticsUnavailable("task evidence cannot be read") from exc
    safe_tasks = []
    if tasks is not None:
        if not isinstance(tasks, list):
            raise FailureDiagnosticsUnavailable("invalid task evidence")
        for task in tasks[:100]:
            if not isinstance(task, dict):
                raise FailureDiagnosticsUnavailable("invalid task evidence")
            digest = task.get("task_id_sha256")
            result_digest = task.get("result_sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise FailureDiagnosticsUnavailable("invalid task evidence")
            safe_tasks.append({
                "task_id_sha256": digest,
                "capability": task["capability"] if isinstance(task.get("capability"), str) and _CAPABILITY_ID.fullmatch(task["capability"]) else "not_recorded",
                "status": _token(task.get("status")) or "not_recorded",
                "error_code": task.get("error_code") if isinstance(task.get("error_code"), str) and _ERROR_CODE.fullmatch(task["error_code"]) else None,
                "result_sha256": result_digest if isinstance(result_digest, str) and re.fullmatch(r"[0-9a-f]{64}", result_digest) else None,
            })
    stages = record.get("stages_v2", [])
    transaction_events = {
        stage["event"] for stage in stages
        if stage["source"] == "host" and stage["event"] in {"transaction.committed", "transaction.discarded"}
    }
    transaction_status = (
        "partially_committed" if len(transaction_events) == 2
        else "committed" if "transaction.committed" in transaction_events
        else "discarded" if "transaction.discarded" in transaction_events
        else "not_recorded"
    )
    operations = record.get("host_operations", [])[:100]
    localization = [operation for operation in operations if operation["capability"] == "aigc.task.assets.localize/1" and operation["event"] == "host.operation.completed"]
    task_acceptance = (
        "accepted" if any(task["capability"] == "aigc.task.assets.localize/1" for task in safe_tasks)
        or any(operation.get("task_accepted") is True for operation in localization)
        else "not_accepted" if tasks is not None
        else "not_accepted" if localization else "not_recorded"
    )
    first = record.get("first_failure")
    return {
        "contract": "developer.runtime.diagnostics.by-reference/4",
        "status": "found", "retention_days": READ_WINDOW.days,
        "task_id": session_id, "invocation_id": invocation_id,
        "installation_id": grant.installation_id, "release_id": grant.release_id,
        "started_at": record.get("started_at").isoformat() if record.get("started_at") else None,
        "ended_at": (record.get("failed_at") or record["completed_at"]).isoformat(),
        "runtime_outcome": "failed" if "failed_at" in record else "completed",
        "transaction_status": transaction_status,
        "first_failure": first or {"phase": None, "category": None, "attempt": None},
        "first_failure_source": record.get("first_failure_source") or ("agent_trace" if first else "not_recorded"),
        "task_acceptance": task_acceptance,
        "task_evidence": "available" if tasks is not None else "not_recorded",
        "tasks": safe_tasks,
        "host_operations": operations,
        "stages": stages[:100],
    }


def read_developer_invocation_by_reference_v5(**kwargs: Any) -> dict[str, Any]:
    """Add a safe, actionable Host blocker without changing the closed v4 result."""
    prior = read_developer_invocation_by_reference_v4(**kwargs)
    result = {**prior, "contract": "developer.runtime.diagnostics.by-reference/5"}
    if prior["status"] == "no_record":
        return result
    path = (Path(kwargs["storage_root"]) / "traces"
            / _scope(prior["installation_id"])
            / f"{_scope(prior['task_id'])}.ndjson")
    record = next((item for item in _trace_failure(
        path, prior["installation_id"], prior["task_id"],
        include_completed=True,
    ) if item["invocation_id"] == prior["invocation_id"]), None)
    if record is None:
        raise FailureDiagnosticsUnavailable("diagnostic trace changed during read")
    details = record.get("host_failure_details", [])
    detail = details[0] if details else None
    if detail is not None and detail.get("error_code"):
        blocker = {
            "phase": detail.get("host_stage") or "host_operation",
            "error_code": detail["error_code"],
            "field_path": detail.get("field_path") or "not_recorded",
            "constraint": detail.get("constraint") or "not_recorded",
            "responsibility": detail.get("responsibility") or "undetermined",
            "recovery_action": detail.get("recovery_action")
            or "contact_platform_with_invocation_id",
            "evidence": "recorded",
        }
    else:
        rejected = next((operation for operation in prior["host_operations"]
                         if operation["event"] == "host.operation.completed"
                         and operation["capability"] == "aigc.task.assets.localize/1"
                         and operation.get("status") in {
                             "rejected", "not_found", "unavailable",
                         }), None)
        status = rejected.get("status") if rejected else None
        code = rejected.get("error_code") if rejected else None
        if code == "LOCAL_GATEWAY.DEVICE_NOT_READY":
            responsibility, action = "environment", "reconnect_helper"
        elif code == "LOCAL_GATEWAY.IDEMPOTENCY_CONFLICT":
            responsibility, action = "developer", "correct_request"
        elif status == "not_found":
            code = "AIGC_TASK_NOT_FOUND_OR_UNAUTHORIZED"
            responsibility, action = "developer", "verify_task_binding"
        elif status == "unavailable":
            code = "AIGC_BINDING_UNAVAILABLE"
            responsibility, action = "platform", "contact_platform_with_invocation_id"
        else:
            responsibility, action = "undetermined", "contact_platform_with_invocation_id"
        blocker = {
            "phase": ("task_binding" if status in {"not_found", "unavailable"}
                      else "task_dispatch") if rejected else
            (prior["first_failure"].get("phase") or "not_recorded"),
            "error_code": code,
            "field_path": "not_recorded", "constraint": "not_recorded",
            "responsibility": responsibility,
            "recovery_action": action,
            "evidence": "recorded" if code else "historical_detail_not_recorded",
        }
    result["blocker"] = blocker
    return result


def search_developer_failures(
    *, storage_root: Path, grants: Any, agent_id: str, tenant_id: str,
    owner_resolver: Callable[[str], dict[str, Any] | None],
    start: datetime, end: datetime, limit: int = 50,
    cursor: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Find opaque failure references for an owned expert in a bounded window."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if (
        start.tzinfo is None or end.tzinfo is None or not 1 <= limit <= 50
        or end <= start or end - start > timedelta(days=1)
        or start < now - READ_WINDOW or end > now + timedelta(minutes=1)
        or (cursor is not None and re.fullmatch(r"(?:[0-9a-f]{32}|preflight-[0-9a-f]{32})", cursor) is None)
    ):
        raise ValueError("invalid diagnostic search window")
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    matches: list[dict[str, str]] = []
    inspected = 0
    for grant in grants.list_grants():
        if grant.tenant_id != tenant_id or grant.agent_id != agent_id:
            continue
        directory = Path(storage_root) / "traces" / _scope(grant.installation_id)
        if directory.is_symlink():
            raise FailureDiagnosticsUnavailable("unsafe failure trace directory")
        if not directory.exists():
            continue
        for path in directory.glob("*.ndjson"):
            inspected += 1
            if inspected > 5000:
                raise FailureDiagnosticsUnavailable("failure trace search limit exceeded")
            if path.is_symlink() or not path.is_file():
                raise FailureDiagnosticsUnavailable("unsafe failure trace")
            try:
                with path.open(encoding="utf-8") as stream:
                    first = json.loads(stream.readline())
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise FailureDiagnosticsUnavailable("failure trace cannot be read") from exc
            session_id = first.get("session_id") if isinstance(first, dict) else None
            if (
                not isinstance(session_id, str) or
                path.name != f"{_scope(session_id)}.ndjson" or
                first.get("installation_id") != grant.installation_id
            ):
                raise FailureDiagnosticsUnavailable("failure trace scope mismatch")
            owner = owner_resolver(session_id)
            if (
                owner is None or owner.get("tenant_id") != tenant_id
                or owner.get("agent_id") != agent_id
            ):
                continue
            for failure in _trace_failure(path, grant.installation_id, session_id):
                when = failure["failed_at"]
                if start <= when < end:
                    matches.append({
                        "task_id": session_id,
                        "invocation_id": failure["invocation_id"],
                        "failed_at": when.isoformat(),
                        "release_id": grant.release_id,
                    })
    matches.sort(key=lambda item: (item["failed_at"], item["invocation_id"]), reverse=True)
    if cursor is not None:
        positions = [index for index, item in enumerate(matches) if item["invocation_id"] == cursor]
        if len(positions) != 1:
            raise ValueError("invalid diagnostic search cursor")
        matches = matches[positions[0] + 1:]
    page = matches[:limit]
    return {
        "contract": "developer.runtime.diagnostics.search/1",
        "status": "found" if page else "no_record",
        "retention_days": READ_WINDOW.days,
        "failures": page,
        "has_more": len(matches) > limit,
        "next_cursor": page[-1]["invocation_id"] if len(matches) > limit else None,
    }
