"""Issue short-lived credentials for the DClaw local execution gateway."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Mapping
from typing import Any

LOCAL_EXECUTION_SESSION_CAPABILITY = "local.execution.session/1"
LOCAL_EXECUTION_SESSION_SECRET_ENV = "DCLAW_LOCAL_EXECUTION_SESSION_SECRET"
LOCAL_EXECUTION_SESSION_CONTEXT_KEY = "local_execution_session_token"
MAX_SESSION_LIFETIME_SECONDS = 600
MIN_SECRET_BYTES = 32


class LocalExecutionSessionError(ValueError):
    """The platform could not issue or validate a local execution session."""


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except Exception as exc:
        raise LocalExecutionSessionError("invalid local execution session") from exc


def _validated_secret(secret: str | bytes | None) -> bytes:
    if secret is None:
        secret = os.environ.get(LOCAL_EXECUTION_SESSION_SECRET_ENV, "")
    value = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if len(value) < MIN_SECRET_BYTES:
        raise LocalExecutionSessionError(
            f"{LOCAL_EXECUTION_SESSION_SECRET_ENV} must contain at least 32 bytes",
        )
    return value


def issue_local_execution_session(
    *,
    user_id: str,
    session_id: str,
    agent_id: str,
    agent_name: str,
    invocation_id: str,
    secret: str | bytes | None = None,
    now: int | None = None,
    lifetime_seconds: int = MAX_SESSION_LIFETIME_SECONDS,
) -> str:
    """Create a Relay-compatible credential bound to one DClaw invocation."""
    if not 1 <= lifetime_seconds <= MAX_SESSION_LIFETIME_SECONDS:
        raise LocalExecutionSessionError("invalid local execution session lifetime")
    values = (user_id, session_id, agent_id, agent_name, invocation_id)
    if not all(isinstance(value, str) and value for value in values):
        raise LocalExecutionSessionError("trusted session context is incomplete")
    issued_at = int(time.time()) if now is None else int(now)
    payload = {
        "v": 1,
        "u": user_id,
        "s": session_id,
        "a": agent_id,
        "n": agent_name,
        "i": invocation_id,
        "iat": issued_at,
        "exp": issued_at + lifetime_seconds,
    }
    encoded = _encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        .encode("utf-8"),
    )
    signature = hmac.new(
        _validated_secret(secret),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded}.{_encode(signature)}"


def verify_local_execution_session(
    token: str,
    *,
    secret: str | bytes | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    """Validate a platform-issued credential for tests and compatible consumers."""
    try:
        encoded, supplied_signature = token.split(".", 1)
    except ValueError as exc:
        raise LocalExecutionSessionError("invalid local execution session") from exc
    expected = hmac.new(
        _validated_secret(secret),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(expected, _decode(supplied_signature)):
        raise LocalExecutionSessionError("invalid local execution session")
    try:
        payload = json.loads(_decode(encoded))
    except Exception as exc:
        raise LocalExecutionSessionError("invalid local execution session") from exc
    current = int(time.time()) if now is None else int(now)
    required = ("u", "s", "a", "n", "i")
    if (
        not isinstance(payload, dict)
        or payload.get("v") != 1
        or not all(isinstance(payload.get(key), str) and payload[key] for key in required)
        or not isinstance(payload.get("iat"), int)
        or not isinstance(payload.get("exp"), int)
        or payload["exp"] <= current
        or payload["iat"] > current
        or payload["exp"] - payload["iat"] > MAX_SESSION_LIFETIME_SECONDS
    ):
        raise LocalExecutionSessionError("invalid or expired local execution session")
    return payload


def inject_local_execution_session(
    context: Mapping[str, Any],
    *,
    granted_capabilities: Mapping[str, str],
    invocation_id: str,
    secret: str | bytes | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    """Add a credential only when the signed release was explicitly granted access."""
    result = dict(context)
    if granted_capabilities.get(LOCAL_EXECUTION_SESSION_CAPABILITY) != "1":
        return result
    result[LOCAL_EXECUTION_SESSION_CONTEXT_KEY] = issue_local_execution_session(
        user_id=str(context.get("user_id") or ""),
        session_id=str(context.get("session_id") or ""),
        agent_id=str(context.get("agent_id") or ""),
        agent_name=str(context.get("agent_name") or ""),
        invocation_id=invocation_id,
        secret=secret,
        now=now,
    )
    return result
