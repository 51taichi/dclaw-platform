# -*- coding: utf-8 -*-
"""Open API key authentication helpers."""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request

from ..storage.repos.open_api_repo import get_open_api_repository
from ..storage.repos.user_repo import get_user_repository

KEY_PREFIX = "qp_live"


@dataclass(frozen=True)
class OpenApiAuthContext:
    api_key: dict[str, Any]
    app: dict[str, Any]
    publication: dict[str, Any]


def generate_open_api_key() -> tuple[str, dict[str, str]]:
    """Generate a plaintext key and one-time display metadata."""
    plaintext = f"{KEY_PREFIX}_{secrets.token_urlsafe(32)}"
    return plaintext, {
        "key_prefix": KEY_PREFIX,
        "key_suffix": plaintext[-4:],
    }


def hash_open_api_key(plaintext: str) -> str:
    digest = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _extract_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "").strip()
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="Open API key required")
    return token.strip()


async def authenticate_open_api_request(
    request: Request,
    required_scope: str,
) -> OpenApiAuthContext:
    token = _extract_bearer_token(request)
    repo = get_open_api_repository()

    try:
        api_key = repo.get_api_key_by_hash(hash_open_api_key(token))
        if (
            api_key is None
            or api_key.get("status") != "active"
            or _is_expired(api_key.get("expires_at"))
        ):
            raise HTTPException(status_code=401, detail="Invalid or expired Open API key")

        app = repo.get_external_app(str(api_key.get("app_id", "")))
        if app is None or app.get("status") != "enabled":
            raise HTTPException(status_code=401, detail="Open API app is disabled")

        publication = repo.get_publication(str(api_key.get("publication_id", "")))
        if publication is None or publication.get("status") != "enabled":
            raise HTTPException(status_code=401, detail="Open API publication is disabled")

        bound_user_id = str(
            publication.get("bound_user_id")
            or publication.get("owner_user_id")
            or "",
        )
        if publication.get("bound_user_id") not in (None, ""):
            try:
                bound_user = get_user_repository().get_user_by_id(int(bound_user_id))
            except (TypeError, ValueError):
                bound_user = None
            if bound_user is None:
                raise HTTPException(
                    status_code=401,
                    detail="Open API bound user is unavailable",
                )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid Open API credential configuration") from exc

    client_ip = _client_ip(request)
    allowlist = app.get("ip_allowlist") or []
    if allowlist and client_ip not in allowlist:
        raise HTTPException(status_code=403, detail="Client IP is not allowed")

    key_scopes = set(api_key.get("scopes") or [])
    publication_scopes = set(publication.get("allowed_scopes") or [])
    if required_scope not in key_scopes or required_scope not in publication_scopes:
        raise HTTPException(status_code=403, detail="Open API scope is not allowed")

    repo.mark_api_key_used(str(api_key["id"]), client_ip)

    context = OpenApiAuthContext(api_key=api_key, app=app, publication=publication)
    request.state.user_id = bound_user_id
    request.state.role = "open_app"
    request.state.open_app_id = app["id"]
    request.state.open_publication_id = publication["id"]
    request.state.open_api_key_id = api_key["id"]
    request.state.open_auth_context = context
    return context


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _is_expired(expires_at: Any) -> bool:
    if not expires_at:
        return False
    if isinstance(expires_at, datetime):
        expires = expires_at
    elif isinstance(expires_at, str):
        try:
            expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            return True
    else:
        return True

    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= datetime.now(timezone.utc)
