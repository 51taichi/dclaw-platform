# -*- coding: utf-8 -*-
"""OpenAI chat model compatibility wrappers."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Type

from agentscope.credential import OpenAICredential
from agentscope.model import ChatResponse, OpenAIChatModel
from openai import NOT_GIVEN
from pydantic import BaseModel, SecretStr

from qwenpaw.local_models.tag_parser import (
    parse_tool_calls_from_text,
    text_contains_tool_call_tag,
)
from qwenpaw.agents.message_compat import LegacyToolCallBlock
from qwenpaw.providers.openai_response_diagnostics import (
    OpenAIResponseDiagnostics,
    is_openai_response_diagnostics_capture_enabled,
    stash_openai_response_diagnostics,
)


logger = logging.getLogger(__name__)


def _is_json_object_prompt_rejection(exc: Exception) -> bool:
    """Match the provider error raised for an invalid JSON-mode prompt."""
    status = getattr(exc, "status_code", None)
    message = str(exc).lower()
    is_bad_request = status == 400 or "error code: 400" in message
    return bool(
        is_bad_request
        and "response_format" in message
        and "json_object" in message
        and "prompt" in message
        and "json" in message
        and "must contain" in message
    )


def _uses_json_object_response_format(value: Any) -> bool:
    """Return whether an OpenAI request option enables legacy JSON mode."""
    if isinstance(value, dict):
        return value.get("type") == "json_object"
    return getattr(value, "type", None) == "json_object"


def _clone_with_overrides(obj: Any, **overrides: Any) -> Any:
    """Clone a stream object into a mutable namespace with overrides."""
    data = dict(getattr(obj, "__dict__", {}))
    data.update(overrides)
    return SimpleNamespace(**data)


def _sanitize_tool_call(tool_call: Any) -> Any | None:
    """Normalize a tool call for parser safety, or drop it if unusable."""
    if not hasattr(tool_call, "index"):
        return None

    function = getattr(tool_call, "function", None)
    if function is None:
        return None

    has_name = hasattr(function, "name")
    has_arguments = hasattr(function, "arguments")

    raw_name = getattr(function, "name", "")
    if isinstance(raw_name, str):
        safe_name = raw_name
    elif raw_name is None:
        safe_name = ""
    else:
        safe_name = str(raw_name)

    raw_arguments = getattr(function, "arguments", "")
    if isinstance(raw_arguments, str):
        safe_arguments = raw_arguments
    elif raw_arguments is None:
        safe_arguments = ""
    else:
        try:
            safe_arguments = json.dumps(raw_arguments, ensure_ascii=False)
        except (TypeError, ValueError):
            safe_arguments = str(raw_arguments)

    if (
        has_name
        and has_arguments
        and isinstance(raw_name, str)
        and isinstance(
            raw_arguments,
            str,
        )
    ):
        return tool_call

    safe_function = SimpleNamespace(
        name=safe_name,
        arguments=safe_arguments,
    )
    return _clone_with_overrides(tool_call, function=safe_function)


def _sanitize_chunk(chunk: Any) -> Any:
    """Drop/normalize malformed tool-calls in a streaming chunk."""
    choices = getattr(chunk, "choices", None)
    if not choices:
        return chunk

    sanitized_choices: list[Any] = []
    changed = False

    for choice in choices:
        delta = getattr(choice, "delta", None)
        if delta is None:
            sanitized_choices.append(choice)
            continue

        raw_tool_calls = getattr(delta, "tool_calls", None)
        if not raw_tool_calls:
            sanitized_choices.append(choice)
            continue

        choice_changed = False
        sanitized_tool_calls: list[Any] = []
        for tool_call in raw_tool_calls:
            sanitized = _sanitize_tool_call(tool_call)
            if sanitized is not tool_call:
                choice_changed = True
            if sanitized is not None:
                sanitized_tool_calls.append(sanitized)

        if choice_changed:
            changed = True
            sanitized_delta = _clone_with_overrides(
                delta,
                tool_calls=sanitized_tool_calls,
            )
            sanitized_choice = _clone_with_overrides(
                choice,
                delta=sanitized_delta,
            )
            sanitized_choices.append(sanitized_choice)
            continue

        sanitized_choices.append(choice)

    if not changed:
        return chunk
    return _clone_with_overrides(chunk, choices=sanitized_choices)


def _sanitize_stream_item(item: Any) -> Any:
    """Sanitize either plain stream chunks or structured stream items."""
    if hasattr(item, "chunk"):
        chunk = item.chunk
        sanitized_chunk = _sanitize_chunk(chunk)
        if sanitized_chunk is chunk:
            return item
        return _clone_with_overrides(item, chunk=sanitized_chunk)

    return _sanitize_chunk(item)


def attach_openai_supplier_billing_reference(
    parsed: ChatResponse,
    raw_response: Any,
    *,
    source: str = "openai.chat.completion.id",
) -> ChatResponse:
    """Attach only an OpenAI upstream ID as explicit billing evidence.

    The generic ``ChatResponse.id`` is deliberately not consulted by billing:
    AgentScope may synthesize it.  This adapter is the trusted boundary that
    reads the verified OpenAI response object and labels its provenance.
    """
    try:
        reference = getattr(raw_response, "id", None)
    except (AttributeError, KeyError, TypeError):
        reference = None
    from ..app.billing.supplier_reference_sidecar import (
        stash_supplier_reference,
    )

    stash_supplier_reference(parsed, reference, source)
    return parsed


def _safe_token_usage(raw_usage: Any) -> dict[str, int]:
    if raw_usage is None:
        return {}
    result: dict[str, int] = {}
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = getattr(raw_usage, name, None)
        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
        ):
            result[name] = value
    return result


def _reasoning_fragment(message: Any) -> str:
    for name in ("reasoning_content", "reasoning"):
        value = getattr(message, name, None)
        if isinstance(value, str):
            return value
    model_extra = getattr(message, "model_extra", None)
    if isinstance(model_extra, dict):
        for name in ("reasoning_content", "reasoning"):
            value = model_extra.get(name)
            if isinstance(value, str):
                return value
    return ""


def _completion_diagnostics(response: Any) -> OpenAIResponseDiagnostics:
    finish_reason: str | None = None
    content_length = 0
    reasoning_length = 0
    for choice in getattr(response, "choices", None) or []:
        raw_finish = getattr(choice, "finish_reason", None)
        if isinstance(raw_finish, str) and raw_finish:
            finish_reason = raw_finish
        message = getattr(choice, "message", None)
        if message is None:
            continue
        content = getattr(message, "content", None)
        if isinstance(content, str):
            content_length += len(content)
        reasoning_length += len(_reasoning_fragment(message))
    return OpenAIResponseDiagnostics(
        finish_reason=finish_reason,
        content_length=content_length,
        reasoning_length=reasoning_length,
        usage=_safe_token_usage(getattr(response, "usage", None)),
    )


class _SanitizedStream:
    """Proxy OpenAI async stream that sanitizes each emitted item and
    captures ``extra_content`` from tool-call chunks (used by Gemini
    thinking models to carry ``thought_signature``)."""

    def __init__(self, stream: Any):
        self._stream = stream
        self._ctx_stream: Any | None = None
        self.extra_contents: dict[str, Any] = {}
        self.supplier_response_id: str | None = None
        self.finish_reason: str | None = None
        self.content_length = 0
        self.reasoning_length = 0
        self.usage: dict[str, int] = {}
        self.capture_diagnostics = (
            is_openai_response_diagnostics_capture_enabled()
        )

    async def __aenter__(self) -> "_SanitizedStream":
        self._ctx_stream = await self._stream.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc: Any,
        tb: Any,
    ) -> bool | None:
        return await self._stream.__aexit__(exc_type, exc, tb)

    def __aiter__(self) -> "_SanitizedStream":
        return self

    async def __anext__(self) -> Any:
        if self._ctx_stream is None:
            raise StopAsyncIteration
        item = await self._ctx_stream.__anext__()
        self._capture_response_metadata(item)
        return _sanitize_stream_item(item)

    def _capture_response_metadata(  # pylint: disable=too-many-branches
        self,
        item: Any,
    ) -> None:
        """Capture tool metadata and content-free supplier diagnostics."""
        chunk = getattr(item, "chunk", item)
        if self.supplier_response_id is None:
            try:
                raw_id = getattr(chunk, "id", None)
            except (AttributeError, KeyError, TypeError):
                raw_id = None
            if isinstance(raw_id, str) and raw_id.strip():
                self.supplier_response_id = raw_id.strip()
        choices = getattr(chunk, "choices", None) or []
        for choice in choices:
            raw_finish = getattr(choice, "finish_reason", None)
            if (
                self.capture_diagnostics
                and isinstance(raw_finish, str)
                and raw_finish
            ):
                self.finish_reason = raw_finish
            delta = getattr(choice, "delta", None)
            if not delta:
                continue
            content = getattr(delta, "content", None)
            if self.capture_diagnostics and isinstance(content, str):
                self.content_length += len(content)
            if self.capture_diagnostics:
                self.reasoning_length += len(_reasoning_fragment(delta))
            for tc in getattr(delta, "tool_calls", None) or []:
                tc_id = getattr(tc, "id", None)
                if not tc_id:
                    continue
                extra = getattr(tc, "extra_content", None)
                if extra is None:
                    model_extra = getattr(tc, "model_extra", None)
                    if isinstance(model_extra, dict):
                        extra = model_extra.get("extra_content")
                if extra:
                    self.extra_contents[tc_id] = extra
        if self.capture_diagnostics:
            usage = _safe_token_usage(getattr(chunk, "usage", None))
            if usage:
                self.usage = usage

    def diagnostics(self) -> OpenAIResponseDiagnostics:
        return OpenAIResponseDiagnostics(
            finish_reason=self.finish_reason,
            content_length=self.content_length,
            reasoning_length=self.reasoning_length,
            usage=dict(self.usage),
        )


def _sanitize_boolean_schemas(schema: Any) -> Any:
    """Recursively replace boolean JSON Schema values with proper objects.

    Some MCP servers emit boolean schemas such as ``true`` (any value) or
    ``false`` (no valid value), which is legal per JSON Schema spec but
    rejected by strict LLM providers like DeepSeek V4.  This function
    converts them to their object equivalents:

        true  → {}           (empty schema = accept anything)
        false → {"not": {}}  (impossible schema = reject everything)

    It also strips problematic but common non-standard usages:
    - ``additionalProperties: true``  → removed (it's the default)
    - ``required: true`` inside a property definition → removed
      (non-standard; real JSON Schema uses ``required: ["field"]`` on the
       parent object, not a boolean inside the property itself)
    """
    if schema is True:
        return {}
    if schema is False:
        return {"not": {}}
    if not isinstance(schema, dict):
        return schema

    result: dict[str, Any] = {}
    for key, value in schema.items():
        # Strip `additionalProperties: true` — it is the default and
        # some strict validators reject the explicit boolean form.
        if key == "additionalProperties" and value is True:
            continue
        # Strip `required: <bool>` inside property schemas.
        # Some MCP servers (e.g. reetp14/openalex-mcp) mistakenly write
        # `"required": true` inside a property definition instead of
        # listing the field in the parent object's `required` array.
        # DeepSeek V4 reports: "true is not of type 'array'"
        if key == "required" and isinstance(value, bool):
            continue
        if isinstance(value, bool):
            result[key] = {} if value else {"not": {}}
        elif isinstance(value, dict):
            result[key] = _sanitize_boolean_schemas(value)
        elif isinstance(value, list):
            result[key] = [
                _sanitize_boolean_schemas(item)
                if isinstance(item, (dict, bool))
                else item
                for item in value
            ]
        else:
            result[key] = value
    return result


def _sanitize_tool_schemas(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Sanitize tool function schemas to be compatible with strict providers.

    Walks the ``parameters`` of each tool's function definition and replaces
    boolean JSON Schema values that providers like DeepSeek V4 reject.
    """
    sanitized = []
    for tool in tools:
        if not isinstance(tool, dict):
            sanitized.append(tool)
            continue
        func = tool.get("function")
        if not isinstance(func, dict):
            sanitized.append(tool)
            continue
        params = func.get("parameters")
        if not isinstance(params, dict):
            sanitized.append(tool)
            continue
        sanitized_params = _sanitize_boolean_schemas(params)
        sanitized.append(
            {**tool, "function": {**func, "parameters": sanitized_params}},
        )
    return sanitized


class OpenAIChatModelCompat(OpenAIChatModel):
    """OpenAIChatModel with robust parsing for malformed tool-call chunks
    and transparent ``extra_content`` (Gemini thought_signature) relay."""

    billing_provider_kind = "openai"

    def __init__(
        self,
        model_name: str | None = None,
        *,
        model: str | None = None,
        credential: OpenAICredential | None = None,
        api_key: str | None = None,
        generate_kwargs: dict[str, Any] | None = None,
        stream_tool_parsing: bool | None = None,
        parameters: OpenAIChatModel.Parameters | None = None,
        stream: bool = True,
        **kwargs: Any,
    ) -> None:
        """Translate DClaw's persisted 1.x model config to AgentScope 2."""
        del stream_tool_parsing
        model_id = model or model_name
        if not isinstance(model_id, str) or not model_id:
            raise ValueError("model is required")
        client_kwargs = dict(kwargs.pop("client_kwargs", None) or {})
        if credential is None:
            credential = OpenAICredential(
                api_key=SecretStr(api_key or ""),
                base_url=client_kwargs.pop("base_url", None),
            )
        self.generate_kwargs = dict(generate_kwargs or {})
        if parameters is None:
            parameter_values = {
                key: self.generate_kwargs[key]
                for key in OpenAIChatModel.Parameters.model_fields
                if key in self.generate_kwargs
                and self.generate_kwargs[key] is not None
            }
            parameters = OpenAIChatModel.Parameters(**parameter_values)
        super().__init__(
            credential=credential,
            model=model_id,
            parameters=parameters,
            stream=stream,
            client_kwargs=client_kwargs or None,
            **kwargs,
        )

    @property
    def model_name(self) -> str:
        return self.model

    @model_name.setter
    def model_name(self, value: str) -> None:
        self.model = value

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Any = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Retry legacy JSON mode once when a provider rejects the prompt.

        Some OpenAI-compatible providers require the literal word ``json``
        in the prompt whenever ``response_format=json_object`` is configured.
        Normal ReAct turns do not need structured output, so retrying without
        that optional request parameter is safe and avoids a blank response.
        """
        call_kwargs = {**self.generate_kwargs, **kwargs}
        for key in OpenAIChatModel.Parameters.model_fields:
            call_kwargs.pop(key, None)
        if structured_model is not None:
            call_kwargs.pop("response_format", None)
            return await self.generate_structured_output(
                messages,
                structured_model,
                **call_kwargs,
            )
        try:
            return await super().__call__(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                **call_kwargs,
            )
        except Exception as exc:
            response_format = call_kwargs.get(
                "response_format",
                self.generate_kwargs.get("response_format"),
            )
            if (
                structured_model is not None
                or not _uses_json_object_response_format(response_format)
                or not _is_json_object_prompt_rejection(exc)
            ):
                raise

            logger.warning(
                "Provider rejected response_format=json_object for a normal "
                "chat prompt; retrying once without response_format",
            )
            retry_kwargs = dict(call_kwargs)
            retry_kwargs["response_format"] = NOT_GIVEN
            return await super().__call__(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                **retry_kwargs,
            )

    def _format_tools_json_schemas(
        self,
        schemas: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Format tool schemas while stripping boolean sub-schemas.

        Some MCP servers declare parameters using JSON Schema boolean values
        (e.g. ``additionalProperties: true``, ``items: true``) which are valid
        per spec but rejected by strict providers such as DeepSeek V4 with the
        error ``true is not of type 'array'``.  This override sanitizes the
        schemas before forwarding them to the base implementation.
        """
        return super()._format_tools_json_schemas(
            _sanitize_tool_schemas(schemas),
        )

    def _parse_openai_completion_response(
        self,
        start_datetime: datetime,
        response: Any,
        structured_model: Type[BaseModel] | None = None,
    ) -> ChatResponse:
        """Label the raw OpenAI completion ID before it becomes generic."""
        parsed = super()._parse_completion_response(
            start_datetime,
            response,
        )
        if is_openai_response_diagnostics_capture_enabled():
            stash_openai_response_diagnostics(
                parsed,
                _completion_diagnostics(response),
            )
        return attach_openai_supplier_billing_reference(parsed, response)

    def _parse_completion_response(
        self,
        start_datetime: datetime,
        response: Any,
        audio_format: str = "wav",
    ) -> ChatResponse:
        parsed = super()._parse_completion_response(
            start_datetime,
            response,
            audio_format,
        )
        if is_openai_response_diagnostics_capture_enabled():
            stash_openai_response_diagnostics(
                parsed,
                _completion_diagnostics(response),
            )
        return attach_openai_supplier_billing_reference(parsed, response)

    async def _parse_stream_response(
        self,
        start_datetime: datetime,
        response: Any,
    ) -> AsyncGenerator[ChatResponse, None]:
        async for parsed in self._parse_openai_stream_response(
            start_datetime,
            response,
        ):
            yield parsed

    # pylint: disable=too-many-branches, too-many-statements
    async def _parse_openai_stream_response(
        self,
        start_datetime: datetime,
        response: Any,
        structured_model: Type[BaseModel] | None = None,
    ) -> AsyncGenerator[ChatResponse, None]:
        sanitized_response = _SanitizedStream(response)

        # Stable tag-extracted tool-call blocks across streaming chunks.
        # Keyed by positional strings so IDs stay consistent as chunks
        # accumulate.  Two sources: "thinking" blocks and plain "text" blocks.
        _think_tool_calls: dict[str, dict] = {}
        _text_tool_calls: dict[str, dict] = {}

        async for parsed in super()._parse_stream_response(
            start_datetime=start_datetime,
            response=sanitized_response,
        ):
            # Filter out malformed tool_use blocks (null id or empty name)
            # emitted by some OpenAI-compatible models, to prevent bad entries
            # from being persisted into session history (issue #4185).
            parsed.content = [
                b
                for b in parsed.content
                if not (
                    getattr(b, "type", None) == "tool_call"
                    and (
                        not isinstance(getattr(b, "id", None), str)
                        or not getattr(b, "name", None)
                    )
                )
            ]

            # Attach extra_content (Gemini thought_signature) to tool_use
            # blocks.
            if sanitized_response.extra_contents:
                for block in parsed.content:
                    if getattr(block, "type", None) != "tool_call":
                        continue
                    tool_id = getattr(block, "id", None)
                    if not isinstance(tool_id, str):
                        continue
                    ec = sanitized_response.extra_contents.get(tool_id)
                    if ec:
                        index = parsed.content.index(block)
                        parsed.content[index] = LegacyToolCallBlock(
                            id=block.id,
                            name=block.name,
                            input=block.input,
                            state=block.state,
                            suggested_rules=block.suggested_rules,
                            extra_content=ec,
                        )

            # Check whether the response already carries structured tool_use
            # blocks (either from the model or from extra_content above).
            has_tool_use = any(
                getattr(b, "type", None) == "tool_call"
                for b in parsed.content
            )

            if has_tool_use:
                # Structured tool calls arrived — discard any tag-derived
                # ones, so we don't produce duplicates.
                _think_tool_calls.clear()
                _text_tool_calls.clear()
            else:
                # --- 1. Scan thinking blocks ---
                for block in parsed.content:
                    if getattr(block, "type", None) != "thinking":
                        continue
                    thinking_text = block.thinking or ""
                    if not text_contains_tool_call_tag(thinking_text):
                        continue

                    think_parsed = parse_tool_calls_from_text(thinking_text)
                    if not think_parsed.tool_calls:
                        continue

                    # Keep only the text before the first <tool_call>.
                    # Everything after is the model's simulated continuation
                    # (may include </tool_response>, </think> artefacts).
                    block.thinking = think_parsed.text_before.strip()

                    _think_tool_calls = {
                        f"thinking_{i}": LegacyToolCallBlock(
                            id=f"think_call_{i}",
                            name=ptc.name,
                            input=json.dumps(ptc.arguments),
                            raw_input=ptc.raw_arguments,
                        )
                        for i, ptc in enumerate(think_parsed.tool_calls)
                    }

                # --- 2. Scan text/content blocks ---
                # Some models emit <tool_call> tags directly in their
                # response text instead of (or in addition to) thinking.
                new_content: list | None = None
                for i, block in enumerate(parsed.content):
                    if getattr(block, "type", None) != "text":
                        continue
                    text = block.text or ""
                    if not text_contains_tool_call_tag(text):
                        continue

                    text_parsed = parse_tool_calls_from_text(text)
                    # Keep only text_before; discard the tag block and
                    # everything after (same rationale as thinking).
                    clean_text = text_parsed.text_before.strip()
                    block.text = clean_text

                    if text_parsed.tool_calls:
                        _text_tool_calls = {
                            f"text_{j}": LegacyToolCallBlock(
                                id=f"text_call_{j}",
                                name=ptc.name,
                                input=json.dumps(ptc.arguments),
                                raw_input=ptc.raw_arguments,
                            )
                            for j, ptc in enumerate(text_parsed.tool_calls)
                        }

                    # If the text block is now empty, mark it for removal.
                    if not clean_text:
                        if new_content is None:
                            new_content = list(parsed.content)
                        new_content[i] = None  # type: ignore[index]

                if new_content is not None:
                    parsed.content = [b for b in new_content if b is not None]

                extra = list(_think_tool_calls.values()) + list(
                    _text_tool_calls.values(),
                )
                if extra:
                    parsed.content = list(parsed.content) + extra

            attach_openai_supplier_billing_reference(
                parsed,
                SimpleNamespace(id=sanitized_response.supplier_response_id),
                source="openai.chat.chunk.id",
            )
            if sanitized_response.capture_diagnostics:
                stash_openai_response_diagnostics(
                    parsed,
                    sanitized_response.diagnostics(),
                )

            yield parsed
