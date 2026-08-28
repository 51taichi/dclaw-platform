# -*- coding: utf-8 -*-
"""Retry wrapper coverage for non-generator asynchronous streams."""
from __future__ import annotations

import asyncio

import pytest

from qwenpaw.providers.retry_chat_model import (
    RateLimitConfig,
    RetryChatModel,
    RetryConfig,
)


class _TransientError(RuntimeError):
    status_code = 500


class _CustomAsyncIterator:
    """An async iterator deliberately not implemented as an async generator."""

    def __init__(self, values, error=None):
        self._values = iter(values)
        self._error = error
        self._raised = False
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._error is not None and not self._raised:
            self._raised = True
            raise self._error
        try:
            return next(self._values)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def aclose(self):
        self.closed = True


class _CustomAsyncIterable:
    """A separate iterable shell used by several SDK streaming APIs."""

    def __init__(self, iterator):
        self.iterator = iterator

    def __aiter__(self):
        return self.iterator


class _StreamingModel:
    model_name = "custom-stream"
    stream = True

    def __init__(self, streams):
        self._streams = iter(streams)
        self.calls = 0

    async def __call__(self, *_args, **_kwargs):
        self.calls += 1
        return next(self._streams)


@pytest.mark.asyncio
async def test_custom_async_iterator_retries_and_closes_failed_stream(
    monkeypatch,
):
    first = _CustomAsyncIterator([], error=_TransientError("temporary"))
    second = _CustomAsyncIterator(["recovered"])
    model = _StreamingModel([first, second])
    wrapper = RetryChatModel(
        model,
        retry_config=RetryConfig(
            enabled=True,
            max_retries=1,
            backoff_base=0.1,
            backoff_cap=0.1,
        ),
        rate_limit_config=RateLimitConfig(max_concurrent=4, max_qpm=0),
    )

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    result = await wrapper(messages=[])
    assert [chunk async for chunk in result] == ["recovered"]
    assert model.calls == 2
    assert first.closed
    assert second.closed


@pytest.mark.asyncio
async def test_custom_async_iterable_closes_its_inner_iterator(monkeypatch):
    first = _CustomAsyncIterator([], error=_TransientError("temporary"))
    second = _CustomAsyncIterator(["recovered"])
    model = _StreamingModel(
        [
            _CustomAsyncIterable(first),
            _CustomAsyncIterable(second),
        ]
    )
    wrapper = RetryChatModel(
        model,
        retry_config=RetryConfig(
            enabled=True,
            max_retries=1,
            backoff_base=0.1,
            backoff_cap=0.1,
        ),
        rate_limit_config=RateLimitConfig(max_concurrent=4, max_qpm=0),
    )

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    result = await wrapper(messages=[])
    assert [chunk async for chunk in result] == ["recovered"]
    assert first.closed
    assert second.closed
