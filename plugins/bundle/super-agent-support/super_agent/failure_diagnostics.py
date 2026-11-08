"""Owner-scoped projection of prior workspace failures."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


READ_CONTRACT = "runtime.failure.read/1"
READ_WINDOW = timedelta(days=30)
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_FIELD_PATH = re.compile(r"[A-Za-z][A-Za-z0-9_.\[\]-]{0,127}\Z")
_CAPABILITY_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}/[0-9]{1,3}\Z")


class FailureDiagnosticsUnauthorized(ValueError):
    pass


class FailureDiagnosticsUnavailable(ValueError):
    pass


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


def _trace_failure(path: Path, installation_id: str, session_id: str) -> list[dict[str, Any]]:
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
                elif event == "runtime.trace":
                    trace = payload
                    if trace.get("event") == "agent.turn.failure":
                        attempt = trace.get("attempt")
                        invocation.setdefault("failure_events", []).append({
                            "phase": _token(trace.get("phase")) or "not_recorded",
                            "category": _token(trace.get("category")) or "not_recorded",
                            "attempt": attempt if type(attempt) is int and 1 <= attempt <= 100 else None,
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
                            "attempt": attempt if type(attempt) is int and 1 <= attempt <= 100 else None,
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
        {"invocation_id": invocation_id, **value}
        for invocation_id, value in invocations.items()
        if "failed_at" in value
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
    terminal = next((event for event in reversed(unresolved) if event["source"] != "agent"), None)
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
    result["unrecorded_fields"] = [
        field for field in ("provider_code", "provider_param")
        if terminal is None or terminal[field] is None
    ]
    return result
