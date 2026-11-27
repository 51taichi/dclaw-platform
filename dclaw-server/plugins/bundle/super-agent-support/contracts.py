# -*- coding: utf-8 -*-
"""Public local execution response contract and stable error mapping."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

STANDARD = {"id": "dclaw.local-execution", "version": "1.2"}
TOOLS = (
    "local_environment_status",
    "local_capabilities_list",
    "local_runtime_prepare",
    "local_task_start",
    "local_task_continue",
    "local_task_status",
    "local_task_cancel",
    "local_task_result",
    "local_file_select",
    "local_file_upload",
    "managed_artifacts_list",
    "managed_artifact_action",
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
    "PUBLIC_COMPONENT_UNAVAILABLE": PublicError(
        "PUBLIC_COMPONENT.UNAVAILABLE",
        "dependency",
        True,
        "contact_administrator",
        "该能力需要的公共组件尚未在当前设备平台完成注册。",
        "public_component_registry",
        "public_component",
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
    "FILE_SELECTOR_UNSUPPORTED": PublicError(
        "FILE_SELECTOR.UNSUPPORTED",
        "unsupported",
        False,
        "update_local_helper",
        "当前本地助手不支持安全文件选择。",
        "file_selector",
    ),
    "FILE_SELECTOR_DEVICE_OFFLINE": PublicError(
        "FILE_SELECTOR.DEVICE_OFFLINE",
        "connection",
        True,
        "reconnect_runner",
        "用于文件选择的本地设备当前离线。",
        "file_selector",
    ),
    "FILE_SELECTOR_PERMISSION_DENIED": PublicError(
        "FILE_SELECTOR.PERMISSION_DENIED",
        "permission",
        False,
        "select_different_file",
        "所选文件不符合允许的类型或访问策略。",
        "file_selector",
    ),
    "FILE_SELECTOR_NOT_AUTHORIZED": PublicError(
        "FILE_SELECTOR.NOT_AUTHORIZED",
        "authorization",
        False,
        "contact_administrator",
        "当前 Agent 未获本地文件选择授权。",
        "file_selector",
    ),
    "FILE_SELECTOR_FILE_TOO_LARGE": PublicError(
        "FILE_SELECTOR.FILE_TOO_LARGE",
        "resource_exhausted",
        False,
        "select_smaller_file",
        "所选文件超过大小限制。",
        "file_selector",
    ),
    "FILE_SELECTOR_FILE_COUNT_EXCEEDED": PublicError(
        "FILE_SELECTOR.FILE_COUNT_EXCEEDED",
        "invalid_request",
        False,
        "select_fewer_files",
        "所选文件数量超过限制。",
        "file_selector",
    ),
    "LOCAL_FILE_REF_EXPIRED": PublicError(
        "LOCAL_FILE_REF.EXPIRED",
        "state_conflict",
        False,
        "select_file_again",
        "本地文件引用已过期，请重新选择文件。",
        "local_file_registry",
        "runner",
    ),
    "LOCAL_FILE_REF_REVOKED": PublicError(
        "LOCAL_FILE_REF.REVOKED",
        "state_conflict",
        False,
        "select_file_again",
        "本地文件引用已撤销，请重新选择文件。",
        "local_file_registry",
        "runner",
    ),
    "LOCAL_FILE_REF_WRONG_DEVICE": PublicError(
        "LOCAL_FILE_REF.WRONG_DEVICE",
        "permission",
        False,
        "use_original_device",
        "本地文件引用不属于当前设备。",
        "local_file_registry",
        "runner",
    ),
    "LOCAL_FILE_REF_SCOPE_MISMATCH": PublicError(
        "LOCAL_FILE_REF.SCOPE_MISMATCH",
        "permission",
        False,
        "select_file_again",
        "本地文件引用不属于当前账号、Agent 或会话。",
        "local_file_registry",
        "runner",
    ),
    "LOCAL_FILE_REF_FILE_CHANGED": PublicError(
        "LOCAL_FILE_REF.FILE_CHANGED",
        "state_conflict",
        False,
        "select_file_again",
        "本地文件自选择后已发生变化，请重新选择。",
        "local_file_registry",
        "runner",
    ),
    "LOCAL_FILE_REF_FILE_MISSING": PublicError(
        "LOCAL_FILE_REF.FILE_MISSING",
        "not_found",
        False,
        "select_file_again",
        "本地文件已移动或删除，请重新选择。",
        "local_file_registry",
        "runner",
    ),
    "LOCAL_FILE_REF_RESOLVE_FAILED": PublicError(
        "LOCAL_FILE_REF.RESOLVE_FAILED",
        "unknown",
        False,
        "select_file_again",
        "无法安全解析本地文件引用。",
        "local_file_registry",
        "runner",
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
            "standard_version": "1.1",
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
