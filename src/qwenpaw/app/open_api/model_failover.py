# -*- coding: utf-8 -*-
"""Request-scoped model failover for direct OpenAPI Agent invocations."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import AsyncIterator
from typing import Any, Literal, Type

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

PRIMARY_TIMEOUT_SECONDS = 20.0
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_RETRYABLE_TYPE_MARKERS = (
    "timeout",
    "connection",
    "ratelimit",
    "rate_limit",
    "internalserver",
)


def _is_retryable_failure(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, ConnectionError)):
        return True
    if getattr(exc, "status_code", None) in _RETRYABLE_STATUS_CODES:
        return True
    return any(
        marker in type(exc).__name__.lower()
        for marker in _RETRYABLE_TYPE_MARKERS
    )


class OpenApiModelFailover(ChatModelBase):
    """Try one configured fallback without replaying the Agent request."""

    def __init__(
        self,
        *,
        primary: ChatModelBase,
        fallback: ChatModelBase,
        fallback_label: str,
        timeout_seconds: float = PRIMARY_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(model_name=primary.model_name, stream=primary.stream)
        self._inner = primary
        self._fallback = fallback
        self._fallback_label = fallback_label
        self._timeout_seconds = timeout_seconds

    @property
    def model_key(self) -> str | None:
        return getattr(self._inner, "model_key", None)

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncIterator[ChatResponse]:
        call_kwargs = {
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "structured_model": structured_model,
            **kwargs,
        }
        try:
            result = await asyncio.wait_for(
                self._inner(**call_kwargs),
                timeout=self._timeout_seconds,
            )
        except BaseException as exc:
            if not _is_retryable_failure(exc):
                raise
            return await self._invoke_fallback(call_kwargs, exc)

        if inspect.isasyncgen(result) or hasattr(result, "__aiter__"):
            return self._stream_with_failover(result, call_kwargs)
        return result

    async def _invoke_fallback(
        self,
        call_kwargs: dict[str, Any],
        exc: BaseException,
    ) -> ChatResponse | AsyncIterator[ChatResponse]:
        logger.warning(
            "OpenAPI primary model failed; using fallback model=%s "
            "reason=%s",
            self._fallback_label,
            type(exc).__name__,
        )
        return await self._fallback(**call_kwargs)

    async def _stream_with_failover(
        self,
        primary_stream: AsyncIterator[ChatResponse],
        call_kwargs: dict[str, Any],
    ) -> AsyncIterator[ChatResponse]:
        emitted = False
        try:
            iterator = primary_stream.__aiter__()
            while True:
                try:
                    item = await asyncio.wait_for(
                        iterator.__anext__(),
                        timeout=self._timeout_seconds,
                    )
                except StopAsyncIteration:
                    return
                emitted = True
                yield item
        except BaseException as exc:
            if emitted or not _is_retryable_failure(exc):
                raise
            fallback_result = await self._invoke_fallback(call_kwargs, exc)
            if inspect.isasyncgen(fallback_result) or hasattr(
                fallback_result,
                "__aiter__",
            ):
                async for item in fallback_result:
                    yield item
            else:
                yield fallback_result


def install_open_api_model_failover(
    agent: Any,
    fallback_model: ChatModelBase,
    *,
    fallback_label: str,
) -> bool:
    """Install failover on a request-owned Agent model instance."""
    primary = getattr(agent, "model", None)
    if primary is None:
        return False
    agent.model = OpenApiModelFailover(
        primary=primary,
        fallback=fallback_model,
        fallback_label=fallback_label,
    )
    return True
