# -*- coding: utf-8 -*-
"""Request-scoped response-format policy for direct Agent OpenAPI calls."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from copy import deepcopy
import json
from typing import Any, Type

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from openai import NOT_GIVEN
from pydantic import BaseModel
from agentscope_runtime.engine.schemas.exception import AppBaseException

from ...providers.openai_chat_model_compat import OpenAIChatModelCompat


_FINALIZATION_INSTRUCTION = (
    "<system-hint>Produce the final customer response now. Do not call tools. "
    "Return exactly one JSON object that follows the configured response "
    "format. Use the planning draft and tool results only as evidence.</system-hint>"
)


class OpenApiAgentExecutionError(AppBaseException):
    """Safe typed failure for a streamed direct-Agent OpenAPI invocation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 502,
        error_summary: str | None = None,
    ) -> None:
        super().__init__(http_status, code, message)
        self.http_status = http_status
        self.error_summary = error_summary or message


def is_trusted_direct_agent_open_api(
    channel: str,
    channel_meta: Any,
) -> bool:
    """Return whether server-owned metadata identifies a direct Agent call."""
    if not str(channel or "").startswith("open:"):
        return False
    if not isinstance(channel_meta, dict):
        return False
    return bool(
        channel_meta.get("target_type") == "agent"
        and str(channel_meta.get("publication_id") or "").strip()
        and str(channel_meta.get("open_invocation_id") or "").strip()
    )


def install_open_api_agent_response_format(agent: Any) -> bool:
    """Install the phase adapter on an eligible request-owned model."""
    model = getattr(agent, "model", None)
    raw_model = _find_openai_compat_model(model)
    if raw_model is None:
        return False
    configured = getattr(raw_model, "generate_kwargs", {}).get(
        "response_format",
    )
    if configured != {"type": "json_object"}:
        return False

    # This model instance belongs to the current QwenPawAgent request. Force
    # AgentScope's internal Pydantic structured calls through its tool-call
    # implementation; that implementation removes response_format before the
    # supplier request. Provider configuration remains untouched.
    raw_model._structured_output_fallback = True  # pylint: disable=protected-access
    agent.model = OpenApiAgentResponseFormatModel(
        model,
        response_format=deepcopy(configured),
    )
    return True


def _find_openai_compat_model(model: Any) -> OpenAIChatModelCompat | None:
    """Find the single raw OpenAI model through known request wrappers."""
    seen: set[int] = set()
    current = model
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OpenAIChatModelCompat):
            return current
        if hasattr(current, "_inner"):
            current = getattr(current, "_inner")
            continue
        if hasattr(current, "_model"):
            current = getattr(current, "_model")
            continue
        return None
    return None


class OpenApiAgentResponseFormatModel(ChatModelBase):
    """Split direct OpenAPI Agent calls into planning and finalization."""

    def __init__(
        self,
        inner: ChatModelBase,
        *,
        response_format: dict[str, Any],
    ) -> None:
        super().__init__(
            model_name=inner.model_name,
            stream=inner.stream,
        )
        self._inner = inner
        self.response_format = deepcopy(response_format)

    @property
    def model_key(self) -> str | None:
        """Preserve capability-cache and provider-specific model identity."""
        return getattr(self._inner, "model_key", None)

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncIterator[ChatResponse]:
        if structured_model is not None:
            return await self._invoke_passthrough(
                messages,
                tools=tools,
                tool_choice=tool_choice,
                structured_model=structured_model,
                response_format=NOT_GIVEN,
                extra_kwargs=kwargs,
            )

        if tools:
            planning = await self._invoke(
                messages,
                tools=tools,
                tool_choice=tool_choice,
                structured_model=None,
                response_format=NOT_GIVEN,
                extra_kwargs=kwargs,
            )
            if _has_tool_use(planning):
                _suppress_planning_text(planning)
                return self._as_model_result(planning)

            final_messages = _finalization_messages(messages, planning)
            final = await self._invoke(
                final_messages,
                tools=None,
                tool_choice=None,
                structured_model=None,
                response_format=deepcopy(self.response_format),
                extra_kwargs=kwargs,
            )
            _validate_final_response(final, messages)
            return self._as_model_result(final)

        final = await self._invoke(
            messages,
            tools=None,
            tool_choice=tool_choice,
            structured_model=None,
            response_format=deepcopy(self.response_format),
            extra_kwargs=kwargs,
        )
        _validate_final_response(final, messages)
        return self._as_model_result(final)

    async def _invoke_passthrough(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None,
        tool_choice: str | None,
        structured_model: Type[BaseModel] | None,
        response_format: Any,
        extra_kwargs: dict[str, Any],
    ) -> ChatResponse | AsyncIterator[ChatResponse]:
        try:
            result = await self._inner(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                structured_model=structured_model,
                response_format=response_format,
                **extra_kwargs,
            )
            if isinstance(result, ChatResponse):
                return result

            async def guarded() -> AsyncIterator[ChatResponse]:
                try:
                    async for item in result:
                        yield item
                except OpenApiAgentExecutionError:
                    raise
                except Exception as exc:
                    raise _model_execution_error(exc) from exc

            return guarded()
        except OpenApiAgentExecutionError:
            raise
        except Exception as exc:
            raise _model_execution_error(exc) from exc

    async def _invoke(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None,
        tool_choice: str | None,
        structured_model: Type[BaseModel] | None,
        response_format: Any,
        extra_kwargs: dict[str, Any],
    ) -> ChatResponse:
        try:
            result = await self._inner(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                structured_model=structured_model,
                response_format=response_format,
                **extra_kwargs,
            )
            return await self._collect(result)
        except OpenApiAgentExecutionError:
            raise
        except Exception as exc:
            raise _model_execution_error(exc) from exc

    async def _collect(
        self,
        result: ChatResponse | AsyncIterator[ChatResponse],
    ) -> ChatResponse:
        if isinstance(result, ChatResponse):
            return result
        last: ChatResponse | None = None
        async for item in result:
            last = item
        if last is None:
            return ChatResponse(content=[])
        return last

    def _as_model_result(
        self,
        response: ChatResponse,
    ) -> ChatResponse | AsyncIterator[ChatResponse]:
        if not self.stream:
            return response

        async def replay() -> AsyncIterator[ChatResponse]:
            yield response

        return replay()


def _has_tool_use(response: ChatResponse) -> bool:
    return any(
        isinstance(block, dict) and block.get("type") == "tool_use"
        for block in response.content
    )


def _suppress_planning_text(response: ChatResponse) -> None:
    """Keep executable tool blocks while hiding non-final planning text."""
    response.content = [
        block
        for block in response.content
        if not (isinstance(block, dict) and block.get("type") == "text")
    ]


def _response_text(response: ChatResponse) -> str:
    return "".join(
        str(block.get("text") or "")
        for block in response.content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def _model_execution_error(exc: Exception) -> OpenApiAgentExecutionError:
    return OpenApiAgentExecutionError(
        "model_execution_failed",
        "Model execution failed",
        error_summary=f"model execution failed ({type(exc).__name__})",
    )


def _validate_final_response(
    response: ChatResponse,
    source_messages: Sequence[dict],
) -> None:
    text = _response_text(response).strip()
    tool_failed = _contains_tool_failure(source_messages)
    if not text:
        if tool_failed:
            raise OpenApiAgentExecutionError(
                "tool_execution_failed",
                "Tool execution failed",
            )
        raise OpenApiAgentExecutionError(
            "empty_final_response",
            "Model returned an empty final response",
        )
    try:
        value = json.loads(text)
    except (TypeError, ValueError) as exc:
        if tool_failed:
            raise OpenApiAgentExecutionError(
                "tool_execution_failed",
                "Tool execution failed",
            ) from exc
        raise OpenApiAgentExecutionError(
            "invalid_final_response",
            "Model returned an invalid JSON response",
        ) from exc
    if not isinstance(value, dict):
        if tool_failed:
            raise OpenApiAgentExecutionError(
                "tool_execution_failed",
                "Tool execution failed",
            )
        raise OpenApiAgentExecutionError(
            "invalid_final_response",
            "Model returned an invalid JSON response",
        )


def _contains_tool_failure(messages: Sequence[dict]) -> bool:
    markers = (
        "error:",
        "error occurred when calling",
        "error during async execution",
        "tool execution failed",
    )
    for message in messages:
        if str(message.get("role") or "").lower() not in {"tool", "system"}:
            continue
        content = message.get("content")
        try:
            rendered = (
                content
                if isinstance(content, str)
                else json.dumps(content, ensure_ascii=False)
            )
        except (TypeError, ValueError):
            rendered = str(content)
        lowered = rendered.lower()
        if any(marker in lowered for marker in markers):
            return True
    return False


def _finalization_messages(
    messages: Sequence[dict],
    planning: ChatResponse,
) -> list[dict]:
    copied = deepcopy(list(messages))
    draft = _response_text(planning).strip()
    if draft:
        copied.append({"role": "assistant", "content": draft})
    copied.append({"role": "user", "content": _FINALIZATION_INSTRUCTION})
    return copied
