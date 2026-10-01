"""Authentication for generic DClaw integration clients."""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass

from fastapi import HTTPException, Request


CLIENT_SECRETS_ENV = "DCLAW_INTEGRATION_CLIENT_SECRETS_JSON"
CLIENT_HEADER = "X-DClaw-Integration-Client"
SECRET_HEADER = "X-DClaw-Integration-Secret"


@dataclass(frozen=True, slots=True)
class AuthenticatedIntegrationClient:
    """Authenticated identity of one external platform integration."""

    client_id: str


class _DuplicateClientError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateClientError(key)
        result[key] = value
    return result


def _client_secrets() -> dict[str, str] | None:
    raw = os.environ.get(CLIENT_SECRETS_ENV, "")
    if not raw:
        return None
    try:
        parsed = json.loads(raw, object_pairs_hook=_unique_object)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict) or not parsed:
        return None
    result: dict[str, str] = {}
    for client_id, secret in parsed.items():
        if (
            not isinstance(client_id, str)
            or not client_id
            or client_id != client_id.strip()
            or not isinstance(secret, str)
            or not secret
        ):
            return None
        result[client_id] = secret
    return result


def require_integration_client(
    request: Request,
) -> AuthenticatedIntegrationClient:
    """Require a configured client id and its exact service secret."""

    configured = _client_secrets()
    if configured is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "INTEGRATION_API_NOT_CONFIGURED"},
        )

    client_id = request.headers.get(CLIENT_HEADER, "")
    supplied = request.headers.get(SECRET_HEADER, "")
    expected = configured.get(client_id)
    candidate = expected if expected is not None else "invalid-client"
    authenticated = bool(client_id and supplied and expected is not None)
    authenticated = authenticated and hmac.compare_digest(
        supplied,
        candidate,
    )
    if not authenticated:
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_INTEGRATION_CREDENTIAL"},
        )
    return AuthenticatedIntegrationClient(client_id=client_id)
