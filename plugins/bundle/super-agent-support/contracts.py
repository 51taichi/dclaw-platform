"""Public local execution response contract and stable error mapping."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

STANDARD = {"id": "dclaw.local-execution", "version": "1.0"}
TOOLS = (
    "local_environment_status",
    "local_capabilities_list",
    "local_runtime_prepare",
    "local_task_start",
    "local_task_continue",
    "local_task_status",
    "local_task_cancel",
    "local_task_result",
)


@dataclass(frozen=True)
class PublicError(Exception):
    code: str
    category: str
    retryable: bool
    user_action: str
    public_message: str
    component: str
    layer: str = "local_gateway"


ERRORS = {
    "AUTHENTICATION_FAILED": PublicError(
        "LOCAL_GATEWAY.AUTHENTICATION_FAILED",
        "authentication",
        False,
        "start_new_task",
        "本地执行会话无效或已过期。",
        "session_verifier",
    ),
    "INVALID_ARGUMENTS": PublicError(
        "LOCAL_GATEWAY.INVALID_ARGUMENTS",
        "invalid_request",
        False,
        "correct_request",
        "本地能力调用参数不符合协议。",
        "mcp.dispatcher",
    ),
    "INVALID_CAPABILITY_PAYLOAD": PublicError(
        "CAPABILITY.INVALID_PAYLOAD",
        "invalid_request",
        False,
        "correct_request",
        "本地能力输入或输出不符合已签名的能力合同。",
        "capability.schema_validator",
        "capability",
    ),
    "DEVICE_NOT_READY": PublicError(
        "LOCAL_GATEWAY.DEVICE_NOT_READY",
        "connection",
        True,
        "reconnect_runner",
        "DClaw 本地助手尚未连接或不支持所选能力。",
        "device_registry",
    ),
    "CAPABILITY_NOT_FOUND": PublicError(
        "LOCAL_GATEWAY.CAPABILITY_NOT_FOUND",
        "not_found",
        False,
        "correct_request",
        "当前能力目录中没有所选能力。",
        "capability_catalog",
    ),
    "TASK_NOT_FOUND": PublicError(
        "LOCAL_GATEWAY.TASK_NOT_FOUND",
        "not_found",
        False,
        "start_new_task",
        "没有找到当前账号可访问的任务。",
        "task_store",
    ),
    "IDEMPOTENCY_CONFLICT": PublicError(
        "LOCAL_GATEWAY.IDEMPOTENCY_CONFLICT",
        "state_conflict",
        False,
        "correct_request",
        "相同幂等标识已用于不同的任务输入。",
        "task_store",
    ),
    "RESOURCE_EXHAUSTED": PublicError(
        "LOCAL_GATEWAY.RESOURCE_EXHAUSTED",
        "resource_exhausted",
        True,
        "retry_later",
        "本地能力已达到当前并发或资源上限。",
        "task_scheduler",
    ),
    "CHECKPOINT_MISMATCH": PublicError(
        "LOCAL_GATEWAY.CHECKPOINT_MISMATCH",
        "state_conflict",
        False,
        "correct_request",
        "任务检查点已变化，请先读取最新任务状态。",
        "task_store",
    ),
    "TASK_NOT_ACTIVE": PublicError(
        "LOCAL_GATEWAY.TASK_NOT_ACTIVE",
        "state_conflict",
        False,
        "start_new_task",
        "该任务已不处于可继续状态。",
        "task_store",
    ),
    "INTERNAL": PublicError(
        "LOCAL_GATEWAY.INTERNAL_ERROR",
        "unknown",
        False,
        "contact_administrator",
        "本地执行服务暂时不可用，请提供追踪编号。",
        "plugin.runtime",
    ),
}


def trace_id(value: str | None = None) -> str:
    if isinstance(value, str) and 8 <= len(value) <= 128:
        return value
    return uuid.uuid4().hex


def success(data: dict[str, Any], trace: str) -> dict[str, Any]:
    return {"standard": STANDARD, "ok": True, "trace_id": trace, "data": data}


def failure(error: PublicError, trace: str, operation: str) -> dict[str, Any]:
    return {
        "standard": STANDARD,
        "ok": False,
        "trace_id": trace,
        "error": {
            "standard_version": "1.0",
            "code": error.code,
            "source": {
                "layer": error.layer,
                "component": error.component,
                "operation": operation,
            },
            "category": error.category,
            "retryable": error.retryable,
            "user_action": error.user_action,
            "public_message": error.public_message,
            "trace_id": trace,
        },
    }
