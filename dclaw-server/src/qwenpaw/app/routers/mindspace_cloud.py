# -*- coding: utf-8 -*-
"""Mindspace cloud document app config and user account authorization APIs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ...constant import WORKING_DIR
from ...mindspace.cloud_auth import (
    CloudAccount,
    CloudAuthStore,
    CloudProviderAppConfig,
    DEFAULT_TOKEN_URLS,
)


admin_router = APIRouter(prefix="/mindspace-cloud", tags=["mindspace-cloud"])
user_router = APIRouter(prefix="/mindspace-cloud", tags=["mindspace-cloud"])
public_router = APIRouter(prefix="/mindspace-cloud", tags=["mindspace-cloud"])


def _store() -> CloudAuthStore:
    return CloudAuthStore(Path(WORKING_DIR) / "mindspace")


def _current_user_id(request: Request) -> str:
    return str(getattr(request.state, "user_id", "0"))


class CloudProviderAppConfigRequest(BaseModel):
    client_id: str = ""
    client_secret: str | None = None
    redirect_uri: str = ""
    scopes: list[str] = Field(default_factory=list)
    enabled: bool = False
    authorization_url: str = ""
    token_url: str = ""
    connector_url: str = ""


class ManualCloudAccountRequest(BaseModel):
    provider_user_id: str = ""
    display_name: str = ""
    access_token: str
    refresh_token: str = ""
    expires_at: str | None = None
    scopes: list[str] = Field(default_factory=list)


@admin_router.get("/providers")
async def list_cloud_provider_configs() -> dict:
    store = _store()
    providers = {item.provider: item for item in store.list_app_configs()}
    return {
        "providers": [
            providers.get(provider, CloudProviderAppConfig(provider=provider)).to_public_dict()
            for provider in ["lark", "tencent"]
        ]
    }


@admin_router.put("/providers/{provider}")
async def update_cloud_provider_config(
    provider: str,
    payload: CloudProviderAppConfigRequest,
) -> dict:
    normalized_provider = "lark" if provider == "feishu" else provider.lower()
    if normalized_provider not in {"lark", "tencent"}:
        raise HTTPException(status_code=400, detail="Unsupported cloud provider")
    store = _store()
    existing = store.get_app_config(normalized_provider)
    client_secret = payload.client_secret
    if client_secret is None or client_secret == "********":
        client_secret = existing.client_secret if existing else ""
    config = store.upsert_app_config(
        CloudProviderAppConfig(
            provider=normalized_provider,
            client_id=payload.client_id.strip(),
            client_secret=(client_secret or "").strip(),
            redirect_uri=payload.redirect_uri.strip(),
            scopes=[scope.strip() for scope in payload.scopes if scope.strip()],
            enabled=payload.enabled,
            authorization_url=payload.authorization_url.strip(),
            token_url=payload.token_url.strip(),
            connector_url=payload.connector_url.strip(),
        )
    )
    return {"provider": config.to_public_dict()}


@user_router.get("/accounts")
async def list_cloud_accounts(request: Request) -> dict:
    store = _store()
    user_id = _current_user_id(request)
    configs = {item.provider: item for item in store.list_app_configs()}
    accounts = [item.to_public_dict() for item in store.list_accounts(user_id=user_id)]
    return {
        "providers": [
            {
                **configs.get(provider, CloudProviderAppConfig(provider=provider)).to_public_dict(),
                "accounts": [
                    account for account in accounts if account["provider"] == provider
                ],
            }
            for provider in ["lark", "tencent"]
        ],
        "accounts": accounts,
    }


@user_router.post("/accounts/{provider}/authorize-url")
async def create_cloud_authorization_url(provider: str, request: Request) -> dict:
    try:
        authorization_url = _store().create_authorization_url(
            provider=provider,
            user_id=_current_user_id(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"authorization_url": authorization_url}


@user_router.post("/accounts/{provider}/manual-token")
async def save_manual_cloud_account(
    provider: str,
    payload: ManualCloudAccountRequest,
    request: Request,
) -> dict:
    """Save an already-issued user token.

    This is intended for private deployments or connector adapters where the
    external OAuth callback is completed outside QwenPaw.
    """
    normalized_provider = "lark" if provider == "feishu" else provider.lower()
    if normalized_provider not in {"lark", "tencent"}:
        raise HTTPException(status_code=400, detail="Unsupported cloud provider")
    if not payload.access_token.strip():
        raise HTTPException(status_code=400, detail="access_token is required")
    account = CloudAccount(
        id=f"{normalized_provider}-{_current_user_id(request)}-{payload.provider_user_id or 'manual'}",
        provider=normalized_provider,
        user_id=_current_user_id(request),
        provider_user_id=payload.provider_user_id,
        display_name=payload.display_name or payload.provider_user_id or normalized_provider,
        access_token=payload.access_token,
        refresh_token=payload.refresh_token,
        expires_at=payload.expires_at,
        scopes=payload.scopes,
    )
    return {"account": _store().upsert_account(account).to_public_dict()}


@public_router.get("/oauth/callback/{provider}")
async def cloud_oauth_callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
) -> HTMLResponse:
    store = _store()
    try:
        oauth_state = store.consume_oauth_state(state)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    normalized_provider = "lark" if provider == "feishu" else provider.lower()
    if normalized_provider != oauth_state.provider:
        raise HTTPException(status_code=400, detail="OAuth provider mismatch")
    config = store.get_app_config(normalized_provider)
    token_url = (
        config.token_url
        or DEFAULT_TOKEN_URLS.get(normalized_provider)
        if config
        else ""
    )
    if not config or not token_url:
        raise HTTPException(
            status_code=400,
            detail=f"{normalized_provider} token URL is not configured",
        )
    try:
        token_payload = await _exchange_oauth_code(config, code)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Token exchange failed: {exc}") from exc
    account = _account_from_token_payload(
        provider=normalized_provider,
        user_id=oauth_state.user_id,
        payload=token_payload,
        fallback_scopes=config.scopes,
    )
    saved = store.upsert_account(account)
    return HTMLResponse(
        "<html><body><h3>Cloud document authorization completed.</h3>"
        f"<p>{saved.provider} account {saved.display_name or saved.provider_user_id} is connected.</p>"
        "<p>You can close this window and return to QwenPaw.</p></body></html>"
    )


async def _exchange_oauth_code(
    config: CloudProviderAppConfig,
    code: str,
) -> dict[str, Any]:
    import httpx

    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "redirect_uri": config.redirect_uri,
    }
    token_url = (
        config.token_url
        or DEFAULT_TOKEN_URLS.get("lark" if config.provider == "feishu" else config.provider)
        or ""
    )
    if not token_url:
        raise ValueError(f"{config.provider} token URL is not configured")
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(token_url, json=payload)
        response.raise_for_status()
        data = response.json()
    if isinstance(data.get("data"), dict):
        return data["data"]
    return data


def _account_from_token_payload(
    provider: str,
    user_id: str,
    payload: dict[str, Any],
    fallback_scopes: list[str],
) -> CloudAccount:
    access_token = str(payload.get("access_token") or payload.get("user_access_token") or "")
    refresh_token = str(payload.get("refresh_token") or "")
    provider_user_id = str(
        payload.get("open_id")
        or payload.get("union_id")
        or payload.get("user_id")
        or payload.get("uid")
        or ""
    )
    display_name = str(payload.get("name") or payload.get("display_name") or provider_user_id or provider)
    expires_at = payload.get("expires_at")
    expires_in = payload.get("expires_in")
    if not expires_at and isinstance(expires_in, int):
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        ).isoformat()
    if not access_token:
        raise ValueError("Token response did not contain an access token")
    account_id = f"{provider}-{user_id}-{provider_user_id or 'default'}"
    return CloudAccount(
        id=account_id,
        provider=provider,
        user_id=str(user_id),
        provider_user_id=provider_user_id,
        display_name=display_name,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        scopes=[str(scope) for scope in payload.get("scopes") or fallback_scopes],
    )
