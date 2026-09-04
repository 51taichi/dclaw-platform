from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from qwenpaw.app.routers import realtime_stt


def test_realtime_stt_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("DCLAW_REALTIME_STT_ENABLED", raising=False)
    app = FastAPI()
    app.include_router(realtime_stt.realtime_stt_router, prefix="/api")

    with TestClient(app) as client:
        try:
            with client.websocket_connect(
                "/api/user/workspace/realtime-transcribe",
            ):
                pass
        except WebSocketDisconnect as exc:
            assert exc.code == 1008
        else:
            raise AssertionError("disabled realtime STT accepted a connection")


def test_authenticate_requires_a_valid_resolvable_user(monkeypatch) -> None:
    monkeypatch.setattr(realtime_stt, "verify_token", lambda token: "alice")
    monkeypatch.setattr(
        realtime_stt,
        "resolve_authenticated_user",
        lambda username: {"id": "17", "username": username},
    )

    assert realtime_stt.authenticate_browser_token("valid") == {
        "id": "17",
        "username": "alice",
    }

    monkeypatch.setattr(realtime_stt, "verify_token", lambda token: None)
    assert realtime_stt.authenticate_browser_token("invalid") is None

    monkeypatch.setattr(realtime_stt, "verify_token", lambda token: "missing")
    monkeypatch.setattr(
        realtime_stt,
        "resolve_authenticated_user",
        lambda username: None,
    )
    assert realtime_stt.authenticate_browser_token("orphaned") is None


def test_browser_token_is_decoded_from_websocket_subprotocol() -> None:
    assert (
        realtime_stt.browser_token_from_protocol_header(
            "dclaw-stt, dclaw-auth.c2VjcmV0LnRva2Vu",
        )
        == "secret.token"
    )
    assert realtime_stt.browser_token_from_protocol_header("dclaw-stt") == ""
    assert (
        realtime_stt.browser_token_from_protocol_header(
            "dclaw-auth.not-valid-encoding!",
        )
        == ""
    )


def test_enabled_socket_rejects_an_invalid_user_token(monkeypatch) -> None:
    monkeypatch.setenv("DCLAW_REALTIME_STT_ENABLED", "true")
    monkeypatch.setattr(realtime_stt, "verify_token", lambda token: None)
    app = FastAPI()
    app.include_router(realtime_stt.realtime_stt_router, prefix="/api")

    with TestClient(app) as client:
        try:
            with client.websocket_connect(
                "/api/user/workspace/realtime-transcribe",
                subprotocols=["dclaw-stt", "dclaw-auth.aW52YWxpZA"],
            ):
                pass
        except WebSocketDisconnect as exc:
            assert exc.code == 1008
        else:
            raise AssertionError("invalid browser token accepted")
