# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import pytest
from agentscope.credential import CredentialBase
from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse

from qwenpaw.app.open_api.model_failover import (
    OpenApiModelFailover,
    take_model_route,
)


def _text(value: str) -> ChatResponse:
    return ChatResponse(
        content=[{"type": "text", "text": value}],
        is_last=True,
    )


class StatusError(Exception):
    def __init__(self, status_code: int):
        super().__init__(str(status_code))
        self.status_code = status_code


class StubModel(ChatModelBase):
    def __init__(self, outcomes):
        super().__init__(
            credential=CredentialBase(),
            model="deepseek",
            parameters=ChatModelBase.Parameters(),
            stream=True,
            context_size=32768,
        )
        self.model_name = self.model
        self.outcomes = list(outcomes)
        self.calls = 0

    async def __call__(self, **_kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return await outcome()
        return outcome


@pytest.mark.asyncio
async def test_uses_fallback_for_retryable_http_failure():
    primary = StubModel([StatusError(500)])
    fallback = StubModel([_text("fallback")])
    model = OpenApiModelFailover(
        primary=primary,
        fallback=fallback,
        fallback_label="volcengine/deepseek",
        invocation_id="inv-fallback",
    )

    response = await model(messages=[])

    assert response.content[0]["text"] == "fallback"
    assert primary.calls == 1
    assert fallback.calls == 1
    assert take_model_route("inv-fallback") == {
        "model_route": "fallback",
        "fallback_used": True,
        "primary_model": "deepseek",
        "primary_error": "HTTP 500",
        "fallback_model": "volcengine/deepseek",
        "fallback_succeeded": True,
        "effective_model": "volcengine/deepseek",
    }


@pytest.mark.asyncio
async def test_records_primary_route_without_fallback():
    model = OpenApiModelFailover(
        primary=StubModel([_text("primary")]),
        fallback=StubModel([_text("fallback")]),
        fallback_label="volcengine/deepseek",
        invocation_id="inv-primary",
    )

    response = await model(messages=[])

    assert response.content[0]["text"] == "primary"
    assert take_model_route("inv-primary") == {
        "model_route": "primary",
        "fallback_used": False,
        "primary_model": "deepseek",
        "effective_model": "deepseek",
    }


@pytest.mark.asyncio
async def test_records_failed_fallback_and_keeps_routes_isolated():
    first = OpenApiModelFailover(
        primary=StubModel([StatusError(500)]),
        fallback=StubModel([StatusError(503)]),
        fallback_label="volcengine/deepseek",
        invocation_id="inv-failed-fallback",
    )
    second = OpenApiModelFailover(
        primary=StubModel([_text("primary")]),
        fallback=StubModel([_text("unused")]),
        fallback_label="volcengine/deepseek",
        invocation_id="inv-isolated",
    )

    with pytest.raises(StatusError):
        await first(messages=[])
    await second(messages=[])

    failed_route = take_model_route("inv-failed-fallback")
    assert failed_route["model_route"] == "fallback"
    assert failed_route["fallback_succeeded"] is False
    assert take_model_route("inv-isolated")["model_route"] == "primary"


@pytest.mark.asyncio
async def test_does_not_fallback_for_non_retryable_http_failure():
    primary = StubModel([StatusError(400)])
    fallback = StubModel([_text("fallback")])
    model = OpenApiModelFailover(
        primary=primary,
        fallback=fallback,
        fallback_label="volcengine/deepseek",
    )

    with pytest.raises(StatusError):
        await model(messages=[])

    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_uses_fallback_when_primary_times_out():
    async def slow_response():
        await asyncio.sleep(0.05)
        return _text("late")

    primary = StubModel([slow_response])
    fallback = StubModel([_text("fallback")])
    model = OpenApiModelFailover(
        primary=primary,
        fallback=fallback,
        fallback_label="volcengine/deepseek",
        timeout_seconds=0.001,
    )

    response = await model(messages=[])

    assert response.content[0]["text"] == "fallback"


@pytest.mark.asyncio
async def test_stream_failure_after_output_is_not_replayed():
    async def partial_stream() -> AsyncIterator[ChatResponse]:
        yield _text("partial")
        raise StatusError(500)

    primary = StubModel([partial_stream()])
    fallback = StubModel([_text("fallback")])
    model = OpenApiModelFailover(
        primary=primary,
        fallback=fallback,
        fallback_label="volcengine/deepseek",
    )

    stream = await model(messages=[])
    first = await anext(stream)
    assert first.content[0]["text"] == "partial"
    with pytest.raises(StatusError):
        await anext(stream)
    assert fallback.calls == 0
