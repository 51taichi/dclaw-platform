from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from devkit.agent_execute_api_demo import (
    execute_agent_loop,
    execute_json,
    execute_text,
    execute_v2_agent_loop,
    execute_v2_candidate,
    fail_turn,
)
from super_agent.orchestration_contract import WorkspaceTurnFailure


ROOT = Path(__file__).parents[1] / "devkit" / "schemas"


def _validator(name: str) -> Draft202012Validator:
    schema = json.loads((ROOT / name / "request.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_agent_execute_schema_accepts_three_modes_and_rejects_mixtures():
    validator = _validator("agent-execute-v1")
    messages = [{"role": "user", "content": "hello"}]
    validator.validate({"messages": messages})
    validator.validate({"messages": messages, "response_format": "json_object"})
    validator.validate({
        "messages": messages, "execution_mode": "agent_loop",
        "instruction": "Use the governed tools.",
    })
    with pytest.raises(ValidationError):
        validator.validate({"messages": messages, "instruction": "invalid"})
    with pytest.raises(ValidationError):
        validator.validate({
            "messages": messages, "execution_mode": "agent_loop",
            "instruction": "invalid", "response_format": "json_object",
        })


def test_v2_agent_loop_can_disable_legacy_interaction_tools():
    validator = _validator("agent-execute-v2")
    messages = [{"role": "user", "content": "hello"}]
    validator.validate({
        "messages": messages, "execution_mode": "agent_loop",
        "instruction": "Use permitted tools.",
        "interaction_tool_access": "disabled",
    })
    with pytest.raises(ValidationError):
        validator.validate({
            "messages": messages, "execution_mode": "candidate",
            "interaction_tool_access": "disabled",
        })
    with pytest.raises(ValidationError):
        _validator("agent-execute-v1").validate({
            "messages": messages, "execution_mode": "agent_loop",
            "instruction": "Use tools.",
            "interaction_tool_access": "disabled",
        })


def test_runtime_fail_codes_are_backward_compatible_and_bounded():
    validator = _validator("runtime-fail-v1")
    for code in ("runtime_failed", "INVALID_TURN_RESULT", "HOST.AGENT_EXECUTE_FAILED"):
        validator.validate({"invocation_id": "invocation", "error_code": code})
        WorkspaceTurnFailure.model_validate({
            "invocation_id": "invocation", "error_code": code,
        })
    for code in ("free form", "host.failure", "HOST-FAILURE", "A" * 65):
        with pytest.raises(Exception):
            WorkspaceTurnFailure.model_validate({
                "invocation_id": "invocation", "error_code": code,
            })


@pytest.mark.asyncio
async def test_reference_demo_calls_exact_host_contracts():
    class Host:
        async def call(self, capability, arguments):
            if capability == "runtime.fail":
                return {"accepted": True}
            return {
                "message": {"name": "agent", "role": "assistant", "content": "ok"},
                "text": "ok",
            }

    host = Host()
    messages = [{"role": "user", "content": "hello"}]
    assert (await execute_text(host, messages))["text"] == "ok"
    assert (await execute_json(host, messages))["text"] == "ok"
    assert (await execute_agent_loop(host, messages, "Use tools."))["text"] == "ok"
    assert (await execute_v2_agent_loop(host, messages))["text"] == "ok"
    assert (await execute_v2_candidate(host, messages, json_object=True))["text"] == "ok"
    assert (await fail_turn(
        host, "invocation", "HOST.AGENT_EXECUTE_FAILED",
    )) == {"accepted": True}
