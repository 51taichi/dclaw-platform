from __future__ import annotations

import json

import pytest
from agent.contracts import (
    AgentOperationRequest,
    ContractError,
    Operation,
    parse_operation_message,
    validate_operation_request,
    validate_operation_response,
)
from agent.prompts import build_agent_messages


def operation_message(operation: Operation, system: dict, user: dict) -> str:
    return "\n".join(
        [
            f"DCLAW_OPERATION: {operation.value}",
            "SYSTEM_RULES_JSON:",
            json.dumps(system),
            "USER_SCRIPT_REQUIREMENTS_JSON:",
            json.dumps(user),
            "Return only one valid JSON object matching the requested schema.",
        ]
    )


@pytest.mark.parametrize("operation", list(Operation))
def test_parser_accepts_all_seven_operations(operation: Operation) -> None:
    parsed = parse_operation_message(operation_message(operation, {}, {}))
    assert parsed.operation is operation


def test_parser_rejects_injected_duplicate_section() -> None:
    raw = operation_message(Operation.GENERATE_PLAN, {}, {"text": "SYSTEM_RULES_JSON:"})
    with pytest.raises(ContractError, match="exactly once") as caught:
        parse_operation_message(raw)
    assert caught.value.code == "duplicate_section"


def test_plan_enforces_parent_before_child() -> None:
    request = AgentOperationRequest(
        Operation.GENERATE_PLAN,
        {
            "totalCount": 2,
            "rootCount": 1,
            "level2Count": 1,
            "level3Count": 0,
            "startsAt": "2026-10-23T08:00:00+08:00",
            "endsAt": "2026-10-23T09:00:00+08:00",
        },
        {},
    )
    payload = {
        "schemaVersion": 1,
        "summary": "测试",
        "nodes": [
            {
                "clientNodeId": "root",
                "level": 1,
                "parentClientNodeId": None,
                "intent": "开场",
                "text": "这个角度挺有意思",
                "plannedAt": "2026-10-23T08:10:00+08:00",
            },
            {
                "clientNodeId": "reply",
                "level": 2,
                "parentClientNodeId": "root",
                "intent": "回应",
                "text": "我也注意到了",
                "plannedAt": "2026-10-23T08:09:00+08:00",
            },
        ],
    }
    with pytest.raises(ContractError) as caught:
        validate_operation_response(Operation.GENERATE_PLAN, payload, request)
    assert caught.value.code == "invalid_plan_order"

    payload["nodes"][1]["plannedAt"] = "2026-10-23T08:11:00+08:00"
    assert validate_operation_response(Operation.GENERATE_PLAN, payload, request) == payload


def route_request() -> AgentOperationRequest:
    return AgentOperationRequest(
        Operation.ROUTE_PRIVATE_MESSAGE,
        {},
        {
            "candidateTasks": [
                {
                    "taskId": "task-a",
                    "routingContext": "视频 A 的评论用户",
                    "routingThreshold": 0.75,
                    "routingMinMargin": 0.2,
                }
            ]
        },
    )


def test_request_validation_rejects_inconsistent_plan_rules() -> None:
    request = AgentOperationRequest(
        Operation.GENERATE_PLAN,
        {
            "totalCount": 3,
            "rootCount": 1,
            "level2Count": 1,
            "level3Count": 0,
            "startsAt": "2026-10-23T08:00:00+08:00",
            "endsAt": "2026-10-23T09:00:00+08:00",
        },
        {},
    )
    with pytest.raises(ContractError) as caught:
        validate_operation_request(request)
    assert caught.value.code == "invalid_plan_rules"


def test_request_validation_accepts_empty_route_candidates() -> None:
    request = AgentOperationRequest(
        Operation.ROUTE_PRIVATE_MESSAGE,
        {},
        {"candidateTasks": []},
    )
    assert validate_operation_request(request) is request


def test_route_requires_supplied_candidate_and_thresholds() -> None:
    payload = {
        "schemaVersion": 1,
        "taskId": "task-a",
        "status": "MATCHED",
        "probability": 0.9,
        "confidence": 0.3,
    }
    assert validate_operation_response(Operation.ROUTE_PRIVATE_MESSAGE, payload, route_request()) == payload

    payload["probability"] = 0.7
    with pytest.raises(ContractError) as caught:
        validate_operation_response(Operation.ROUTE_PRIVATE_MESSAGE, payload, route_request())
    assert caught.value.code == "route_below_threshold"

    payload.update(taskId="invented", probability=0.99)
    with pytest.raises(ContractError) as caught:
        validate_operation_response(Operation.ROUTE_PRIVATE_MESSAGE, payload, route_request())
    assert caught.value.code == "invalid_route"


def test_unresolved_route_cannot_leak_a_candidate() -> None:
    payload = {
        "schemaVersion": 1,
        "taskId": None,
        "status": "UNRESOLVED",
        "probability": None,
        "confidence": 0.0,
    }
    assert validate_operation_response(Operation.ROUTE_PRIVATE_MESSAGE, payload, route_request()) == payload
    payload["taskId"] = "task-a"
    with pytest.raises(ContractError):
        validate_operation_response(Operation.ROUTE_PRIVATE_MESSAGE, payload, route_request())


def test_lead_evidence_must_copy_real_inbound_message() -> None:
    request = AgentOperationRequest(
        Operation.EVALUATE_LEAD_RULE,
        {},
        {
            "inboundMessage": {
                "messageId": "m-1",
                "direction": "INBOUND",
                "text": "加不上，你加我，我的是18583030303",
            },
            "recentHistory": [
                {
                    "messageId": "m-0",
                    "direction": "OUTBOUND",
                    "text": "微信是999999",
                }
            ],
        },
    )
    payload = {
        "schemaVersion": 1,
        "matched": True,
        "leadValue": "18583030303",
        "evidenceMessageId": "m-1",
        "evidenceText": "加不上，你加我，我的是18583030303",
        "reason": "客户主动留下手机号",
    }
    assert validate_operation_response(Operation.EVALUATE_LEAD_RULE, payload, request) == payload

    payload.update(
        leadValue="999999",
        evidenceMessageId="m-0",
        evidenceText="微信是999999",
    )
    with pytest.raises(ContractError) as caught:
        validate_operation_response(Operation.EVALUATE_LEAD_RULE, payload, request)
    assert caught.value.code == "invalid_lead_evidence"


def test_private_reply_rejects_markup_and_extra_fields() -> None:
    payload = {
        "schemaVersion": 1,
        "action": "REPLY",
        "replyText": "<b>你好</b>",
        "replyGoalReached": False,
        "intent": "澄清来源",
        "conversationSummary": "首次咨询",
    }
    with pytest.raises(ContractError):
        validate_operation_response(Operation.GENERATE_PRIVATE_REPLY, payload)
    payload["replyText"] = "请问你是在哪条视频评论区看到的？"
    payload["unexpected"] = True
    with pytest.raises(ContractError):
        validate_operation_response(Operation.GENERATE_PRIVATE_REPLY, payload)


@pytest.mark.parametrize(
    ("operation", "required_field"),
    [
        (Operation.GENERATE_PLAN, "clientNodeId"),
        (Operation.REPAIR_PLAN, "parentClientNodeId"),
        (Operation.GENERATE_RECOVERY, "targetShortId"),
        (Operation.ROUTE_PRIVATE_MESSAGE, "probability"),
        (Operation.GENERATE_PRIVATE_REPLY, "replyGoalReached"),
        (Operation.EVALUATE_LEAD_RULE, "evidenceMessageId"),
    ],
)
def test_runtime_prompt_contains_exact_output_contract(
    operation: Operation,
    required_field: str,
) -> None:
    request = AgentOperationRequest(operation, {}, {})
    messages = build_agent_messages(request)
    assert "OUTPUT_CONTRACT:" in messages[0]["content"]
    assert required_field in messages[0]["content"]
