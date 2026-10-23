"""Fail-closed orchestration runtime for Douyin engagement operations."""

from __future__ import annotations

import json
from typing import Any

from .contracts import (
    AgentOperationRequest,
    ContractError,
    parse_operation_message,
    validate_operation_request,
    validate_operation_response,
)
from .prompts import build_agent_messages


def _latest_user_content(request: Any) -> str:
    normalized = getattr(request, "normalized_input", None)
    messages = normalized.get("messages") if isinstance(normalized, dict) else None
    if not isinstance(messages, list):
        raise ContractError("invalid_message", "normalized messages are missing")
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str):
                return content
    raise ContractError("invalid_message", "user operation message is missing")


def _candidate_text(candidate: object) -> str:
    if not isinstance(candidate, dict) or not isinstance(candidate.get("text"), str):
        raise ContractError("invalid_agent_output", "model response text is missing")
    return candidate["text"]


def _validated_candidate(
    candidate: object,
    operation_request: AgentOperationRequest,
) -> dict[str, Any]:
    raw = _candidate_text(candidate)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractError("invalid_agent_output", "model output is not JSON") from exc
    return validate_operation_response(
        operation_request.operation,
        payload,
        operation_request,
    )


def _repair_message(error: ContractError) -> dict[str, str]:
    return {
        "role": "system",
        "content": (
            "The previous output was invalid. Return one corrected JSON object only. "
            f"Validation error code: {error.code}."
        ),
    }


class DouyinEngagementRuntime:
    async def handle(self, request: Any, host: Any) -> None:
        invocation_id = getattr(request, "invocation_id", "")
        try:
            await host.call("session.context", {})
            operation_request = validate_operation_request(
                parse_operation_message(_latest_user_content(request))
            )
        except ContractError as exc:
            await self._safe_trace(
                host,
                {"event": "douyin.operation.rejected", "error_code": exc.code},
            )
            await self._fail(host, invocation_id, "invalid_operation_message")
            return
        except Exception:  # noqa: BLE001 - Host failures must still reach a terminal state.
            await self._safe_trace(host, {"event": "douyin.context.unavailable"})
            await self._fail(host, invocation_id, "session_context_unavailable")
            return

        if operation_request.operation.value == "HEALTH_CHECK":
            await self._complete(
                host,
                invocation_id,
                operation_request,
                {"ok": True, "capabilityVersion": "2"},
                0,
            )
            return

        messages = build_agent_messages(operation_request)
        await self._safe_trace(
            host,
            {
                "event": "douyin.operation.prepared",
                "operation": operation_request.operation.value,
            },
        )
        last_error: ContractError | None = None
        for attempt in (1, 2):
            try:
                candidate = await host.call("agent.execute", {"messages": messages})
            except Exception:  # noqa: BLE001 - Host failures must still reach a terminal state.
                await self._safe_trace(
                    host,
                    {
                        "event": "douyin.model.unavailable",
                        "operation": operation_request.operation.value,
                        "attempt": attempt,
                    },
                )
                await self._fail(host, invocation_id, "model_unavailable")
                return
            try:
                validated = _validated_candidate(candidate, operation_request)
            except ContractError as exc:
                last_error = exc
                await self._safe_trace(
                    host,
                    {
                        "event": "douyin.output.invalid",
                        "operation": operation_request.operation.value,
                        "attempt": attempt,
                        "error_code": exc.code,
                    },
                )
                if attempt == 1:
                    messages = [*messages, _repair_message(exc)]
                    continue
                break

            await self._safe_trace(
                host,
                {
                    "event": "douyin.output.validated",
                    "operation": operation_request.operation.value,
                    "attempt": attempt,
                },
            )
            await self._complete(host, invocation_id, operation_request, validated, attempt)
            return

        await self._fail(
            host,
            invocation_id,
            "invalid_agent_output" if last_error is not None else "runtime_failed",
        )

    @staticmethod
    async def _fail(host: Any, invocation_id: str, diagnostic_ref: str) -> None:
        await host.call(
            "runtime.fail",
            {
                "invocation_id": invocation_id,
                "error_code": "runtime_failed",
                "diagnostic_ref": diagnostic_ref,
            },
        )

    @staticmethod
    async def _safe_trace(host: Any, payload: dict[str, Any]) -> None:
        try:
            await host.call("runtime.trace", payload)
        except Exception:  # noqa: BLE001 - Trace failure must not mask the business result.
            return

    @staticmethod
    async def _complete(
        host: Any,
        invocation_id: str,
        operation_request: AgentOperationRequest,
        payload: dict[str, Any],
        attempts: int,
    ) -> None:
        await host.call(
            "runtime.complete",
            {
                "invocation_id": invocation_id,
                "message": {
                    "name": "assistant",
                    "role": "assistant",
                    "content": json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                },
                "diagnostics": {
                    "operation": operation_request.operation.value,
                    "attempts": attempts,
                },
            },
        )


def create_runtime() -> DouyinEngagementRuntime:
    return DouyinEngagementRuntime()
