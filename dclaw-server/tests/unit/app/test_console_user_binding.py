# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.app.routers.console import _bind_console_payload_to_request_user


def test_console_payload_user_id_comes_from_authenticated_request() -> None:
    request = SimpleNamespace(state=SimpleNamespace(user_id=42))
    payload = {
        "sender_id": "default",
        "meta": {
            "user_id": "default",
            "session_id": "chat-1",
        },
    }

    _bind_console_payload_to_request_user(request, payload)

    assert payload["sender_id"] == "42"
    assert payload["meta"]["user_id"] == "42"
