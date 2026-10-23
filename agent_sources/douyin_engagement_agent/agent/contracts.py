"""Strict wire contracts for the Douyin engagement Agent."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

MAX_MESSAGE_CHARS = 262_144
MAX_PRIVATE_REPLY_CHARS = 1_000
_SYSTEM_MARKER = "SYSTEM_RULES_JSON:"
_USER_MARKER = "USER_SCRIPT_REQUIREMENTS_JSON:"
_RETURN_INSTRUCTION = "Return only one valid JSON object matching the requested schema."
_HTML_TAG = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")


class Operation(str, Enum):
    HEALTH_CHECK = "HEALTH_CHECK"
    GENERATE_PLAN = "GENERATE_PLAN"
    REPAIR_PLAN = "REPAIR_PLAN"
    GENERATE_RECOVERY = "GENERATE_RECOVERY"
    ROUTE_PRIVATE_MESSAGE = "ROUTE_PRIVATE_MESSAGE"
    GENERATE_PRIVATE_REPLY = "GENERATE_PRIVATE_REPLY"
    EVALUATE_LEAD_RULE = "EVALUATE_LEAD_RULE"


class ContractError(ValueError):
    """A stable, machine-readable contract validation error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AgentOperationRequest:
    operation: Operation
    system_rules: dict[str, Any]
    user_requirements: dict[str, Any]


def _object_json(raw: str, section: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractError("invalid_json", f"{section} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("invalid_json", f"{section} must be a JSON object")
    return value


def parse_operation_message(raw: str) -> AgentOperationRequest:
    if not isinstance(raw, str):
        raise ContractError("invalid_message", "operation message must be text")
    if len(raw) > MAX_MESSAGE_CHARS:
        raise ContractError("message_too_large", "operation message exceeds maximum size")

    operation_prefix = "DCLAW_OPERATION:"
    if raw.count(operation_prefix) != 1 or raw.count(_SYSTEM_MARKER) != 1 or raw.count(_USER_MARKER) != 1:
        known_counts = (raw.count(operation_prefix), raw.count(_SYSTEM_MARKER), raw.count(_USER_MARKER))
        code = "duplicate_section" if any(count > 1 for count in known_counts) else "missing_section"
        raise ContractError(code, "operation message sections must appear exactly once")

    operation_line, separator, remainder = raw.partition("\n")
    if not separator or not operation_line.startswith(operation_prefix):
        raise ContractError("missing_section", "operation header must be the first line")
    operation_name = operation_line[len(operation_prefix) :].strip()
    try:
        operation = Operation(operation_name)
    except ValueError as exc:
        raise ContractError("unknown_operation", f"unsupported operation: {operation_name}") from exc

    if not remainder.startswith(_SYSTEM_MARKER):
        raise ContractError("missing_section", "system rules section must follow the header")
    system_body, separator, user_body = remainder[len(_SYSTEM_MARKER) :].partition(_USER_MARKER)
    if not separator:
        raise ContractError("missing_section", "user requirements section is missing")

    user_body = user_body.strip()
    if user_body.endswith(_RETURN_INSTRUCTION):
        user_body = user_body[: -len(_RETURN_INSTRUCTION)].rstrip()
    return AgentOperationRequest(
        operation=operation,
        system_rules=_object_json(system_body.strip(), "system rules"),
        user_requirements=_object_json(user_body, "user requirements"),
    )


def _require_object(payload: object, code: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ContractError(code, "response must be a JSON object")
    return payload


def _nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _exact_keys(value: Mapping[str, Any], expected: set[str], code: str) -> None:
    if set(value) != expected:
        raise ContractError(code, "response fields do not match the operation contract")


def _number_between(value: object, minimum: float, maximum: float) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and minimum <= float(value) <= maximum
    )


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_operation_request(request: AgentOperationRequest) -> AgentOperationRequest:
    if request.operation in (Operation.GENERATE_PLAN, Operation.REPAIR_PLAN):
        counts = [
            request.system_rules.get("totalCount"),
            request.system_rules.get("rootCount"),
            request.system_rules.get("level2Count"),
            request.system_rules.get("level3Count"),
        ]
        starts_at = _parse_datetime(request.system_rules.get("startsAt"))
        ends_at = _parse_datetime(request.system_rules.get("endsAt"))
        if (
            not all(_nonnegative_int(value) for value in counts)
            or counts[0] == 0
            or counts[0] != sum(counts[1:])
            or starts_at is None
            or ends_at is None
            or starts_at >= ends_at
        ):
            raise ContractError("invalid_plan_rules", "plan system rules are incomplete or inconsistent")

    if request.operation is Operation.ROUTE_PRIVATE_MESSAGE:
        candidates = request.user_requirements.get("candidateTasks")
        if not isinstance(candidates, list) or len(candidates) > 2_000:
            raise ContractError("invalid_route_input", "candidate task list is invalid")
        task_ids: set[str] = set()
        for candidate in candidates:
            if (
                not isinstance(candidate, dict)
                or not _nonempty_text(candidate.get("taskId"))
                or candidate["taskId"] in task_ids
                or not _nonempty_text(candidate.get("routingContext"))
                or not _number_between(candidate.get("routingThreshold"), 0, 1)
                or not _number_between(candidate.get("routingMinMargin"), 0, 1)
            ):
                raise ContractError("invalid_route_input", "candidate task contract is invalid")
            task_ids.add(candidate["taskId"])
    return request


def _validate_health(payload: object) -> dict[str, Any]:
    value = _require_object(payload, "invalid_health_response")
    if value != {"ok": True, "capabilityVersion": "2"}:
        raise ContractError("invalid_health_response", "health response does not advertise capability version 2")
    return value


def _validate_plan(
    payload: object,
    request: AgentOperationRequest | None,
) -> dict[str, Any]:
    value = _require_object(payload, "invalid_plan")
    _exact_keys(value, {"schemaVersion", "summary", "nodes"}, "invalid_plan")
    if value.get("schemaVersion") != 1 or not _nonempty_text(value.get("summary")):
        raise ContractError("invalid_plan", "plan metadata is invalid")
    nodes = value.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ContractError("invalid_plan", "plan nodes must be a non-empty list")

    if request is not None:
        expected = request.system_rules.get("totalCount")
        if isinstance(expected, int) and len(nodes) != expected:
            raise ContractError("plan_count_mismatch", "plan total count differs from system rules")
        level_counts = {1: "rootCount", 2: "level2Count", 3: "level3Count"}
        for level, field in level_counts.items():
            expected_level = request.system_rules.get(field)
            if isinstance(expected_level, int):
                actual_level = sum(isinstance(node, dict) and node.get("level") == level for node in nodes)
                if actual_level != expected_level:
                    raise ContractError("plan_count_mismatch", f"plan {field} differs from system rules")

    indexed: dict[str, Mapping[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            raise ContractError("invalid_plan", "each plan node must be an object")
        _exact_keys(
            node,
            {"clientNodeId", "level", "parentClientNodeId", "intent", "text", "plannedAt"},
            "invalid_plan",
        )
        node_id = node.get("clientNodeId")
        level = node.get("level")
        if (
            not _nonempty_text(node_id)
            or node_id in indexed
            or level not in (1, 2, 3)
            or not _nonempty_text(node.get("intent"))
            or not _nonempty_text(node.get("text"))
            or _parse_datetime(node.get("plannedAt")) is None
        ):
            raise ContractError("invalid_plan", "plan node shape is invalid")
        indexed[node_id] = node

    for node in nodes:
        level = node["level"]
        parent_id = node.get("parentClientNodeId")
        if level == 1:
            if parent_id is not None:
                raise ContractError("invalid_plan_parent", "root comments cannot have a parent")
            continue
        parent = indexed.get(parent_id) if isinstance(parent_id, str) else None
        if parent is None or parent.get("level") != level - 1:
            raise ContractError("invalid_plan_parent", "reply parent must exist at the previous level")
        parent_time = _parse_datetime(parent.get("plannedAt"))
        child_time = _parse_datetime(node.get("plannedAt"))
        if parent_time is None or child_time is None or parent_time >= child_time:
            raise ContractError("invalid_plan_order", "reply must be scheduled after its parent")

    if request is not None:
        starts_at = _parse_datetime(request.system_rules.get("startsAt"))
        ends_at = _parse_datetime(request.system_rules.get("endsAt"))
        if starts_at is not None and ends_at is not None:
            for node in nodes:
                planned_at = _parse_datetime(node["plannedAt"])
                if planned_at is None or not starts_at <= planned_at <= ends_at:
                    raise ContractError("plan_time_out_of_window", "planned time falls outside the configured window")
    return value


def _validate_recovery(
    payload: object,
    request: AgentOperationRequest | None,
) -> dict[str, Any]:
    value = _require_object(payload, "invalid_recovery")
    _exact_keys(
        value,
        {"schemaVersion", "newLevel", "targetType", "targetShortId", "intent", "text"},
        "invalid_recovery",
    )
    if (
        value.get("schemaVersion") != 1
        or value.get("newLevel") not in (1, 2, 3)
        or value.get("targetType") not in ("NEARBY_COMMENT", "NEW_ROOT")
        or not _nonempty_text(value.get("intent"))
        or not _nonempty_text(value.get("text"))
    ):
        raise ContractError("invalid_recovery", "recovery response shape is invalid")

    target_type = value["targetType"]
    target_short_id = value.get("targetShortId")
    if target_type == "NEW_ROOT":
        if value["newLevel"] != 1 or target_short_id is not None:
            raise ContractError("invalid_recovery", "new root recovery must target level one without an ID")
        return value

    nearby = request.user_requirements.get("nearbyComments", []) if request is not None else []
    known_ids = {
        item.get("shortId")
        for item in nearby
        if isinstance(item, dict) and _nonempty_text(item.get("shortId"))
    }
    if not _nonempty_text(target_short_id) or target_short_id not in known_ids:
        raise ContractError("unknown_recovery_target", "recovery target was not supplied by the caller")
    target = next(
        (
            item
            for item in nearby
            if isinstance(item, dict) and item.get("shortId") == target_short_id
        ),
        None,
    )
    if (
        isinstance(target, dict)
        and target.get("level") in (1, 2)
        and value["newLevel"] != target["level"] + 1
    ):
        raise ContractError("invalid_recovery", "recovery level must follow the target level")
    return value


def _validate_private_reply(payload: object) -> dict[str, Any]:
    value = _require_object(payload, "invalid_private_reply")
    _exact_keys(
        value,
        {
            "schemaVersion",
            "action",
            "replyText",
            "replyGoalReached",
            "intent",
            "conversationSummary",
        },
        "invalid_private_reply",
    )
    reply = value.get("replyText")
    action = value.get("action")
    if (
        value.get("schemaVersion") != 1
        or action not in ("REPLY", "NO_REPLY")
        or not isinstance(value.get("replyGoalReached"), bool)
        or not _nonempty_text(value.get("intent"))
        or not _nonempty_text(value.get("conversationSummary"))
    ):
        raise ContractError("invalid_private_reply", "private reply decision shape is invalid")
    if action == "REPLY":
        if (
            not isinstance(reply, str)
            or not reply.strip()
            or len(reply) > MAX_PRIVATE_REPLY_CHARS
            or "```" in reply
            or _HTML_TAG.search(reply) is not None
        ):
            raise ContractError("invalid_private_reply", "reply action requires safe plain text")
    elif reply is not None or value["replyGoalReached"]:
        raise ContractError("invalid_private_reply", "no-reply action cannot include reply text or reach the goal")
    return value


def _inbound_messages(request: AgentOperationRequest | None) -> list[Mapping[str, Any]]:
    if request is None:
        return []
    messages: list[Mapping[str, Any]] = []
    current = request.user_requirements.get("inboundMessage")
    if isinstance(current, dict):
        messages.append(current)
    for field in ("recentHistory", "conversation"):
        history = request.user_requirements.get(field)
        if isinstance(history, list):
            messages.extend(item for item in history if isinstance(item, dict))
    return [
        message
        for message in messages
        if str(message.get("direction", "")).upper() == "INBOUND"
    ]


def _message_identity(message: Mapping[str, Any]) -> tuple[object, object]:
    message_id = message.get("messageId", message.get("id"))
    text = message.get("text", message.get("content"))
    return message_id, text


def _validate_lead_rule(
    payload: object,
    request: AgentOperationRequest | None,
) -> dict[str, Any]:
    value = _require_object(payload, "invalid_lead_rule")
    _exact_keys(
        value,
        {
            "schemaVersion",
            "matched",
            "leadValue",
            "evidenceMessageId",
            "evidenceText",
            "reason",
        },
        "invalid_lead_rule",
    )
    if value.get("schemaVersion") != 1 or not isinstance(value.get("matched"), bool):
        raise ContractError("invalid_lead_rule", "lead evaluation shape is invalid")
    fields = ("leadValue", "evidenceMessageId", "evidenceText")
    if value["matched"]:
        if any(not _nonempty_text(value.get(field)) for field in fields):
            raise ContractError("invalid_lead_rule", "matched lead requires copied evidence")
        evidence = [
            message
            for message in _inbound_messages(request)
            if _message_identity(message)
            == (value["evidenceMessageId"], value["evidenceText"])
        ]
        if not evidence or value["leadValue"] not in value["evidenceText"]:
            raise ContractError(
                "invalid_lead_evidence",
                "lead evidence must be copied from a real inbound message",
            )
    elif any(value.get(field) is not None for field in fields):
        raise ContractError("invalid_lead_rule", "unmatched lead cannot include evidence")
    if not _nonempty_text(value.get("reason")):
        raise ContractError("invalid_lead_rule", "lead evaluation requires a reason")
    return value


def _candidate_tasks(request: AgentOperationRequest | None) -> dict[str, Mapping[str, Any]]:
    if request is None:
        return {}
    raw = request.user_requirements.get("candidateTasks")
    if not isinstance(raw, list) or len(raw) > 2_000:
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for candidate in raw:
        if not isinstance(candidate, dict) or not _nonempty_text(candidate.get("taskId")):
            return {}
        task_id = candidate["taskId"]
        if task_id in result:
            return {}
        result[task_id] = candidate
    return result


def _validate_route(
    payload: object,
    request: AgentOperationRequest | None,
) -> dict[str, Any]:
    value = _require_object(payload, "invalid_route")
    _exact_keys(
        value,
        {"schemaVersion", "taskId", "status", "probability", "confidence"},
        "invalid_route",
    )
    status = value.get("status")
    if (
        value.get("schemaVersion") != 1
        or status not in ("MATCHED", "UNRESOLVED", "ERROR")
        or not _number_between(value.get("confidence"), 0, 1)
    ):
        raise ContractError("invalid_route", "routing decision shape is invalid")

    if status != "MATCHED":
        if value.get("taskId") is not None or value.get("probability") is not None:
            raise ContractError("invalid_route", "unresolved route cannot select a task")
        return value

    candidates = _candidate_tasks(request)
    task_id = value.get("taskId")
    probability = value.get("probability")
    if task_id not in candidates or not _number_between(probability, 0, 1):
        raise ContractError("invalid_route", "matched route must select a supplied candidate")
    candidate = candidates[task_id]
    threshold = candidate.get("routingThreshold")
    min_margin = candidate.get("routingMinMargin")
    if not _number_between(threshold, 0, 1) or not _number_between(min_margin, 0, 1):
        raise ContractError("invalid_route_input", "candidate routing thresholds are invalid")
    if float(probability) < float(threshold) or float(value["confidence"]) < float(min_margin):
        raise ContractError("route_below_threshold", "matched route does not meet candidate thresholds")
    return value


def validate_operation_response(
    operation: Operation,
    payload: object,
    request: AgentOperationRequest | None = None,
) -> dict[str, Any]:
    if operation is Operation.HEALTH_CHECK:
        return _validate_health(payload)
    if operation in (Operation.GENERATE_PLAN, Operation.REPAIR_PLAN):
        return _validate_plan(payload, request)
    if operation is Operation.GENERATE_RECOVERY:
        return _validate_recovery(payload, request)
    if operation is Operation.ROUTE_PRIVATE_MESSAGE:
        return _validate_route(payload, request)
    if operation is Operation.GENERATE_PRIVATE_REPLY:
        return _validate_private_reply(payload)
    if operation is Operation.EVALUATE_LEAD_RULE:
        return _validate_lead_rule(payload, request)
    raise ContractError("unknown_operation", f"unsupported operation: {operation}")
