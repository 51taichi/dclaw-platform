from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.routers import open_api, open_api_admin


def test_sealed_publication_policy_is_forced_server_side(monkeypatch):
    monkeypatch.setattr(
        open_api_admin,
        "get_sealed_agent_registry",
        lambda: SimpleNamespace(is_sealed=lambda agent_id: agent_id == "luyu"),
    )

    assert open_api_admin._target_publication_policy("agent", "luyu") == {
        "allowed_capability": "invoke_only",
        "response_policy": "sealed",
    }
    assert open_api_admin._target_publication_policy("agent", "ordinary") == {
        "allowed_capability": "standard",
        "response_policy": "standard",
    }


def test_disabled_or_unreleased_sealed_target_is_not_publishable(monkeypatch):
    record = SimpleNamespace(enabled=False, active_release_id=None)
    monkeypatch.setattr(
        open_api_admin,
        "get_sealed_agent_registry",
        lambda: SimpleNamespace(
            is_sealed=lambda agent_id: True,
            get_agent=lambda agent_id: record,
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        open_api_admin._assert_target_exists("agent", "luyu")

    assert exc_info.value.status_code == 400
    assert "unavailable" in exc_info.value.detail.lower()


def test_sealed_stream_serializer_allows_text_and_hides_internal_events():
    text = 'data: {"type":"response.output_text.delta","delta":"hello"}\n\n'
    tool = 'data: {"type":"tool.call","path":"/private/AGENTS.md"}\n\n'
    error = 'data: {"error":"trace at /private/AGENTS.md"}\n\n'

    assert open_api._sanitize_sealed_stream_event(text) == text
    assert open_api._sanitize_sealed_stream_event(tool) is None
    sanitized_error = open_api._sanitize_sealed_stream_event(error)
    assert json.loads(sanitized_error[6:].strip()) == {
        "type": "response.failed",
        "error": "sealed_agent_failed",
    }
    assert "/private" not in sanitized_error


def test_sealed_stream_serializer_allows_null_error_on_success_event():
    completed = (
        'data: {"type":"response.completed","error":null,'
        '"response":{"status":"completed"}}\n\n'
    )

    assert open_api._sanitize_sealed_stream_event(completed) == completed


def test_sealed_stream_serializer_converts_completed_assistant_text():
    native = (
        'data: {"object":"message","status":"completed","error":null,'
        '"type":"message","role":"assistant","content":['
        '{"type":"text","text":"陆羽你好"},'
        '{"type":"image","image_url":"/private/source.png"}]}'
        "\n\n"
    )

    public = open_api._sanitize_sealed_stream_event(native)

    assert json.loads(public[6:].strip()) == {
        "type": "response.output_text.delta",
        "delta": "陆羽你好",
    }
    assert "/private/source.png" not in public


def test_sealed_stream_serializer_drops_completed_tool_message():
    tool = (
        'data: {"object":"message","status":"completed","error":null,'
        '"type":"function_call_output","role":"tool","content":['
        '{"type":"text","text":"/private/AGENTS.md"}]}'
        "\n\n"
    )

    assert open_api._sanitize_sealed_stream_event(tool) is None
