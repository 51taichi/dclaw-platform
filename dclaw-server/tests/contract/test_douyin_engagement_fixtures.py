from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_sources.douyin_engagement_agent.agent.contracts import (
    ContractError,
    Operation,
    parse_operation_message,
    validate_operation_response,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "agent_contract"
CANONICAL_FIXTURES = (
    Path(__file__).resolve().parents[2].parent
    / "dclaw-bot-server/tests/fixtures/agent_contract"
)


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_local_agent_fixtures_match_canonical_source_when_available() -> None:
    if not CANONICAL_FIXTURES.is_dir():
        pytest.skip("canonical bot-server fixture repository is not checked out")
    for local in FIXTURES.glob("*.json"):
        assert local.read_bytes() == (CANONICAL_FIXTURES / local.name).read_bytes()


def operation_message(value: dict) -> str:
    return "\n".join(
        [
            f"DCLAW_OPERATION: {value['operation']}",
            "SYSTEM_RULES_JSON:",
            json.dumps(value["systemRules"], ensure_ascii=False),
            "USER_SCRIPT_REQUIREMENTS_JSON:",
            json.dumps(value["userScriptRequirements"], ensure_ascii=False),
            "Return only one valid JSON object matching the requested schema.",
        ]
    )


@pytest.mark.parametrize(
    "name",
    [
        "health_check.valid.json",
        "generate_plan.valid.json",
        "repair_plan.valid.json",
        "generate_recovery.valid.json",
        "generate_private_reply.valid.json",
    ],
)
def test_canonical_agent_fixture_parses_and_validates(name: str) -> None:
    value = fixture(name)
    parsed = parse_operation_message(operation_message(value))

    assert parsed.operation is Operation(value["operation"])
    assert validate_operation_response(parsed.operation, value["response"], parsed) == value[
        "response"
    ]


def test_canonical_invalid_private_reply_type_is_rejected() -> None:
    value = fixture("generate_private_reply.invalid.json")

    with pytest.raises(ContractError) as caught:
        validate_operation_response(Operation.GENERATE_PRIVATE_REPLY, value["response"])

    assert caught.value.code == "invalid_private_reply"
