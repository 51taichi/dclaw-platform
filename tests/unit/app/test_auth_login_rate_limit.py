# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app import auth, db
from qwenpaw.app.routers.auth import router as auth_router


@pytest.fixture
def isolated_auth_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("QWENPAW_AUTH_ENABLED", "true")
    monkeypatch.setattr(auth, "AUTH_FILE", tmp_path / "auth.json")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "qwenpaw.db")
    monkeypatch.setattr(
        auth,
        "LOGIN_ATTEMPT_LIMITER",
        auth.LoginAttemptLimiter(
            window_seconds=60,
            lockout_seconds=30,
            max_failures_per_ip=10,
            max_failures_per_user=2,
        ),
    )

    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        delattr(db._local, "conn")

    db.init_db()
    auth.register_user("admin", "correct-password")

    app = FastAPI()
    app.include_router(auth_router, prefix="/api")
    try:
        yield TestClient(app)
    finally:
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
            delattr(db._local, "conn")


def test_login_rate_limiter_blocks_repeated_bad_passwords(isolated_auth_api):
    client = isolated_auth_api
    headers = {"X-Real-IP": "198.51.100.10"}

    first = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong"},
        headers=headers,
    )
    assert first.status_code == 401

    second = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "still-wrong"},
        headers=headers,
    )
    assert second.status_code == 429
    assert second.headers.get("retry-after") == "30"

    locked = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "correct-password"},
        headers=headers,
    )
    assert locked.status_code == 429


def test_successful_login_clears_previous_failures(isolated_auth_api):
    client = isolated_auth_api
    headers = {"X-Real-IP": "198.51.100.20"}

    bad = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong"},
        headers=headers,
    )
    assert bad.status_code == 401

    good = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "correct-password"},
        headers=headers,
    )
    assert good.status_code == 200
    assert good.json()["username"] == "admin"

    bad_again = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong"},
        headers=headers,
    )
    assert bad_again.status_code == 401
