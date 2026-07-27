# -*- coding: utf-8 -*-
"""Tests for Mindspace cloud document authorization storage."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from qwenpaw.mindspace.cloud_auth import (
    CloudAccount,
    CloudAuthStore,
    CloudProviderAppConfig,
)
from qwenpaw.mindspace.connectors import CloudConnectorRegistry


def test_admin_provider_config_is_saved_and_secret_is_masked(tmp_path):
    store = CloudAuthStore(root=tmp_path / "mindspace")

    store.upsert_app_config(
        CloudProviderAppConfig(
            provider="lark",
            client_id="cli_123",
            client_secret="super-secret",
            redirect_uri="https://example.com/oauth/lark/callback",
            scopes=["docs:read"],
            enabled=True,
            connector_url="https://connector.example.com/lark/fetch",
        )
    )

    saved = store.get_app_config("lark")

    assert saved is not None
    assert saved.client_secret == "super-secret"
    assert saved.to_public_dict()["client_secret"] == "********"
    assert saved.to_public_dict()["configured"] is True


def test_authorization_url_uses_admin_config_and_persists_state(tmp_path):
    store = CloudAuthStore(root=tmp_path / "mindspace")
    store.upsert_app_config(
        CloudProviderAppConfig(
            provider="lark",
            client_id="cli_123",
            client_secret="secret",
            redirect_uri="https://example.com/oauth/lark/callback",
            scopes=["docs:read", "drive:read"],
            enabled=True,
            authorization_url="https://open.feishu.cn/open-apis/authen/v1/authorize",
        )
    )

    auth_url = store.create_authorization_url(provider="lark", user_id="user-a")
    state = auth_url.split("state=", 1)[1].split("&", 1)[0]

    assert "client_id=cli_123" in auth_url
    assert "redirect_uri=https%3A%2F%2Fexample.com%2Foauth%2Flark%2Fcallback" in auth_url
    assert "scope=docs%3Aread+drive%3Aread" in auth_url
    assert store.consume_oauth_state(state).user_id == "user-a"


def test_cloud_accounts_are_scoped_to_current_user(tmp_path):
    store = CloudAuthStore(root=tmp_path / "mindspace")
    store.upsert_account(
        CloudAccount(
            id="acct-a",
            provider="tencent",
            user_id="user-a",
            provider_user_id="tencent-user-a",
            display_name="A",
            access_token="token-a",
            refresh_token="refresh-a",
        )
    )
    store.upsert_account(
        CloudAccount(
            id="acct-b",
            provider="tencent",
            user_id="user-b",
            provider_user_id="tencent-user-b",
            display_name="B",
            access_token="token-b",
            refresh_token="refresh-b",
        )
    )

    accounts = store.list_accounts(user_id="user-a")

    assert [account.id for account in accounts] == ["acct-a"]
    assert store.get_account("acct-b", user_id="user-a") is None


@pytest.mark.asyncio
async def test_refresh_expired_account_token_updates_saved_account(monkeypatch, tmp_path):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "expires_in": 3600,
                }
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.requests = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            self.requests.append({"url": url, "json": json})
            return FakeResponse()

    fake_client = FakeClient()
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: fake_client)

    store = CloudAuthStore(root=tmp_path / "mindspace")
    config = CloudProviderAppConfig(
        provider="lark",
        client_id="cli_123",
        client_secret="secret",
        token_url="https://open.feishu.cn/open-apis/authen/v2/oauth/token",
        enabled=True,
    )
    account = CloudAccount(
        id="acct-a",
        provider="lark",
        user_id="user-a",
        provider_user_id="open-id",
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
    )
    store.upsert_account(account)

    refreshed = await store.refresh_account_token(account, config)

    assert refreshed.access_token == "new-access"
    assert refreshed.refresh_token == "new-refresh"
    assert store.get_account("acct-a", user_id="user-a").access_token == "new-access"
    assert fake_client.requests[0]["url"] == config.token_url
    assert fake_client.requests[0]["json"]["grant_type"] == "refresh_token"
    assert fake_client.requests[0]["json"]["refresh_token"] == "old-refresh"


def test_connector_status_uses_builtin_connector_without_external_url(tmp_path):
    store = CloudAuthStore(root=tmp_path / "mindspace")
    store.upsert_app_config(
        CloudProviderAppConfig(
            provider="lark",
            client_id="cli_123",
            client_secret="secret",
            redirect_uri="https://example.com/oauth/lark/callback",
            enabled=True,
        )
    )

    statuses = {
        item.provider: item for item in CloudConnectorRegistry(auth_store=store).status()
    }

    assert statuses["lark"].configured is True
    assert statuses["lark"].status == "builtin"
    assert "built-in" in statuses["lark"].message.lower()


def test_connector_status_uses_external_override_when_configured(tmp_path):
    store = CloudAuthStore(root=tmp_path / "mindspace")
    store.upsert_app_config(
        CloudProviderAppConfig(
            provider="lark",
            client_id="cli_123",
            client_secret="secret",
            redirect_uri="https://example.com/oauth/lark/callback",
            enabled=True,
            connector_url="https://connector.example.com/lark/fetch",
        )
    )

    statuses = {
        item.provider: item for item in CloudConnectorRegistry(auth_store=store).status()
    }

    assert statuses["lark"].configured is True
    assert statuses["lark"].status == "external"
    assert "external" in statuses["lark"].message.lower()


def test_tencent_builtin_connector_fails_closed_without_official_export_binding(tmp_path):
    store = CloudAuthStore(root=tmp_path / "mindspace")
    store.upsert_app_config(
        CloudProviderAppConfig(
            provider="tencent",
            client_id="cli_123",
            client_secret="secret",
            redirect_uri="https://example.com/oauth/tencent/callback",
            enabled=True,
        )
    )
    store.upsert_account(
        CloudAccount(
            id="acct-a",
            provider="tencent",
            user_id="user-a",
            provider_user_id="tencent-user-a",
            access_token="token-a",
        )
    )

    import pytest

    with pytest.raises(Exception) as exc:
        import asyncio

        asyncio.run(
            CloudConnectorRegistry(auth_store=store).fetch_text(
                "tencent",
                "https://docs.qq.com/doc/example",
                "Example",
                cloud_account_id="acct-a",
                user_id="user-a",
            )
        )

    assert "built-in" in str(exc.value).lower()
    assert "official" in str(exc.value).lower()


def test_lark_builtin_connector_exports_document_text(monkeypatch, tmp_path):
    class FakeResponse:
        def __init__(self, payload=None, content=b""):
            self.payload = payload or {}
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.requests = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json, headers=None):
            self.requests.append(
                {"method": "POST", "url": url, "json": json, "headers": headers or {}}
            )
            return FakeResponse({"code": 0, "data": {"ticket": "ticket-1"}})

        async def get(self, url, headers=None):
            self.requests.append(
                {"method": "GET", "url": url, "headers": headers or {}}
            )
            if url.endswith("/export_tasks/ticket-1"):
                return FakeResponse(
                    {
                        "code": 0,
                        "data": {
                            "result": {
                                "file_token": "export-file-token",
                                "job_status": 0,
                            }
                        },
                    }
                )
            return FakeResponse(content=b"Quarterly roadmap\nNova launch approval")

    fake_client = FakeClient()
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: fake_client)

    store = CloudAuthStore(root=tmp_path / "mindspace")
    store.upsert_app_config(
        CloudProviderAppConfig(
            provider="lark",
            client_id="cli_123",
            client_secret="secret",
            redirect_uri="https://example.com/oauth/lark/callback",
            enabled=True,
        )
    )
    store.upsert_account(
        CloudAccount(
            id="acct-a",
            provider="lark",
            user_id="user-a",
            provider_user_id="lark-user-a",
            access_token="token-a",
        )
    )

    text = asyncio.run(
        CloudConnectorRegistry(auth_store=store).fetch_text(
            "lark",
            "https://example.feishu.cn/docx/DocTokenAbc",
            "Roadmap",
            cloud_account_id="acct-a",
            user_id="user-a",
        )
    )

    assert "Nova launch approval" in text
    create_request = fake_client.requests[0]
    assert create_request["url"].endswith("/open-apis/drive/v1/export_tasks")
    assert create_request["json"] == {
        "file_extension": "txt",
        "token": "DocTokenAbc",
        "type": "docx",
    }
    assert create_request["headers"]["Authorization"] == "Bearer token-a"


@pytest.mark.asyncio
async def test_lark_oauth_exchange_uses_default_token_url(monkeypatch):
    from qwenpaw.app.routers.mindspace_cloud import _exchange_oauth_code

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": {"access_token": "access-from-code"}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.requests = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            self.requests.append({"url": url, "json": json})
            return FakeResponse()

    fake_client = FakeClient()
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: fake_client)

    payload = await _exchange_oauth_code(
        CloudProviderAppConfig(
            provider="lark",
            client_id="cli_123",
            client_secret="secret",
            redirect_uri="https://example.com/oauth/callback/lark",
        ),
        "code-123",
    )

    assert payload["access_token"] == "access-from-code"
    assert fake_client.requests[0]["url"].endswith("/open-apis/authen/v2/oauth/token")
