# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, Request, Response

from qwenpaw.app import auth as app_auth
from qwenpaw.app.open_api import auth as open_api_auth


class FakeOpenApiRepository:
    def __init__(
        self,
        *,
        key: dict[str, object] | None = None,
        app: dict[str, object] | None = None,
        publication: dict[str, object] | None = None,
    ) -> None:
        self.key = key
        self.app = app
        self.publication = publication
        self.used: list[tuple[str, str]] = []

    def get_api_key_by_hash(self, key_hash: str) -> dict[str, object] | None:
        if self.key and self.key["key_hash"] == key_hash:
            return self.key
        return None

    def get_external_app(self, app_id: str) -> dict[str, object] | None:
        if self.app and self.app["id"] == app_id:
            return self.app
        return None

    def get_publication(self, publication_id: str) -> dict[str, object] | None:
        if self.publication and self.publication["id"] == publication_id:
            return self.publication
        return None

    def mark_api_key_used(self, key_id: str, ip: str) -> None:
        self.used.append((key_id, ip))


def _request(
    path: str = "/api/open/v1/messages",
    *,
    token: str | None = "qp_live_secret-token",
    client: tuple[str, int] = ("203.0.113.10", 12345),
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    raw_headers = list(headers or [])
    if token is not None:
        raw_headers.append((b"authorization", f"Bearer {token}".encode()))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "raw_path": path.encode(),
            "headers": raw_headers,
            "client": client,
            "scheme": "http",
            "server": ("127.0.0.1", 8088),
            "query_string": b"",
        },
    )


def _repo_for_token(
    token: str = "qp_live_secret-token",
    *,
    key_overrides: dict[str, object] | None = None,
    app_overrides: dict[str, object] | None = None,
    publication_overrides: dict[str, object] | None = None,
) -> FakeOpenApiRepository:
    key = {
        "id": "key-1",
        "app_id": "app-1",
        "publication_id": "pub-1",
        "key_hash": open_api_auth.hash_open_api_key(token),
        "scopes": ["messages:create"],
        "status": "active",
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
    }
    app = {
        "id": "app-1",
        "status": "enabled",
        "ip_allowlist": [],
    }
    publication = {
        "id": "pub-1",
        "owner_user_id": "user-1",
        "status": "enabled",
        "allowed_scopes": ["messages:create"],
    }
    key.update(key_overrides or {})
    app.update(app_overrides or {})
    publication.update(publication_overrides or {})
    return FakeOpenApiRepository(key=key, app=app, publication=publication)


def test_generate_open_api_key_returns_one_time_plaintext_and_display_metadata():
    plaintext, display = open_api_auth.generate_open_api_key()

    assert plaintext.startswith("qp_live_")
    assert display == {
        "key_prefix": "qp_live",
        "key_suffix": plaintext[-4:],
    }
    assert "plaintext" not in display
    assert "key_hash" not in display


def test_hash_open_api_key_is_stable_and_does_not_contain_plaintext():
    plaintext = "qp_live_secret-token"

    first = open_api_auth.hash_open_api_key(plaintext)
    second = open_api_auth.hash_open_api_key(plaintext)

    assert first == second
    assert first.startswith("sha256:")
    assert plaintext not in first


@pytest.mark.asyncio
async def test_authenticate_open_api_request_denies_missing_scope_without_marking_used(
    monkeypatch,
):
    repo = _repo_for_token(key_overrides={"scopes": ["messages:read"]})
    monkeypatch.setattr(open_api_auth, "get_open_api_repository", lambda: repo)

    with pytest.raises(HTTPException) as exc_info:
        await open_api_auth.authenticate_open_api_request(
            _request(),
            required_scope="messages:create",
        )

    assert exc_info.value.status_code == 403
    assert repo.used == []


@pytest.mark.asyncio
async def test_authenticate_open_api_request_binds_state_and_marks_key_used(
    monkeypatch,
):
    repo = _repo_for_token(app_overrides={"ip_allowlist": ["198.51.100.7"]})
    monkeypatch.setattr(open_api_auth, "get_open_api_repository", lambda: repo)
    request = _request(client=("198.51.100.7", 12345))

    context = await open_api_auth.authenticate_open_api_request(
        request,
        required_scope="messages:create",
    )

    assert context.api_key["id"] == "key-1"
    assert request.state.user_id == "user-1"
    assert request.state.role == "open_app"
    assert request.state.open_app_id == "app-1"
    assert request.state.open_publication_id == "pub-1"
    assert request.state.open_api_key_id == "key-1"
    assert request.state.open_auth_context is context
    assert repo.used == [("key-1", "198.51.100.7")]


@pytest.mark.asyncio
async def test_authenticate_open_api_request_ignores_spoofed_real_ip_header(
    monkeypatch,
):
    repo = _repo_for_token(app_overrides={"ip_allowlist": ["198.51.100.7"]})
    monkeypatch.setattr(open_api_auth, "get_open_api_repository", lambda: repo)

    with pytest.raises(HTTPException) as exc_info:
        await open_api_auth.authenticate_open_api_request(
            _request(
                client=("10.0.0.99", 12345),
                headers=[(b"x-real-ip", b"198.51.100.7")],
            ),
            required_scope="messages:create",
        )

    assert exc_info.value.status_code == 403
    assert repo.used == []


@pytest.mark.asyncio
async def test_authenticate_open_api_request_fails_closed_on_bad_stored_json(
    monkeypatch,
):
    class BadRepo:
        def get_api_key_by_hash(self, _key_hash: str):
            raise ValueError("scopes must be a list")

    monkeypatch.setattr(open_api_auth, "get_open_api_repository", lambda: BadRepo())

    with pytest.raises(HTTPException) as exc_info:
        await open_api_auth.authenticate_open_api_request(
            _request(),
            required_scope="messages:create",
        )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key_overrides",
    [
        {"status": "revoked"},
        {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)},
    ],
)
async def test_authenticate_open_api_request_rejects_revoked_or_expired_keys(
    monkeypatch,
    key_overrides,
):
    repo = _repo_for_token(key_overrides=key_overrides)
    monkeypatch.setattr(open_api_auth, "get_open_api_repository", lambda: repo)

    with pytest.raises(HTTPException) as exc_info:
        await open_api_auth.authenticate_open_api_request(
            _request(),
            required_scope="messages:create",
        )

    assert exc_info.value.status_code == 401
    assert repo.used == []


@pytest.mark.asyncio
async def test_open_api_middleware_authenticates_even_when_auth_is_disabled(
    monkeypatch,
):
    async def fake_open_auth(request: Request, required_scope: str):
        assert required_scope == "messages:create"
        request.state.user_id = "user-1"
        request.state.role = "open_app"

    monkeypatch.setattr(app_auth, "is_auth_enabled", lambda: False)
    monkeypatch.setattr(
        app_auth,
        "authenticate_open_api_request",
        fake_open_auth,
        raising=False,
    )
    request = _request(token="qp_live_secret-token")
    middleware = app_auth.AuthMiddleware(app=lambda scope, receive, send: None)

    async def call_next(req: Request) -> Response:
        assert req.state.user_id == "user-1"
        assert req.state.role == "open_app"
        return Response("ok")

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_open_api_middleware_converts_auth_errors_to_json(monkeypatch):
    async def fake_open_auth(request: Request, required_scope: str):
        raise HTTPException(status_code=401, detail="Open API key required")

    monkeypatch.setattr(app_auth, "is_auth_enabled", lambda: False)
    monkeypatch.setattr(
        app_auth,
        "authenticate_open_api_request",
        fake_open_auth,
        raising=False,
    )
    request = _request(token=None)
    middleware = app_auth.AuthMiddleware(app=lambda scope, receive, send: None)

    async def call_next(_req: Request) -> Response:
        raise AssertionError("/api/open/ auth failures should not pass through")

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 401
    assert response.media_type == "application/json"
