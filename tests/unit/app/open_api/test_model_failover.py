# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import pytest
from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse

from qwenpaw.app.open_api.model_failover import OpenApiModelFailover


def _text(value: str) -> ChatResponse:
    return ChatResponse(content=[{"type": "text", "text": value}])


class StatusError(Exception):
    def __init__(self, status_code: int):
        super().__init__(str(status_code))
        self.status_code = status_code


class StubModel(ChatModelBase):
    def __init__(self, outcomes):
        super().__init__(model_name="deepseek", stream=True)
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
    )

    response = await model(messages=[])

    assert response.content[0]["text"] == "fallback"
    assert primary.calls == 1
    assert fallback.calls == 1


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
