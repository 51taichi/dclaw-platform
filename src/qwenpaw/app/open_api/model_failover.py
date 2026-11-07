# -*- coding: utf-8 -*-
"""Request-scoped model failover for direct OpenAPI Agent invocations."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import AsyncIterator
from copy import deepcopy
from threading import Lock
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

_route_lock = Lock()
_route_by_invocation: dict[str, dict[str, Any]] = {}


def _model_label(model: ChatModelBase) -> str:
    return str(
        getattr(model, "model_key", None)
        or getattr(model, "model_name", None)
        or type(model).__name__
    )


def _failure_summary(exc: BaseException) -> str:
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        return f"HTTP {status_code}"
    return type(exc).__name__


def begin_model_route(
    invocation_id: str,
    *,
    primary_model: str,
) -> None:
    if not invocation_id:
        return
    with _route_lock:
        _route_by_invocation[invocation_id] = {
            "model_route": "primary",
            "fallback_used": False,
            "primary_model": primary_model,
            "effective_model": primary_model,
        }


def _mark_fallback_started(
    invocation_id: str,
    *,
    fallback_model: str,
    primary_error: str,
) -> None:
    if not invocation_id:
        return
    with _route_lock:
        route = _route_by_invocation.setdefault(invocation_id, {})
        route.update(
            {
                "model_route": "fallback",
                "fallback_used": True,
                "primary_error": primary_error,
                "fallback_model": fallback_model,
                "fallback_succeeded": False,
                "effective_model": fallback_model,
            },
        )


def _mark_fallback_succeeded(invocation_id: str) -> None:
    if not invocation_id:
        return
    with _route_lock:
        route = _route_by_invocation.get(invocation_id)
        if route is not None:
            route["fallback_succeeded"] = True


def take_model_route(invocation_id: str) -> dict[str, Any]:
    """Return and clear route metadata after durable invocation finalization."""
    if not invocation_id:
        return {}
    with _route_lock:
        return deepcopy(_route_by_invocation.pop(invocation_id, {}))


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
        invocation_id: str = "",
        timeout_seconds: float = PRIMARY_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(model_name=primary.model_name, stream=primary.stream)
        self._inner = primary
        self._fallback = fallback
        self._fallback_label = fallback_label
        self._invocation_id = invocation_id
        self._timeout_seconds = timeout_seconds
        begin_model_route(
            invocation_id,
            primary_model=_model_label(primary),
        )

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

        if inspect.isasyncgen(result) or getattr(
            type(result),
            "__aiter__",
            None,
        ):
            return self._stream_with_failover(result, call_kwargs)
        return result

    async def _invoke_fallback(
        self,
        call_kwargs: dict[str, Any],
        exc: BaseException,
    ) -> ChatResponse | AsyncIterator[ChatResponse]:
        logger.warning(
            "OpenAPI primary model failed; using fallback "
            "invocation_id=%s model=%s reason=%s",
            self._invocation_id,
            self._fallback_label,
            _failure_summary(exc),
        )
        _mark_fallback_started(
            self._invocation_id,
            fallback_model=self._fallback_label,
            primary_error=_failure_summary(exc),
        )
        try:
            result = await self._fallback(**call_kwargs)
        except BaseException as fallback_exc:
            logger.error(
                "OpenAPI fallback model failed invocation_id=%s "
                "model=%s reason=%s",
                self._invocation_id,
                self._fallback_label,
                _failure_summary(fallback_exc),
            )
            raise
        if inspect.isasyncgen(result) or getattr(
            type(result),
            "__aiter__",
            None,
        ):
            return self._track_fallback_stream(result)
        _mark_fallback_succeeded(self._invocation_id)
        logger.info(
            "OpenAPI fallback model succeeded invocation_id=%s model=%s",
            self._invocation_id,
            self._fallback_label,
        )
        return result

    async def _track_fallback_stream(
        self,
        stream: AsyncIterator[ChatResponse],
    ) -> AsyncIterator[ChatResponse]:
        async for item in stream:
            yield item
        _mark_fallback_succeeded(self._invocation_id)
        logger.info(
            "OpenAPI fallback model succeeded invocation_id=%s model=%s",
            self._invocation_id,
            self._fallback_label,
        )

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
            if inspect.isasyncgen(fallback_result) or getattr(
                type(fallback_result),
                "__aiter__",
                None,
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
    invocation_id: str = "",
) -> bool:
    """Install failover on a request-owned Agent model instance."""
    primary = getattr(agent, "model", None)
    if primary is None:
        return False
    agent.model = OpenApiModelFailover(
        primary=primary,
        fallback=fallback_model,
        fallback_label=fallback_label,
        invocation_id=invocation_id,
    )
    return True
