# -*- coding: utf-8 -*-
"""Request-scoped response-format policy for direct Agent OpenAPI calls."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Sequence
from copy import deepcopy
import json
import logging
from typing import Any, NoReturn, Type

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from openai import NOT_GIVEN
from pydantic import BaseModel
from agentscope_runtime.engine.schemas.exception import AppBaseException

from ...providers.openai_chat_model_compat import OpenAIChatModelCompat
from ...providers.openai_response_diagnostics import (
    OpenAIResponseDiagnostics,
    capture_openai_response_diagnostics,
    pop_openai_response_diagnostics,
    stash_openai_response_diagnostics,
)


logger = logging.getLogger(__name__)

_JSON_OBJECT_RESPONSE_FORMAT = {"type": "json_object"}
_FINALIZATION_INSTRUCTION = (
    "<system-hint>Produce the final customer response now. Do not call tools. "
    "Return exactly one JSON object that follows the configured response "
    "format. Use the planning draft and tool results only as evidence."
    "</system-hint>"
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
        and str(channel_meta.get("open_invocation_id") or "").strip(),
    )


def install_open_api_agent_response_format(
    agent: Any,
    *,
    force_json_object: bool = False,
) -> bool:
    """Install the phase adapter on an eligible request-owned model."""
    model = getattr(agent, "model", None)
    raw_model = _find_openai_compat_model(model)
    if raw_model is None:
        if _model_chain_has_json_object_format(model):
            _raise_adapter_unavailable(model, "compatible model not found")
        return False
    configured = getattr(raw_model, "generate_kwargs", {}).get(
        "response_format",
    )
    if force_json_object:
        configured = deepcopy(_JSON_OBJECT_RESPONSE_FORMAT)
    if configured != _JSON_OBJECT_RESPONSE_FORMAT:
        return False

    # This model instance belongs to the current QwenPawAgent request. Force
    # AgentScope's internal Pydantic structured calls through its tool-call
    # implementation; that implementation removes response_format before the
    # supplier request. Provider configuration remains untouched.
    try:
        setattr(raw_model, "_structured_output_fallback", True)
        agent.model = OpenApiAgentResponseFormatModel(
            model,
            response_format=deepcopy(configured),
        )
    except Exception as exc:
        _raise_adapter_unavailable(model, type(exc).__name__)
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


def _walk_model_chain(model: Any) -> Iterator[Any]:
    """Yield known wrappers without inspecting arbitrary model state."""
    seen: set[int] = set()
    current = model
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        if hasattr(current, "_inner"):
            current = getattr(current, "_inner")
        elif hasattr(current, "_model"):
            current = getattr(current, "_model")
        else:
            current = None


def _model_chain_has_json_object_format(model: Any) -> bool:
    for current in _walk_model_chain(model):
        generate_kwargs = getattr(current, "generate_kwargs", None)
        if (
            isinstance(generate_kwargs, dict)
            and generate_kwargs.get("response_format")
            == _JSON_OBJECT_RESPONSE_FORMAT
        ):
            return True
    return False


def _raise_adapter_unavailable(model: Any, reason: str) -> NoReturn:
    model_type = type(model).__name__ if model is not None else "None"
    logger.error(
        "open_api_response_format_adapter_unavailable model_type=%s reason=%s",
        model_type,
        reason,
    )
    raise OpenApiAgentExecutionError(
        "response_format_adapter_unavailable",
        "Configured response format is unavailable",
        http_status=500,
        error_summary=(
            "response format adapter unavailable " f"({model_type}: {reason})"
        ),
    )


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
                phase="planning",
            )
            if _has_tool_use(planning):
                _retain_tool_calls(planning)
                return self._as_model_result(planning)

            final_messages = _finalization_messages(messages, planning)
            final = await self._invoke(
                final_messages,
                tools=None,
                tool_choice=None,
                structured_model=None,
                response_format=deepcopy(self.response_format),
                extra_kwargs=kwargs,
                phase="final",
            )
            _validate_final_response(final, messages)
            return self._as_model_result(_final_text_response(final))

        final = await self._invoke(
            messages,
            tools=None,
            tool_choice=tool_choice,
            structured_model=None,
            response_format=deepcopy(self.response_format),
            extra_kwargs=kwargs,
            phase="final",
        )
        _validate_final_response(final, messages)
        return self._as_model_result(_final_text_response(final))

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
                except OpenApiAgentExecutionError:  # pylint: disable=W0706
                    raise
                except Exception as exc:
                    raise _model_execution_error(exc) from exc

            return guarded()
        except OpenApiAgentExecutionError:  # pylint: disable=W0706
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
        phase: str,
    ) -> ChatResponse:
        try:
            with capture_openai_response_diagnostics():
                result = await self._inner(
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    structured_model=structured_model,
                    response_format=response_format,
                    **extra_kwargs,
                )
                response = await self._collect(result)
            self._record_supplier_diagnostics(
                response,
                phase=phase,
                response_format=response_format,
            )
            return response
        except OpenApiAgentExecutionError:  # pylint: disable=W0706
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
        last_diagnostics = OpenAIResponseDiagnostics()
        text = _FragmentAccumulator()
        thinking = _FragmentAccumulator()
        tool_blocks: list[dict[str, Any]] = []
        other_blocks: list[Any] = []
        async for item in result:
            last = item
            diagnostics = pop_openai_response_diagnostics(item)
            if diagnostics != OpenAIResponseDiagnostics():
                last_diagnostics = diagnostics
            item_text = "".join(
                str(block.get("text") or "")
                for block in item.content
                if isinstance(block, dict) and block.get("type") == "text"
            )
            item_thinking = "".join(
                str(block.get("thinking") or "")
                for block in item.content
                if (
                    isinstance(block, dict) and block.get("type") == "thinking"
                )
            )
            text.add(item_text)
            thinking.add(item_thinking)
            current_tools = [
                deepcopy(block)
                for block in item.content
                if isinstance(block, dict) and block.get("type") == "tool_use"
            ]
            if current_tools:
                tool_blocks = current_tools
            current_other = [
                deepcopy(block)
                for block in item.content
                if not (
                    isinstance(block, dict)
                    and block.get("type") in {"text", "thinking", "tool_use"}
                )
            ]
            if current_other:
                other_blocks = current_other
        if last is None:
            return ChatResponse(content=[])
        merged_content: list[Any] = []
        if thinking.value:
            merged_content.append(
                {"type": "thinking", "thinking": thinking.value},
            )
        if text.value:
            merged_content.append({"type": "text", "text": text.value})
        merged_content.extend(tool_blocks)
        merged_content.extend(other_blocks)
        last.content = merged_content
        if last_diagnostics != OpenAIResponseDiagnostics():
            stash_openai_response_diagnostics(last, last_diagnostics)
        return last

    def _record_supplier_diagnostics(
        self,
        response: ChatResponse,
        *,
        phase: str,
        response_format: Any,
    ) -> None:
        diagnostics = pop_openai_response_diagnostics(response)
        # Imported lazily to avoid the AgentRunner -> adapter import cycle.
        from ..agent_context import get_current_billing_context

        context = get_current_billing_context()
        session = getattr(context, "session", None)
        invocation_id = str(getattr(session, "invocation_id", "") or "")
        logger.info(
            "open_api_supplier_response invocation_id=%s phase=%s "
            "model_key=%s response_format_json_object=%s "
            "finish_reason=%s content_length=%d reasoning_length=%d usage=%s",
            invocation_id,
            phase,
            self.model_key or "",
            response_format == _JSON_OBJECT_RESPONSE_FORMAT,
            diagnostics.finish_reason or "",
            diagnostics.content_length,
            diagnostics.reasoning_length,
            diagnostics.usage,
        )

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


class _FragmentAccumulator:
    """Merge either cumulative snapshots or true deltas without duplication."""

    def __init__(self) -> None:
        self.value = ""
        self._mode: str | None = None

    def add(self, fragment: str) -> None:
        if not fragment:
            return
        if not self.value:
            self.value = fragment
            return
        if self._mode is None:
            self._mode = (
                "cumulative" if fragment.startswith(self.value) else "delta"
            )
        if self._mode == "cumulative":
            if len(fragment) >= len(self.value):
                self.value = fragment
            return
        self.value += fragment


def _retain_tool_calls(response: ChatResponse) -> None:
    """Keep executable tool blocks while hiding all model reasoning/drafts."""
    response.content = [
        block
        for block in response.content
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]


def _final_text_response(response: ChatResponse) -> ChatResponse:
    """Expose only validated final text across the OpenAPI model boundary."""
    response.content = [
        {"type": "text", "text": _response_text(response).strip()},
    ]
    return response


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
