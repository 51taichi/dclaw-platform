# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, insert, select
from starlette.requests import Request
from starlette.responses import Response

from qwenpaw.app import auth, db
from qwenpaw.app.billing.service import get_wallet_service
from qwenpaw.app.storage.engine import get_app_engine, reset_app_engine_cache
from qwenpaw.app.storage.schema import (
    billing_ledger_entries,
    billing_wallets,
    create_all,
    users,
)


@pytest.fixture
def isolated_auth_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point auth.json and SQLite at an isolated test directory."""
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "true")
    monkeypatch.setattr(auth, "AUTH_FILE", tmp_path / "auth.json")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "qwenpaw.db")
    monkeypatch.setenv("QWENPAW_SQLITE_PATH", str(tmp_path / "qwenpaw.db"))
    reset_app_engine_cache()

    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        delattr(db._local, "conn")

    db.init_db()
    create_all(get_app_engine())
    try:
        yield
    finally:
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
            delattr(db._local, "conn")
        reset_app_engine_cache()


def test_first_registered_user_is_synced_as_admin(isolated_auth_store):
    token = auth.register_user("admin", "strong-password")

    assert token
    username = auth.verify_token(token)
    assert username == "admin"

    user = auth.resolve_authenticated_user(username)
    assert user is not None
    assert user["username"] == "admin"
    assert user["role"] == "admin"


def test_registration_creates_an_empty_personal_wallet(isolated_auth_store):
    auth.register_user("admin", "strong-password")
    user = auth.resolve_authenticated_user("admin")

    assert user is not None
    with get_app_engine().connect() as conn:
        wallet = (
            conn.execute(
                select(billing_wallets).where(
                    billing_wallets.c.owner_type == "user",
                    billing_wallets.c.owner_id == str(user["id"]),
                ),
            )
            .mappings()
            .one_or_none()
        )
        ledger_count = conn.scalar(
            select(func.count()).select_from(billing_ledger_entries),
        )

    assert wallet is not None
    assert (
        wallet["available_credits"],
        wallet["held_credits"],
        wallet["purchased_credits"],
        wallet["promotional_credits"],
        wallet["package_credits"],
    ) == (0, 0, 0, 0, 0)
    assert ledger_count == 0


def test_schema_bootstrap_idempotently_backfills_existing_users(
    isolated_auth_store,
):
    with get_app_engine().begin() as conn:
        user_id = conn.execute(
            insert(users).values(
                username="legacy-user",
                password_hash="hash",
                password_salt="salt",
                role="user",
            ),
        ).inserted_primary_key[0]

    create_all(get_app_engine())
    create_all(get_app_engine())

    with get_app_engine().connect() as conn:
        wallets = (
            conn.execute(
                select(billing_wallets).where(
                    billing_wallets.c.owner_type == "user",
                    billing_wallets.c.owner_id == str(user_id),
                ),
            )
            .mappings()
            .all()
        )
    assert len(wallets) == 1


def test_registration_retry_compensates_a_transient_wallet_failure(
    isolated_auth_store,
    monkeypatch,
):
    real_wallet_service = get_wallet_service()

    class FlakyWalletService:
        calls = 0

        def get_or_create_personal_wallet(self, user_id):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary wallet failure")
            return real_wallet_service.get_or_create_personal_wallet(user_id)

    flaky = FlakyWalletService()
    monkeypatch.setattr(auth, "get_wallet_service", lambda: flaky)

    with pytest.raises(RuntimeError, match="temporary wallet failure"):
        auth.register_user("admin", "strong-password")
    token = auth.register_user("admin", "strong-password")

    assert token is not None
    assert flaky.calls == 2
    user = auth.resolve_authenticated_user("admin")
    with get_app_engine().connect() as conn:
        wallet_count = conn.scalar(
            select(func.count())
            .select_from(billing_wallets)
            .where(
                billing_wallets.c.owner_type == "user",
                billing_wallets.c.owner_id == str(user["id"]),
            ),
        )
    assert wallet_count == 1


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
async def test_preview_subresource_can_reuse_referer_token(
    isolated_auth_store,
):
    token = auth.register_user("admin", "strong-password")
    preview_path = (
        "/api/user/workspace/preview/__qwenpaw_preview__/default/"
        "chat-1/style.css"
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": preview_path,
            "raw_path": preview_path.encode(),
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
