# -*- coding: utf-8 -*-
"""Provider-boundary adapters that preserve verified supplier references."""
from __future__ import annotations

from typing import Any, AsyncGenerator, AsyncIterator, Type

from agentscope.model import AnthropicChatModel, GeminiChatModel
from agentscope.model._model_response import ChatResponse
from pydantic import BaseModel


def _attach_reference(
    parsed: ChatResponse,
    reference: Any,
    source: str,
) -> ChatResponse:
    """Write an explicit reference only when the raw adapter field exists."""
    if isinstance(reference, str) and reference.strip():
        parsed.supplier_billing_reference = reference.strip()
        parsed.supplier_billing_reference_source = source
    return parsed


class BillingAnthropicChatModel(AnthropicChatModel):
    """Anthropic adapter that labels its raw message IDs for billing."""

    billing_provider_kind = "anthropic"

    async def _parse_anthropic_completion_response(
        self,
        start_datetime: Any,
        response: Any,
        structured_model: Type[BaseModel] | None = None,
    ) -> ChatResponse:
        parsed = await super()._parse_anthropic_completion_response(
            start_datetime,
            response,
            structured_model,
        )
        return _attach_reference(
            parsed,
            _raw_field(response, "id"),
            "anthropic.message.id",
        )

    async def _parse_anthropic_stream_completion_response(
        self,
        start_datetime: Any,
        response: AsyncIterator[Any],
        structured_model: Type[BaseModel] | None = None,
    ) -> AsyncGenerator[ChatResponse, None]:
        reference: str | None = None

        async def captured_events() -> AsyncGenerator[Any, None]:
            nonlocal reference
            async for event in response:
                if (
                    reference is None
                    and _raw_field(event, "type") == "message_start"
                ):
                    reference = _raw_field(_raw_field(event, "message"), "id")
                yield event

        parsed_stream = super()._parse_anthropic_stream_completion_response(
            start_datetime,
            captured_events(),
            structured_model,
        )
        async for parsed in parsed_stream:
            yield _attach_reference(
                parsed,
                reference,
                "anthropic.message.id",
            )


class BillingGeminiChatModel(GeminiChatModel):
    """Gemini adapter that labels raw ``response_id`` fields for billing."""

    billing_provider_kind = "gemini"

    def _parse_gemini_generation_response(
        self,
        start_datetime: Any,
        response: Any,
        structured_model: Type[BaseModel] | None = None,
    ) -> ChatResponse:
        parsed = super()._parse_gemini_generation_response(
            start_datetime,
            response,
            structured_model,
        )
        return _attach_reference(
            parsed,
            _raw_field(response, "response_id"),
            "gemini.response_id",
        )

    async def _parse_gemini_stream_generation_response(
        self,
        start_datetime: Any,
        response: AsyncIterator[Any],
        structured_model: Type[BaseModel] | None = None,
    ) -> AsyncGenerator[ChatResponse, None]:
        reference: str | None = None

        async def captured_chunks() -> AsyncGenerator[Any, None]:
            nonlocal reference
            async for chunk in response:
                if reference is None:
                    reference = _raw_field(chunk, "response_id")
                yield chunk

        async for parsed in super()._parse_gemini_stream_generation_response(
            start_datetime,
            captured_chunks(),
            structured_model,
        ):
            yield _attach_reference(
                parsed,
                reference,
                "gemini.response_id",
            )


def _raw_field(value: Any, name: str) -> Any:
    """Read vendor response fields without trusting dict-like ChatResponse."""
    try:
        return getattr(value, name, None)
    except (AttributeError, KeyError, TypeError):
        return None


__all__ = ["BillingAnthropicChatModel", "BillingGeminiChatModel"]
