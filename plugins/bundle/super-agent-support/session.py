"""Short-lived, invocation-bound local execution sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from typing import Any

CAPABILITY_ID = "local.execution.session/1"
PREFLIGHT_CAPABILITY_ID = "local.environment.preflight/1"
CONTEXT_KEY = "local_execution_session_token"
MAX_LIFETIME_SECONDS = 600


class SessionError(ValueError):
    """A local execution session is missing, invalid, or expired."""


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
                "local execution session key must be at least 32 bytes"
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
        now: int | None = None,
    ) -> str:
        values = (
            user_id,
            session_id,
            agent_id,
            agent_name,
            installation_id,
            release_id,
            invocation_id,
        )
        if not all(isinstance(value, str) and value for value in values):
            raise SessionError("trusted session context is incomplete")
        issued_at = int(time.time()) if now is None else int(now)
        payload = {
            "v": 1,
            "u": user_id,
            "s": session_id,
            "a": agent_id,
            "n": agent_name,
            "g": installation_id,
            "r": release_id,
            "i": invocation_id,
            "iat": issued_at,
            "exp": issued_at + MAX_LIFETIME_SECONDS,
        }
        encoded = _encode(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":")
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
        return payload

    def enrich(
        self,
        context: Mapping[str, Any],
        *,
        granted_capabilities: Mapping[str, str],
        invocation_id: str,
    ) -> dict[str, Any]:
        result = dict(context)
        if granted_capabilities.get(CAPABILITY_ID) != "1":
            return result
        result[CONTEXT_KEY] = self.issue(
            user_id=str(context.get("user_id") or ""),
            session_id=str(context.get("session_id") or ""),
            agent_id=str(context.get("agent_id") or ""),
            agent_name=str(context.get("agent_name") or ""),
            installation_id=str(context.get("installation_id") or ""),
            release_id=str(context.get("release_id") or ""),
            invocation_id=invocation_id,
        )
        return result
