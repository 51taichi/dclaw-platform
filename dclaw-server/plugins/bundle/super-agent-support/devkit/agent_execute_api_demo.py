"""Strict reference calls for the shared sealed-Agent model boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import validate


ROOT = Path(__file__).parent / "schemas"


def _schema(name: str, kind: str) -> dict[str, Any]:
    return json.loads(
        (ROOT / name / f"{kind}.schema.json").read_text(encoding="utf-8"),
    )


async def execute_text(host: Any, messages: list[dict[str, Any]]) -> dict[str, Any]:
    request = {"messages": messages}
    validate(request, _schema("agent-execute-v1", "request"))
    result = await host.call("agent.execute", request)
    validate(result, _schema("agent-execute-v1", "response"))
    return result


async def execute_json(host: Any, messages: list[dict[str, Any]]) -> dict[str, Any]:
    request = {"messages": messages, "response_format": "json_object"}
    validate(request, _schema("agent-execute-v1", "request"))
    result = await host.call("agent.execute", request)
    validate(result, _schema("agent-execute-v1", "response"))
    return result


async def execute_agent_loop(
    host: Any,
    messages: list[dict[str, Any]],
    instruction: str,
    *,
    require_interaction: bool = False,
) -> dict[str, Any]:
    request = {
        "messages": messages,
        "execution_mode": "agent_loop",
        "instruction": instruction,
        "require_interaction": require_interaction,
    }
    validate(request, _schema("agent-execute-v1", "request"))
    result = await host.call("agent.execute", request)
    validate(result, _schema("agent-execute-v1", "response"))
    return result


async def execute_v2_agent_loop(
    host: Any,
    messages: list[dict[str, Any]],
    instruction: str | None = None,
    *,
    require_interaction: bool = False,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "messages": messages,
        "require_interaction": require_interaction,
    }
    if instruction is not None:
        request["instruction"] = instruction
    validate(request, _schema("agent-execute-v2", "request"))
    result = await host.call("agent.execute", request)
    validate(result, _schema("agent-execute-v2", "response"))
    return result


async def execute_v2_candidate(
    host: Any,
    messages: list[dict[str, Any]],
    *,
    json_object: bool = False,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "messages": messages,
        "execution_mode": "candidate",
    }
    if json_object:
        request["response_format"] = "json_object"
    validate(request, _schema("agent-execute-v2", "request"))
    result = await host.call("agent.execute", request)
    validate(result, _schema("agent-execute-v2", "response"))
    return result


async def fail_turn(
    host: Any,
    invocation_id: str,
    error_code: str,
    diagnostic_ref: str | None = None,
) -> dict[str, Any]:
    request = {"invocation_id": invocation_id, "error_code": error_code}
    if diagnostic_ref is not None:
        request["diagnostic_ref"] = diagnostic_ref
    validate(request, _schema("runtime-fail-v1", "request"))
    result = await host.call("runtime.fail", request)
    validate(result, _schema("runtime-fail-v1", "response"))
    return result
