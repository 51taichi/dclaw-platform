from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from agent.runtime import create_runtime


def message(operation: str, user: dict | None = None) -> str:
    return "\n".join(
        [
            f"DCLAW_OPERATION: {operation}",
            "SYSTEM_RULES_JSON:",
            "{}",
            "USER_SCRIPT_REQUIREMENTS_JSON:",
            json.dumps(user or {}),
            "Return only one valid JSON object matching the requested schema.",
        ]
    )


@dataclass
class Request:
    normalized_input: dict[str, Any]
    invocation_id: str = "inv-1"


class FakeHost:
    def __init__(self, candidates: list[object] | None = None, fail_context: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.candidates = list(candidates or [])
        self.fail_context = fail_context

    async def call(self, name: str, arguments: dict[str, Any]) -> object:
        self.calls.append((name, arguments))
        if name == "session.context":
            if self.fail_context:
                raise RuntimeError("unavailable")
            return {"session_id": "trusted"}
        if name == "agent.execute":
            candidate = self.candidates.pop(0)
            return candidate
        return {"accepted": True}


def request_for(raw: str) -> Request:
    return Request({"messages": [{"role": "user", "content": raw}]})


def call_names(host: FakeHost) -> list[str]:
    return [name for name, _ in host.calls]


def test_health_is_deterministic_and_completes_once() -> None:
    host = FakeHost()
    asyncio.run(create_runtime().handle(request_for(message("HEALTH_CHECK")), host))
    assert "agent.execute" not in call_names(host)
    assert call_names(host).count("runtime.complete") == 1
    assert "runtime.fail" not in call_names(host)
    complete = next(arguments for name, arguments in host.calls if name == "runtime.complete")
    assert json.loads(complete["message"]["content"]) == {"ok": True, "capabilityVersion": "2"}


def test_invalid_candidate_is_repaired_once() -> None:
    valid = {
        "schemaVersion": 1,
        "taskId": None,
        "status": "UNRESOLVED",
        "probability": None,
        "confidence": 0.0,
    }
    host = FakeHost([{"text": "not json"}, {"text": json.dumps(valid)}])
    raw = message(
        "ROUTE_PRIVATE_MESSAGE",
        {
            "candidateTasks": [
                {
                    "taskId": "task-a",
                    "routingContext": "video a",
                    "routingThreshold": 0.8,
                    "routingMinMargin": 0.2,
                }
            ]
        },
    )
    asyncio.run(create_runtime().handle(request_for(raw), host))
    assert call_names(host).count("agent.execute") == 2
    assert call_names(host).count("runtime.complete") == 1
    assert "runtime.fail" not in call_names(host)
    second_messages = [args for name, args in host.calls if name == "agent.execute"][1]["messages"]
    assert second_messages[-1]["role"] == "system"
    assert "invalid_agent_output" in second_messages[-1]["content"]


def test_two_invalid_candidates_fail_once() -> None:
    host = FakeHost([{"text": "bad"}, {"text": "still bad"}])
    asyncio.run(create_runtime().handle(request_for(message("GENERATE_PRIVATE_REPLY")), host))
    assert call_names(host).count("runtime.fail") == 1
    assert "runtime.complete" not in call_names(host)


def test_invalid_protocol_does_not_call_model() -> None:
    host = FakeHost()
    asyncio.run(create_runtime().handle(request_for("hello"), host))
    assert "agent.execute" not in call_names(host)
    assert call_names(host).count("runtime.fail") == 1


def test_invalid_business_rules_do_not_call_model() -> None:
    host = FakeHost()
    raw = "\n".join(
        [
            "DCLAW_OPERATION: GENERATE_PLAN",
            "SYSTEM_RULES_JSON:",
            json.dumps(
                {
                    "totalCount": 2,
                    "rootCount": 1,
                    "level2Count": 0,
                    "level3Count": 0,
                    "startsAt": "2026-10-23T09:00:00+08:00",
                    "endsAt": "2026-10-23T08:00:00+08:00",
                }
            ),
            "USER_SCRIPT_REQUIREMENTS_JSON:",
            "{}",
        ]
    )
    asyncio.run(create_runtime().handle(request_for(raw), host))
    assert "agent.execute" not in call_names(host)
    assert call_names(host).count("runtime.fail") == 1


def test_session_context_failure_is_reported_without_model_call() -> None:
    host = FakeHost(fail_context=True)
    asyncio.run(create_runtime().handle(request_for(message("HEALTH_CHECK")), host))
    assert "agent.execute" not in call_names(host)
    assert call_names(host).count("runtime.fail") == 1
    failure = next(arguments for name, arguments in host.calls if name == "runtime.fail")
    assert failure["diagnostic_ref"] == "session_context_unavailable"
