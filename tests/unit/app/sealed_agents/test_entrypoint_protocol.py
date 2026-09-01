from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from qwenpaw.app.sealed_agents.entrypoint_protocol import (
    HostCall,
    RuntimeFinal,
    RuntimeInvoke,
    validate_protocol_message,
)


def _invoke_payload() -> dict:
    return {
        "type": "runtime.invoke",
        "protocol_version": "1",
        "invocation_id": "inv-1",
        "message_id": "msg-1",
        "release": {
            "release_id": "release-1",
            "version": "1.1.0",
            "content_digest": f"sha256:{'a' * 64}",
        },
        "session": {
            "conversation_id": "open:app:pub:user:session",
            "user_id": "user-1",
            "channel": "open:app",
        },
        "input": {
            "role": "user",
            "content": "hello",
            "attachments": [],
        },
        "metadata": {"case": {"id": "case-1"}},
        "history": [],
        "runtime": {
            "diagnostics_authorized": False,
            "capabilities": ["agent.execute"],
        },
    }


def test_runtime_invoke_accepts_complete_literal_contract():
    request = RuntimeInvoke.model_validate(_invoke_payload())

    assert request.session.conversation_id == "open:app:pub:user:session"
    assert request.runtime.capabilities == ["agent.execute"]
    assert request.metadata == {"case": {"id": "case-1"}}


def test_runtime_invoke_rejects_unknown_fields_and_versions():
    unknown = _invoke_payload()
    unknown["agent_specific_stage"] = "S1"
    with pytest.raises(ValidationError):
        RuntimeInvoke.model_validate(unknown)

    wrong_version = _invoke_payload()
    wrong_version["protocol_version"] = "2"
    with pytest.raises(ValidationError):
        RuntimeInvoke.model_validate(wrong_version)


def test_host_call_rejects_unsupported_capability():
    with pytest.raises(ValidationError):
        HostCall(
            type="host.call",
            protocol_version="1",
            invocation_id="inv-1",
            call_id="call-1",
            capability="read.release.source",
            arguments={},
        )


def test_runtime_final_requires_one_non_empty_reply():
    with pytest.raises(ValidationError):
        RuntimeFinal(
            type="runtime.final",
            protocol_version="1",
            invocation_id="inv-1",
            message_id="final-1",
            reply="",
            artifacts=[],
            diagnostics=None,
        )


def test_protocol_message_rejects_oversized_payload():
    payload = _invoke_payload()
    payload["metadata"] = {"bulk": "x" * (1024 * 1024)}

    with pytest.raises(ValueError, match="too large"):
        validate_protocol_message(json.dumps(payload).encode())

