from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent_sources.douyin_engagement_agent.agent.runtime import (
    create_runtime,
)


def _message(operation: str, system: dict, user: dict) -> str:
    return "\n".join(
        [
            f"DCLAW_OPERATION: {operation}",
            "SYSTEM_RULES_JSON:",
            json.dumps(system, ensure_ascii=False),
            "USER_SCRIPT_REQUIREMENTS_JSON:",
            json.dumps(user, ensure_ascii=False),
            "Return only one valid JSON object matching the requested schema.",
        ]
    )


def _request(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        invocation_id="inv-1",
        normalized_input={
            "messages": [{"role": "user", "name": "customer", "content": content}],
        },
    )


class FakeHost:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls: list[tuple[str, dict]] = []

    async def call(self, capability: str, arguments: dict):
        self.calls.append((capability, arguments))
        if capability == "session.context":
            return {"session_id": "session-1", "history_size": 2}
        if capability == "agent.execute":
            return {"text": self.outputs.pop(0)}
        return {"accepted": True}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "output"),
    [
        (
            _message("HEALTH_CHECK", {}, {}),
            {"ok": True, "capabilityVersion": "2"},
        ),
        (
            _message(
                "GENERATE_PLAN",
                {
                    "totalCount": 1,
                    "rootCount": 1,
                    "level2Count": 0,
                    "level3Count": 0,
                    "startsAt": "2026-10-01T01:00:00+00:00",
                    "endsAt": "2026-10-01T02:00:00+00:00",
                },
                {"goal": "自然讨论"},
            ),
            {
                "schemaVersion": 1,
                "summary": "单条评论",
                "nodes": [
                    {
                        "clientNodeId": "root",
                        "level": 1,
                        "parentClientNodeId": None,
                        "intent": "提出观点",
                        "text": "测试评论",
                        "plannedAt": "2026-10-01T01:05:00+00:00",
                    }
                ],
            },
        ),
        (
            _message("REPAIR_PLAN", {}, {"invalidPlan": {}}),
            {
                "schemaVersion": 1,
                "summary": "修复计划",
                "nodes": [
                    {
                        "clientNodeId": "root",
                        "level": 1,
                        "parentClientNodeId": None,
                        "intent": "提出观点",
                        "text": "修复评论",
                        "plannedAt": "2026-10-01T01:05:00+00:00",
                    }
                ],
            },
        ),
        (
            _message(
                "GENERATE_RECOVERY",
                {"allowedNewLevels": [1, 2]},
                {"nearbyComments": [{"shortId": "near-1", "text": "附近"}]},
            ),
            {
                "schemaVersion": 1,
                "newLevel": 2,
                "targetType": "NEARBY_COMMENT",
                "targetShortId": "near-1",
                "intent": "自然回应",
                "text": "临时回复",
            },
        ),
        (
            _message(
                "GENERATE_PRIVATE_REPLY",
                {"maxLength": 1000},
                {"inboundMessage": {"text": "你好"}},
            ),
            {
                "schemaVersion": 1,
                "replyText": "你好，请问有什么可以帮你？",
                "intent": "回应问候",
                "conversationSummary": "用户问候",
            },
        ),
    ],
)
async def test_runtime_routes_and_completes_all_operations(content, output) -> None:
    host = FakeHost([json.dumps(output, ensure_ascii=False)])

    await create_runtime().handle(_request(content), host)

    assert [capability for capability, _ in host.calls] == [
        "session.context",
        "runtime.trace",
        "agent.execute",
        "runtime.trace",
        "runtime.complete",
    ]
    completion = host.calls[-1][1]
    assert completion["invocation_id"] == "inv-1"
    assert json.loads(completion["message"]["content"]) == output
    assert completion["message"]["role"] == "assistant"


@pytest.mark.asyncio
async def test_runtime_repairs_once_after_invalid_model_json() -> None:
    valid = {
        "schemaVersion": 1,
        "replyText": "有效回复",
        "intent": "回答",
        "conversationSummary": "咨询",
    }
    host = FakeHost(["not-json", json.dumps(valid, ensure_ascii=False)])
    request = _request(
        _message("GENERATE_PRIVATE_REPLY", {}, {"inboundMessage": {"text": "你好"}})
    )

    await create_runtime().handle(request, host)

    execute_calls = [arguments for capability, arguments in host.calls if capability == "agent.execute"]
    assert len(execute_calls) == 2
    assert "previous output was invalid" in execute_calls[1]["messages"][-1]["content"]
    assert host.calls[-1][0] == "runtime.complete"


@pytest.mark.asyncio
async def test_runtime_fails_closed_after_second_invalid_output() -> None:
    host = FakeHost(["not-json", "still-not-json"])
    request = _request(
        _message("GENERATE_PRIVATE_REPLY", {}, {"inboundMessage": {"text": "你好"}})
    )

    await create_runtime().handle(request, host)

    assert host.calls[-1][0] == "runtime.fail"
    assert host.calls[-1][1] == {
        "invocation_id": "inv-1",
        "error_code": "runtime_failed",
        "diagnostic_ref": "invalid_agent_output",
    }
    assert not any(capability == "runtime.complete" for capability, _ in host.calls)


def test_profile_declares_only_bounded_runtime_capabilities() -> None:
    profile = json.loads(
        (
            Path(__file__).parents[4]
            / "agent_sources/douyin_engagement_agent/agent/agent.json"
        ).read_text(encoding="utf-8")
    )

    assert profile["orchestration"]["required_host_capabilities"] == [
        "agent.execute",
        "session.context",
        "runtime.trace",
        "runtime.complete",
        "runtime.fail",
    ]
