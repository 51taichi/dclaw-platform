from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

CONTRACT_ROOT = (
    Path(__file__).parents[3] / "docs" / "contracts" / "local-execution" / "v1"
)
STANDARD_DOC = Path(__file__).parents[3] / "docs" / "local-execution-standard-v1.zh-CN.md"


def _load(name: str) -> dict:
    return json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))


def test_local_execution_v1_schemas_are_valid_and_resolve_locally():
    error_schema = _load("error-envelope.schema.json")
    response_schema = _load("tool-response.schema.json")
    call_schema = _load("tool-call.schema.json")
    Draft202012Validator.check_schema(error_schema)
    Draft202012Validator.check_schema(response_schema)
    Draft202012Validator.check_schema(call_schema)
    registry = Registry().with_resource(
        error_schema["$id"], Resource.from_contents(error_schema)
    )
    validator = Draft202012Validator(response_schema, registry=registry)

    validator.validate(
        {
            "standard": {"id": "dclaw.local-execution", "version": "1.0"},
            "ok": True,
            "trace_id": "invocation-contract-success",
            "data": {"state": "ready"},
        }
    )
    call_validator = Draft202012Validator(call_schema)
    call_validator.validate(
        {
            "tool": "local_task_start",
            "arguments": {
                "capability_id": "video.s1.compose",
                "input": {"gate_text": "confirmed"},
                "idempotency_key": "conversation-turn-1",
            },
        }
    )

    valid_calls = [
        {
            "tool": "local_environment_status",
            "arguments": {"agent_protocol_version": "1"},
        },
        {"tool": "local_capabilities_list", "arguments": {}},
        {
            "tool": "local_runtime_prepare",
            "arguments": {"capability": "video.s1.compose"},
        },
        {
            "tool": "local_task_continue",
            "arguments": {
                "task_id": "task-1",
                "checkpoint_id": "checkpoint-1",
                "input": {},
            },
        },
        {
            "tool": "local_task_status",
            "arguments": {"current_task": True, "wait_seconds": 25},
        },
        {"tool": "local_task_cancel", "arguments": {"task_id": "task-1"}},
        {"tool": "local_task_result", "arguments": {"task_id": "task-1"}},
    ]
    for call in valid_calls:
        call_validator.validate(call)

    with pytest.raises(ValidationError):
        call_validator.validate(
            {"tool": "dzb_task_result", "arguments": {"task_id": "task-1"}}
        )
    with pytest.raises(ValidationError):
        call_validator.validate(
            {
                "tool": "local_task_status",
                "arguments": {"task_id": "task-1", "current_task": True},
            }
        )
    validator.validate(
        {
            "standard": {"id": "dclaw.local-execution", "version": "1.0"},
            "ok": False,
            "trace_id": "invocation-contract-failure",
            "error": {
                "standard_version": "1.0",
                "code": "LOCAL_GATEWAY.DEVICE_NOT_READY",
                "legacy_code": "DEVICE_NOT_READY",
                "source": {
                    "layer": "local_gateway",
                    "component": "device_registry",
                    "operation": "local_task_start",
                },
                "category": "connection",
                "retryable": True,
                "user_action": "reconnect_runner",
                "public_message": "DClaw 本地助手尚未连接。",
                "trace_id": "invocation-contract-failure",
            },
        }
    )


def test_local_execution_standard_defines_desktop_owned_toolbox_and_workspace():
    text = STANDARD_DOC.read_text(encoding="utf-8")

    required = (
        "DClaw 桌面版是唯一用户入口",
        "本地助手不提供第二套登录",
        "%LocalAppData%\\DClawLocalTool",
        "<Agent 在 DClaw 中的显示名称>",
        "最终 MP4、图片、文档等客户成品直接放在任务目录第一层",
        "全部放在 `res`",
        "不得把这些检查扩展为业务审核或重复状态机",
    )
    for phrase in required:
        assert phrase in text
