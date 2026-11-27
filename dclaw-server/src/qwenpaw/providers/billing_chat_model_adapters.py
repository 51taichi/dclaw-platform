# -*- coding: utf-8 -*-
"""Provider-boundary adapters that preserve verified supplier references."""
from __future__ import annotations

from typing import Any, AsyncGenerator, AsyncIterator, Type

from agentscope.credential import AnthropicCredential, GeminiCredential
from agentscope.model import AnthropicChatModel, ChatResponse, GeminiChatModel
from pydantic import BaseModel, SecretStr

from ..app.billing.supplier_reference_sidecar import stash_supplier_reference


def _attach_reference(
    parsed: ChatResponse,
    reference: Any,
    source: str,
) -> ChatResponse:
    """Write an explicit reference only when the raw adapter field exists."""
    stash_supplier_reference(parsed, reference, source)
    return parsed


class BillingAnthropicChatModel(AnthropicChatModel):
    """Anthropic adapter that labels its raw message IDs for billing."""

    billing_provider_kind = "anthropic"

    def __init__(
        self,
        model_name: str | None = None,
        *,
        model: str | None = None,
        credential: AnthropicCredential | None = None,
        api_key: str | None = None,
        generate_kwargs: dict[str, Any] | None = None,
        stream_tool_parsing: bool | None = None,
        max_tokens: int | None = None,
        parameters: AnthropicChatModel.Parameters | None = None,
        stream: bool = True,
        **kwargs: Any,
    ) -> None:
        del stream_tool_parsing
        model_id = model or model_name
        if not isinstance(model_id, str) or not model_id:
            raise ValueError("model is required")
        client_kwargs = dict(kwargs.pop("client_kwargs", None) or {})
        if credential is None:
            credential = AnthropicCredential(
                api_key=SecretStr(api_key or ""),
                base_url=client_kwargs.pop("base_url", None),
            )
        self.generate_kwargs = dict(generate_kwargs or {})
        parameter_values = {
            key: self.generate_kwargs[key]
            for key in AnthropicChatModel.Parameters.model_fields
            if key in self.generate_kwargs
            and self.generate_kwargs[key] is not None
        }
        if max_tokens is not None:
            parameter_values["max_tokens"] = max_tokens
        super().__init__(
            credential=credential,
            model=model_id,
            parameters=(
                parameters
                or AnthropicChatModel.Parameters(**parameter_values)
            ),
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
        messages: list[Any],
        tools: list[dict] | None = None,
        tool_choice: Any = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> Any:
        call_kwargs = {**self.generate_kwargs, **kwargs}
        for key in AnthropicChatModel.Parameters.model_fields:
            call_kwargs.pop(key, None)
        if structured_model is not None:
            return await self.generate_structured_output(
                messages,
                structured_model,
                **call_kwargs,
            )
        return await super().__call__(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            **call_kwargs,
        )

    async def _parse_anthropic_completion_response(
        self,
        start_datetime: Any,
        response: Any,
        structured_model: Type[BaseModel] | None = None,
    ) -> ChatResponse:
        parsed = await super()._parse_anthropic_completion_response(
            start_datetime,
            response,
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

    def __init__(
        self,
        model_name: str | None = None,
        *,
        model: str | None = None,
        credential: GeminiCredential | None = None,
        api_key: str | None = None,
        generate_kwargs: dict[str, Any] | None = None,
        parameters: GeminiChatModel.Parameters | None = None,
        stream: bool = True,
        **kwargs: Any,
    ) -> None:
        model_id = model or model_name
        if not isinstance(model_id, str) or not model_id:
            raise ValueError("model is required")
        if credential is None:
            credential = GeminiCredential(api_key=SecretStr(api_key or ""))
        self.generate_kwargs = dict(generate_kwargs or {})
        parameter_values = {
            key: self.generate_kwargs[key]
            for key in GeminiChatModel.Parameters.model_fields
            if key in self.generate_kwargs
            and self.generate_kwargs[key] is not None
        }
        super().__init__(
            credential=credential,
            model=model_id,
            parameters=(
                parameters or GeminiChatModel.Parameters(**parameter_values)
            ),
            stream=stream,
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
        messages: list[Any],
        tools: list[dict] | None = None,
        tool_choice: Any = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> Any:
        call_kwargs = {**self.generate_kwargs, **kwargs}
        for key in GeminiChatModel.Parameters.model_fields:
            call_kwargs.pop(key, None)
        if structured_model is not None:
            return await self.generate_structured_output(
                messages,
                structured_model,
                **call_kwargs,
            )
        return await super().__call__(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            **call_kwargs,
        )

    def _parse_completion_response(
        self,
        start_datetime: Any,
        response: Any,
        structured_model: Type[BaseModel] | None = None,
    ) -> ChatResponse:
        parsed = super()._parse_completion_response(
            start_datetime,
            response,
        )
        return _attach_reference(
            parsed,
            _raw_field(response, "response_id"),
            "gemini.response_id",
        )

    async def _parse_stream_response(
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

        async for parsed in super()._parse_stream_response(
            start_datetime,
            captured_chunks(),
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
