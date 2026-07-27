# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.requests import Request
from starlette.responses import Response

from qwenpaw.app import auth, db


@pytest.fixture
def isolated_auth_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point auth.json and SQLite at an isolated test directory."""
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "true")
    monkeypatch.setattr(auth, "AUTH_FILE", tmp_path / "auth.json")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "qwenpaw.db")

    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        delattr(db._local, "conn")

    db.init_db()
    try:
        yield
    finally:
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
            delattr(db._local, "conn")


def test_first_registered_user_is_synced_as_admin(isolated_auth_store):
    token = auth.register_user("admin", "strong-password")

    assert token
    username = auth.verify_token(token)
    assert username == "admin"

    user = auth.resolve_authenticated_user(username)
    assert user is not None
    assert user["username"] == "admin"
    assert user["role"] == "admin"


def test_legacy_auth_json_user_is_migrated_to_db(isolated_auth_store):
    token = auth.register_user("admin", "strong-password")
    conn = db.get_db()
    conn.execute("DELETE FROM users")
    conn.commit()

    username = auth.verify_token(token)
    user = auth.resolve_authenticated_user(username)

    assert user is not None
    assert user["username"] == "admin"
    assert user["role"] == "admin"
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_middleware_accepts_registered_admin_token(isolated_auth_store):
    token = auth.register_user("admin", "strong-password")
    conn = db.get_db()
    conn.execute("DELETE FROM users")
    conn.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/user/agents",
            "raw_path": b"/api/user/agents",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
            "client": ("203.0.113.10", 12345),
            "scheme": "http",
            "server": ("127.0.0.1", 8088),
            "query_string": b"",
        },
    )
    middleware = auth.AuthMiddleware(app=lambda scope, receive, send: None)

    async def call_next(req: Request) -> Response:
        assert req.state.user == "admin"
        assert req.state.role == "admin"
        return Response("ok")

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_middleware_requires_auth_even_before_first_user(
    isolated_auth_store,
):
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/user/agents",
            "raw_path": b"/api/user/agents",
            "headers": [],
            "client": ("203.0.113.10", 12345),
            "scheme": "http",
            "server": ("127.0.0.1", 8088),
            "query_string": b"",
        },
    )
    middleware = auth.AuthMiddleware(app=lambda scope, receive, send: None)

    async def call_next(_req: Request) -> Response:
        raise AssertionError("protected API request should not pass through")

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_desktop_update_endpoint_is_public(isolated_auth_store):
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/desktop/update",
            "raw_path": b"/api/desktop/update",
            "headers": [],
            "client": ("203.0.113.10", 12345),
            "scheme": "http",
            "server": ("127.0.0.1", 8088),
            "query_string": b"platform=mac&version=1.1.9",
        },
    )
    middleware = auth.AuthMiddleware(app=lambda scope, receive, send: None)

    async def call_next(_req: Request) -> Response:
        return Response("ok")

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_preview_subresource_can_reuse_referer_token(isolated_auth_store):
    token = auth.register_user("admin", "strong-password")
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/user/workspace/preview/__qwenpaw_preview__/default/chat-1/style.css",
            "raw_path": b"/api/user/workspace/preview/__qwenpaw_preview__/default/chat-1/style.css",
            "headers": [
                (
                    b"referer",
                    (
                        "http://localhost:8088/api/user/workspace/preview/"
                        "__qwenpaw_preview__/default/chat-1/index.html"
                        f"?token={token}"
                    ).encode(),
                ),
            ],
            "client": ("203.0.113.10", 12345),
            "scheme": "http",
            "server": ("127.0.0.1", 8088),
            "query_string": b"",
        },
    )
    middleware = auth.AuthMiddleware(app=lambda scope, receive, send: None)

    async def call_next(req: Request) -> Response:
        assert req.state.user == "admin"
        return Response("ok")

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
