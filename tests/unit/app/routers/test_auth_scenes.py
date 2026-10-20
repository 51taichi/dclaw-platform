from __future__ import annotations

import pytest
from starlette.requests import Request

from qwenpaw.app.routers import auth as auth_router


def _request(token: str = "token") -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        },
    )


@pytest.mark.asyncio
async def test_verify_returns_configured_ai_customer_service_scene(
    monkeypatch,
):
    monkeypatch.setattr(auth_router, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth_router, "verify_token", lambda token: "alice")
    monkeypatch.setattr(
        auth_router,
        "resolve_authenticated_user",
        lambda username: {
            "role": "user",
            "ai_customer_service_url": (
                "https://service.example.com/console/?workspace=alice"
            ),
        },
    )

    result = await auth_router.verify(_request())

    assert result["scenes"] == [
        {
            "key": "ai-customer-service",
            "title": "AI客服",
            "url": "https://service.example.com/console/?workspace=alice",
        },
    ]


@pytest.mark.asyncio
async def test_verify_omits_unconfigured_scene(monkeypatch):
    monkeypatch.setattr(auth_router, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth_router, "verify_token", lambda token: "alice")
    monkeypatch.setattr(
        auth_router,
        "resolve_authenticated_user",
        lambda username: {"role": "user", "ai_customer_service_url": None},
    )

    result = await auth_router.verify(_request())

    assert result["scenes"] == []
