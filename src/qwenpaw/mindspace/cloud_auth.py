# -*- coding: utf-8 -*-
"""Cloud document app configuration and per-user OAuth account storage."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from .models import utc_now_iso


DEFAULT_AUTHORIZATION_URLS = {
    "lark": "https://open.feishu.cn/open-apis/authen/v1/authorize",
    "feishu": "https://open.feishu.cn/open-apis/authen/v1/authorize",
}

DEFAULT_TOKEN_URLS = {
    "lark": "https://open.feishu.cn/open-apis/authen/v2/oauth/token",
    "feishu": "https://open.feishu.cn/open-apis/authen/v2/oauth/token",
}


@dataclass
class CloudProviderAppConfig:
    provider: str
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    scopes: list[str] = field(default_factory=list)
    enabled: bool = False
    authorization_url: str = ""
    token_url: str = ""
    connector_url: str = ""
    updated_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CloudProviderAppConfig":
        return cls(
            provider=str(raw.get("provider") or ""),
            client_id=str(raw.get("client_id") or ""),
            client_secret=str(raw.get("client_secret") or ""),
            redirect_uri=str(raw.get("redirect_uri") or ""),
            scopes=[str(scope) for scope in raw.get("scopes") or []],
            enabled=bool(raw.get("enabled", False)),
            authorization_url=str(raw.get("authorization_url") or ""),
            token_url=str(raw.get("token_url") or ""),
            connector_url=str(raw.get("connector_url") or ""),
            updated_at=str(raw.get("updated_at") or utc_now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "scopes": self.scopes,
            "enabled": self.enabled,
            "authorization_url": self.authorization_url,
            "token_url": self.token_url,
            "connector_url": self.connector_url,
            "updated_at": self.updated_at,
        }

    def to_public_dict(self) -> dict[str, Any]:
        configured = bool(self.enabled and self.client_id and self.redirect_uri)
        return {
            "provider": self.provider,
            "client_id": self.client_id,
            "client_secret": "********" if self.client_secret else "",
            "redirect_uri": self.redirect_uri,
            "scopes": self.scopes,
            "enabled": self.enabled,
            "authorization_url": self.authorization_url,
            "token_url": self.token_url,
            "connector_url": self.connector_url,
            "configured": configured,
            "updated_at": self.updated_at,
        }


@dataclass
class CloudAccount:
    id: str
    provider: str
    user_id: str
    provider_user_id: str = ""
    display_name: str = ""
    access_token: str = ""
    refresh_token: str = ""
    expires_at: str | None = None
    scopes: list[str] = field(default_factory=list)
    status: str = "authorized"
    updated_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CloudAccount":
        return cls(
            id=str(raw.get("id") or ""),
            provider=str(raw.get("provider") or ""),
            user_id=str(raw.get("user_id") or ""),
            provider_user_id=str(raw.get("provider_user_id") or ""),
            display_name=str(raw.get("display_name") or ""),
            access_token=str(raw.get("access_token") or ""),
            refresh_token=str(raw.get("refresh_token") or ""),
            expires_at=raw.get("expires_at"),
            scopes=[str(scope) for scope in raw.get("scopes") or []],
            status=str(raw.get("status") or "authorized"),
            updated_at=str(raw.get("updated_at") or utc_now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "user_id": self.user_id,
            "provider_user_id": self.provider_user_id,
            "display_name": self.display_name,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scopes": self.scopes,
            "status": self.status,
            "updated_at": self.updated_at,
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "user_id": self.user_id,
            "provider_user_id": self.provider_user_id,
            "display_name": self.display_name,
            "expires_at": self.expires_at,
            "scopes": self.scopes,
            "status": self.status,
            "updated_at": self.updated_at,
            "has_access_token": bool(self.access_token),
            "has_refresh_token": bool(self.refresh_token),
        }


@dataclass
class OAuthState:
    state: str
    provider: str
    user_id: str
    created_at: str = field(default_factory=utc_now_iso)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "OAuthState":
        return cls(
            state=str(raw.get("state") or ""),
            provider=str(raw.get("provider") or ""),
            user_id=str(raw.get("user_id") or ""),
            created_at=str(raw.get("created_at") or utc_now_iso()),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "state": self.state,
            "provider": self.provider,
            "user_id": self.user_id,
            "created_at": self.created_at,
        }


class CloudAuthStore:
    """JSON-backed store for cloud document app and account authorization."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def list_app_configs(self) -> list[CloudProviderAppConfig]:
        return [
            CloudProviderAppConfig.from_dict(raw)
            for raw in self._read_json(self._apps_path(), [])
            if isinstance(raw, dict) and raw.get("provider")
        ]

    def get_app_config(self, provider: str) -> CloudProviderAppConfig | None:
        normalized = self._normalize_provider(provider)
        for config in self.list_app_configs():
            if self._normalize_provider(config.provider) == normalized:
                return config
        return None

    def upsert_app_config(self, config: CloudProviderAppConfig) -> CloudProviderAppConfig:
        config.provider = self._normalize_provider(config.provider)
        config.updated_at = utc_now_iso()
        configs = self.list_app_configs()
        replaced = False
        for idx, existing in enumerate(configs):
            if self._normalize_provider(existing.provider) == config.provider:
                configs[idx] = config
                replaced = True
                break
        if not replaced:
            configs.append(config)
        self._write_json(self._apps_path(), [item.to_dict() for item in configs])
        return config

    def list_accounts(
        self,
        user_id: str | None = None,
        provider: str | None = None,
    ) -> list[CloudAccount]:
        normalized_provider = self._normalize_provider(provider) if provider else None
        accounts = [
            CloudAccount.from_dict(raw)
            for raw in self._read_json(self._accounts_path(), [])
            if isinstance(raw, dict) and raw.get("id")
        ]
        if user_id is not None:
            accounts = [account for account in accounts if account.user_id == str(user_id)]
        if normalized_provider is not None:
            accounts = [
                account
                for account in accounts
                if self._normalize_provider(account.provider) == normalized_provider
            ]
        return accounts

    def get_account(
        self,
        account_id: str,
        user_id: str | None = None,
    ) -> CloudAccount | None:
        for account in self.list_accounts(user_id=user_id):
            if account.id == account_id:
                return account
        return None

    def upsert_account(self, account: CloudAccount) -> CloudAccount:
        account.provider = self._normalize_provider(account.provider)
        account.user_id = str(account.user_id)
        account.updated_at = utc_now_iso()
        accounts = self.list_accounts()
        replaced = False
        for idx, existing in enumerate(accounts):
            if existing.id == account.id:
                accounts[idx] = account
                replaced = True
                break
        if not replaced:
            accounts.append(account)
        self._write_json(self._accounts_path(), [item.to_dict() for item in accounts])
        return account

    def account_token_expires_soon(
        self,
        account: CloudAccount,
        *,
        leeway_seconds: int = 300,
    ) -> bool:
        if not account.expires_at:
            return False
        try:
            expires_at = datetime.fromisoformat(str(account.expires_at))
        except ValueError:
            return True
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at <= datetime.now(timezone.utc) + timedelta(seconds=leeway_seconds)

    async def refresh_account_token(
        self,
        account: CloudAccount,
        config: CloudProviderAppConfig,
    ) -> CloudAccount:
        if not account.refresh_token:
            account.status = "expired"
            self.upsert_account(account)
            raise ValueError(f"{account.provider} account token expired and has no refresh token.")
        token_url = (
            config.token_url
            or DEFAULT_TOKEN_URLS.get(self._normalize_provider(config.provider))
            or ""
        )
        if not token_url:
            raise ValueError(f"{account.provider} token refresh URL is not configured.")

        import httpx

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": account.refresh_token,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(token_url, json=payload)
            response.raise_for_status()
            raw = response.json()

        data = raw.get("data") if isinstance(raw, dict) else None
        token_payload = data if isinstance(data, dict) else raw
        access_token = str(
            token_payload.get("access_token")
            or token_payload.get("user_access_token")
            or ""
        )
        if not access_token:
            account.status = "expired"
            self.upsert_account(account)
            raise ValueError("Token refresh response did not contain an access token.")

        account.access_token = access_token
        account.refresh_token = str(
            token_payload.get("refresh_token") or account.refresh_token
        )
        expires_at = token_payload.get("expires_at")
        expires_in = token_payload.get("expires_in")
        if not expires_at and expires_in is not None:
            try:
                expires_at = (
                    datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
                ).isoformat()
            except (TypeError, ValueError):
                expires_at = None
        account.expires_at = str(expires_at) if expires_at else None
        account.status = "authorized"
        return self.upsert_account(account)

    def create_authorization_url(self, provider: str, user_id: str) -> str:
        normalized = self._normalize_provider(provider)
        config = self.get_app_config(normalized)
        if not config or not config.enabled or not config.client_id or not config.redirect_uri:
            raise ValueError(f"{normalized} cloud document app is not configured.")
        state = secrets.token_urlsafe(24)
        states = self._load_oauth_states()
        states.append(OAuthState(state=state, provider=normalized, user_id=str(user_id)))
        self._save_oauth_states(states)
        authorization_url = (
            config.authorization_url
            or DEFAULT_AUTHORIZATION_URLS.get(normalized)
            or ""
        )
        if not authorization_url:
            raise ValueError(f"{normalized} authorization URL is not configured.")
        params = {
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "response_type": "code",
            "state": state,
        }
        if config.scopes:
            params["scope"] = " ".join(config.scopes)
        return f"{authorization_url}?{urlencode(params)}"

    def consume_oauth_state(self, state: str) -> OAuthState:
        states = self._load_oauth_states()
        remaining: list[OAuthState] = []
        matched: OAuthState | None = None
        for item in states:
            if item.state == state and matched is None:
                matched = item
            else:
                remaining.append(item)
        self._save_oauth_states(remaining)
        if matched is None:
            raise ValueError("OAuth state is invalid or expired.")
        return matched

    def _load_oauth_states(self) -> list[OAuthState]:
        return [
            OAuthState.from_dict(raw)
            for raw in self._read_json(self._states_path(), [])
            if isinstance(raw, dict) and raw.get("state")
        ]

    def _save_oauth_states(self, states: list[OAuthState]) -> None:
        self._write_json(self._states_path(), [state.to_dict() for state in states])

    def _apps_path(self) -> Path:
        return self.root / "cloud_apps.json"

    def _accounts_path(self) -> Path:
        return self.root / "cloud_accounts.json"

    def _states_path(self) -> Path:
        return self.root / "cloud_oauth_states.json"

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def _write_json(self, path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def _normalize_provider(self, provider: str | None) -> str:
        value = (provider or "").strip().lower()
        if value == "feishu":
            return "lark"
        return value
