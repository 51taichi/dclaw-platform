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
STANDARD_DOC = (
    Path(__file__).parents[3]
    / "docs"
    / "super-agent-development-standard-v1.zh-CN.md"
)


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
        error_schema["$id"],
        Resource.from_contents(error_schema),
    )
    validator = Draft202012Validator(response_schema, registry=registry)

    validator.validate(
        {
            "standard": {"id": "dclaw.local-execution", "version": "1.0"},
            "ok": True,
            "trace_id": "invocation-contract-success",
            "data": {
                "state": "device_not_ready",
                "reason": "no_paired_device",
                "protocol_version": "1",
                "compatible": True,
                "minimum_runner_version": "1.0.0",
                "bootstrap_session_id": "bootstrap-1",
                "user_action": "open_dclaw",
                "devices": [],
            },
        },
    )
    success_data = [
        {
            "catalog_version": "1",
            "availability": "available",
            "capabilities": [],
            "device_count": 1,
        },
        {
            "state": "preparing",
            "capability_id": "example.video.compose",
            "package_id": "example.video.package",
            "package_version": "1.0.0",
            "min_runner_version": "1.0.0",
            "device_id": "device-1",
            "runner_version": "1.0.0",
            "user_action": "wait",
        },
        {
            "task_id": "task-1",
            "capability_id": "example.video.compose",
            "device_id": "device-1",
            "status": "awaiting_input",
            "checkpoint": {"checkpoint_id": "checkpoint-1"},
            "result": None,
            "error": None,
            "created_at": 1,
            "updated_at": 2,
            "idempotent_replay": False,
        },
    ]
    for data in success_data:
        validator.validate(
            {
                "standard": {
                    "id": "dclaw.local-execution",
                    "version": "1.0",
                },
                "ok": True,
                "trace_id": "invocation-contract-success",
                "data": data,
            },
        )
    call_validator = Draft202012Validator(call_schema)
    call_validator.validate(
        {
            "tool": "local_task_start",
            "arguments": {
                "capability_id": "example.video.compose",
                "input": {"gate_text": "confirmed"},
                "idempotency_key": "conversation-turn-1",
            },
        },
    )

    valid_calls = [
        {
            "tool": "local_environment_status",
            "arguments": {"agent_protocol_version": "1"},
        },
        {"tool": "local_capabilities_list", "arguments": {}},
        {
            "tool": "local_runtime_prepare",
            "arguments": {"capability": "example.video.compose"},
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
            {"tool": "dzb_task_result", "arguments": {"task_id": "task-1"}},
        )
    with pytest.raises(ValidationError):
        call_validator.validate(
            {
                "tool": "local_task_status",
                "arguments": {"task_id": "task-1", "current_task": True},
            },
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
        },
    )


def test_standard_defines_desktop_owned_toolbox_and_workspace():
    text = STANDARD_DOC.read_text(encoding="utf-8")

    required = (
        "DClaw 桌面版是唯一用户入口",
        "本地助手不提供第二套登录",
        "%LocalAppData%\\DClawLocalTool",
        "<Agent 显示名称>",
        "客户成品直接放在任务目录第一层",
        "过程资源放在 `res`",
        "Runner 核心不理解业务字段",
    )
    for phrase in required:
        assert phrase in text


def test_local_execution_standard_requires_optional_plugin_isolation():
    text = STANDARD_DOC.read_text(encoding="utf-8")

    required = (
        "`dclaw.super-agent-support` 插件包",
        "`local-execution` 模块",
        "`credential-broker` 模块",
        "`capability-packages` 模块",
        "DClaw 核心不得导入或调用 `dclaw.super-agent-support` 插件的内部模块",
        "未安装、禁用、升级失败或卸载该插件时",
        "由插件安装时注册",
        "其他平台能力仍可正常使用",
    )
    for phrase in required:
        assert phrase in text


def test_super_agent_standard_is_the_only_human_development_standard():
    text = STANDARD_DOC.read_text(encoding="utf-8")
    root = Path(__file__).parents[3]

    assert "唯一需要接收和阅读的人工标准文档" in text
    assert "不再新建并行的人工标准" in text
    assert "任何步骤都不得要求访问、克隆或导入" in text
    assert "developer-kit/v1.zip" in text
    assert "dclaw_agent_devkit.py" in text
    migration_staging_root = (
        "/Users/moxi/Desktop/codex space/agent create/agents/超级专家/移植前"
    )
    assert text.count(migration_staging_root) == 2
    assert "/Users/moxi/" not in text.replace(migration_staging_root, "")
    assert "from qwenpaw" not in text
    assert "scripts/build_sealed_agent.py" not in text
    assert not (
        root / "docs" / "local-execution-standard-v1.zh-CN.md"
    ).exists()
    assert not (
        root / "docs" / "super-expert-porting-playbook-v1.zh-CN.md"
    ).exists()
    assert not (
        root / "docs" / "contracts" / "local-execution" / "CHANGELOG.md"
    ).exists()
