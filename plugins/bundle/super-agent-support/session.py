# -*- coding: utf-8 -*-
"""Short-lived, invocation-bound local execution sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Iterable, Mapping
from typing import Any

CAPABILITY_ID = "local.execution.session/1"
PREFLIGHT_CAPABILITY_ID = "local.environment.preflight/1"
BUSINESS_IDENTITY_CAPABILITY_ID = "business.service.installation-identity/1"
AGENT_OUTBOUND_CAPABILITY_ID = "agent.outbound/1"
CONTEXT_KEY = "local_execution_session_token"
MAX_LIFETIME_SECONDS = 600

# Historical names remain public from the plugin so old server-side imports
# keep working while the implementation stays outside DClaw core.
LOCAL_EXECUTION_SESSION_CAPABILITY = CAPABILITY_ID
LOCAL_EXECUTION_SESSION_SECRET_ENV = "DCLAW_LOCAL_EXECUTION_SESSION_SECRET"
LOCAL_EXECUTION_SESSION_CONTEXT_KEY = CONTEXT_KEY
MAX_SESSION_LIFETIME_SECONDS = MAX_LIFETIME_SECONDS
MIN_SECRET_BYTES = 32


class SessionError(ValueError):
    """A local execution session is missing, invalid, or expired."""


LocalExecutionSessionError = SessionError


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise SessionError("invalid local execution session") from exc


class SessionSigner:
    """Issue and verify one-invocation HMAC credentials."""

    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError(
                "local execution session key must be at least 32 bytes",
            )
        self._secret = secret

    def issue(
        self,
        *,
        user_id: str,
        session_id: str,
        agent_id: str,
        agent_name: str,
        installation_id: str,
        release_id: str,
        invocation_id: str,
        tenant_id: str = "local",
        capability_ids: Iterable[str] = (),
        now: int | None = None,
    ) -> str:
        tenant_id = tenant_id or "local"
        capabilities = sorted(set(capability_ids))
        values = (
            tenant_id,
            user_id,
            session_id,
            agent_id,
            agent_name,
            installation_id,
            release_id,
            invocation_id,
        )
        if not all(
            isinstance(value, str) and value for value in values
        ) or not all(
            isinstance(value, str) and value for value in capabilities
        ):
            raise SessionError("trusted session context is incomplete")
        issued_at = int(time.time()) if now is None else int(now)
        payload = {
            "v": 1,
            "t": tenant_id,
            "u": user_id,
            "s": session_id,
            "a": agent_id,
            "n": agent_name,
            "g": installation_id,
            "r": release_id,
            "i": invocation_id,
            "c": capabilities,
            "iat": issued_at,
            "exp": issued_at + MAX_LIFETIME_SECONDS,
        }
        encoded = _encode(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
        )
        signature = hmac.new(
            self._secret,
            encoded.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{encoded}.{_encode(signature)}"

    def verify(self, token: str, *, now: int | None = None) -> dict[str, Any]:
        try:
            encoded, supplied = token.split(".", 1)
        except (AttributeError, ValueError) as exc:
            raise SessionError("invalid local execution session") from exc
        expected = hmac.new(
            self._secret,
            encoded.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected, _decode(supplied)):
            raise SessionError("invalid local execution session")
        try:
            payload = json.loads(_decode(encoded))
        except Exception as exc:
            raise SessionError("invalid local execution session") from exc
        current = int(time.time()) if now is None else int(now)
        required = ("u", "s", "a", "n", "g", "r", "i")
        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or (
                "t" in payload
                and not (isinstance(payload.get("t"), str) and payload["t"])
            )
            or (
                "c" in payload
                and not (
                    isinstance(payload.get("c"), list)
                    and all(
                        isinstance(value, str) and value
                        for value in payload["c"]
                    )
                )
            )
            or not all(
                isinstance(payload.get(key), str) and payload[key]
                for key in required
            )
            or not isinstance(payload.get("iat"), int)
            or not isinstance(payload.get("exp"), int)
            or payload["iat"] > current
            or payload["exp"] <= current
            or payload["exp"] - payload["iat"] > MAX_LIFETIME_SECONDS
        ):
            raise SessionError("invalid or expired local execution session")
        payload.setdefault("t", "local")
        payload.setdefault("c", [])
        return payload

    def enrich(
        self,
        context: Mapping[str, Any],
        *,
        granted_capabilities: Mapping[str, str],
        invocation_id: str,
    ) -> dict[str, Any]:
        result = dict(context)
        if not any(
            granted_capabilities.get(capability_id) == "1"
            for capability_id in (
                CAPABILITY_ID,
                BUSINESS_IDENTITY_CAPABILITY_ID,
                AGENT_OUTBOUND_CAPABILITY_ID,
            )
        ):
            return result
        result[CONTEXT_KEY] = self.issue(
            user_id=str(context.get("user_id") or ""),
            session_id=str(context.get("session_id") or ""),
            agent_id=str(context.get("agent_id") or ""),
            agent_name=str(context.get("agent_name") or ""),
            installation_id=str(context.get("installation_id") or ""),
            release_id=str(context.get("release_id") or ""),
            invocation_id=invocation_id,
            tenant_id=str(context.get("tenant_id") or "local"),
            capability_ids=granted_capabilities,
        )
        return result


def _validated_legacy_secret(secret: str | bytes | None) -> bytes:
    if secret is None:
        secret = os.environ.get(LOCAL_EXECUTION_SESSION_SECRET_ENV, "")
    value = (
        secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    )
    if len(value) < MIN_SECRET_BYTES:
        message = (
            f"{LOCAL_EXECUTION_SESSION_SECRET_ENV} must contain "
            "at least 32 bytes"
        )
        raise LocalExecutionSessionError(message)
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
    """Issue the historical session format for compatibility consumers."""
    if not 1 <= lifetime_seconds <= MAX_SESSION_LIFETIME_SECONDS:
        raise LocalExecutionSessionError(
            "invalid local execution session " "lifetime",
        )
    values = (user_id, session_id, agent_id, agent_name, invocation_id)
    if not all(isinstance(value, str) and value for value in values):
        raise LocalExecutionSessionError(
            "trusted session context is " "incomplete",
        )
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
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"),
    )
    signature = hmac.new(
        _validated_legacy_secret(secret),
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
    """Verify the historical session format for compatibility consumers."""
    try:
        encoded, supplied_signature = token.split(".", 1)
    except (AttributeError, ValueError) as exc:
        raise LocalExecutionSessionError(
            "invalid local execution session",
        ) from exc
    expected = hmac.new(
        _validated_legacy_secret(secret),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(expected, _decode(supplied_signature)):
        raise LocalExecutionSessionError("invalid local execution session")
    try:
        payload = json.loads(_decode(encoded))
    except Exception as exc:
        raise LocalExecutionSessionError(
            "invalid local execution session",
        ) from exc
    current = int(time.time()) if now is None else int(now)
    required = ("u", "s", "a", "n", "i")
    if (
        not isinstance(payload, dict)
        or payload.get("v") != 1
        or not all(
            isinstance(payload.get(key), str) and payload[key]
            for key in required
        )
        or not isinstance(payload.get("iat"), int)
        or not isinstance(payload.get("exp"), int)
        or payload["exp"] <= current
        or payload["iat"] > current
        or payload["exp"] - payload["iat"] > MAX_SESSION_LIFETIME_SECONDS
    ):
        raise LocalExecutionSessionError(
            "invalid or expired local execution session",
        )
    return payload


def inject_local_execution_session(
    context: Mapping[str, Any],
    *,
    granted_capabilities: Mapping[str, str],
    invocation_id: str,
    secret: str | bytes | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    """Preserve the historical context enrichment contract."""
    result = dict(context)
    if granted_capabilities.get(LOCAL_EXECUTION_SESSION_CAPABILITY) != "1":
        return result
    result[
        LOCAL_EXECUTION_SESSION_CONTEXT_KEY
    ] = issue_local_execution_session(
        user_id=str(context.get("user_id") or ""),
        session_id=str(context.get("session_id") or ""),
        agent_id=str(context.get("agent_id") or ""),
        agent_name=str(context.get("agent_name") or ""),
        invocation_id=invocation_id,
        secret=secret,
        now=now,
    )
    return result
