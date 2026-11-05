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
                if event not in {"orchestration.started", "runtime.trace", "orchestration.failed"}:
                    continue
                invocation = invocations.setdefault(record["invocation_id"], {})
                when = _timestamp(record.get("timestamp"))
                if event == "orchestration.started":
                    invocation["started_at"] = when
                elif event == "orchestration.failed":
                    invocation["failed_at"] = when
                    payload = record.get("payload") or {}
                    invocation["error_code"] = _token(payload.get("error_code"))
                else:
                    payload = (record.get("payload") or {}).get("payload") or {}
                    if payload.get("event") == "agent.turn.failure" and "first_failure" not in invocation:
                        attempt = payload.get("attempt")
                        invocation["first_failure"] = {
                            "phase": _token(payload.get("phase")),
                            "category": _token(payload.get("category")),
                            "attempt": attempt if type(attempt) is int and 1 <= attempt <= 100 else None,
                        }
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError) as exc:
        raise FailureDiagnosticsUnavailable("failure trace cannot be read") from exc
    return [
        {"invocation_id": invocation_id, **value}
        for invocation_id, value in invocations.items()
        if "failed_at" in value
    ]


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
        "first_failure_source": "agent_trace" if first_failure else "not_recorded",
        "error_code": failure.get("error_code"),
        "transaction_status": "discarded",
    }
