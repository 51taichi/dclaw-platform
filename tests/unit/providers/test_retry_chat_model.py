# -*- coding: utf-8 -*-
"""Retry wrapper coverage for non-generator asynchronous streams."""
from __future__ import annotations

import asyncio

import pytest

from qwenpaw import constant
from qwenpaw.providers.retry_chat_model import (
    RateLimitConfig,
    RetryChatModel,
    RetryConfig,
)
from qwenpaw.providers.rate_limiter import (
    get_rate_limiter,
    reset_rate_limiter,
)


@pytest.fixture(autouse=True)
def _isolate_rate_limiter():
    reset_rate_limiter()
    yield
    reset_rate_limiter()


class _TransientError(RuntimeError):
    status_code = 500


class _BusinessError(RuntimeError):
    pass


class _CustomAsyncIterator:
    """An async iterator deliberately not implemented as an async generator."""

    def __init__(self, values, error=None, close_error=None):
        self._values = iter(values)
        self._error = error
        self._close_error = close_error
        self._raised = False
        self.closed = False
        self.close_calls = 0

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
        self.close_calls += 1
        if self._close_error is not None:
            raise self._close_error


class _CustomAsyncIterable:
    """A separate iterable shell used by several SDK streaming APIs."""

    def __init__(self, iterator, close_error=None):
        self.iterator = iterator
        self._close_error = close_error
        self.close_calls = 0

    def __aiter__(self):
        return self.iterator

    async def aclose(self):
        self.close_calls += 1
        if self._close_error is not None:
            raise self._close_error


class _StreamingModel:
    model_name = "custom-stream"
    stream = True

    def __init__(self, streams):
        self._streams = iter(streams)
        self.calls = 0

    async def __call__(self, *_args, **_kwargs):
        self.calls += 1
        return next(self._streams)


class _ImmediateModel:
    model_name = "immediate"
    stream = False

    async def __call__(self, *_args, **_kwargs):
        return "done"


@pytest.mark.asyncio
async def test_agent_rate_limit_does_not_override_platform_model_concurrency(
    monkeypatch,
):
    monkeypatch.setattr(constant, "LLM_MAX_CONCURRENT", 999)
    monkeypatch.setattr(constant, "LLM_MAX_QPM", 0)
    wrapper = RetryChatModel(
        _ImmediateModel(),
        retry_config=RetryConfig(enabled=False),
        rate_limit_config=RateLimitConfig(max_concurrent=10, max_qpm=600),
    )

    assert await wrapper(messages=[]) == "done"

    stats = (await get_rate_limiter()).stats()
    assert stats["max_concurrent"] == 999
    assert stats["max_qpm"] == 0


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
        ],
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


@pytest.mark.asyncio
async def test_unstarted_stream_close_releases_slot_and_closes_inner():
    first = _CustomAsyncIterator(["unused"])
    second = _CustomAsyncIterator(["next"])
    wrapper = RetryChatModel(
        _StreamingModel([first, second]),
        retry_config=RetryConfig(enabled=False),
        rate_limit_config=RateLimitConfig(max_concurrent=1, max_qpm=0),
    )

    result = await wrapper(messages=[])
    await result.aclose()

    limiter = await get_rate_limiter()
    assert first.close_calls == 1
    assert limiter.stats()["current_in_flight"] == 0
    next_result = await asyncio.wait_for(wrapper(messages=[]), timeout=0.2)
    assert [chunk async for chunk in next_result] == ["next"]
    assert limiter.stats()["current_in_flight"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("iterator_close_fails", "iterable_close_fails"),
    [(True, False), (False, True), (True, True)],
)
async def test_business_error_survives_all_independent_close_failures(
    iterator_close_fails,
    iterable_close_fails,
):
    business_error = _BusinessError("provider iteration failed")
    iterator = _CustomAsyncIterator(
        [],
        error=business_error,
        close_error=(
            RuntimeError("iterator close failed")
            if iterator_close_fails
            else None
        ),
    )
    iterable = _CustomAsyncIterable(
        iterator,
        close_error=(
            RuntimeError("iterable close failed")
            if iterable_close_fails
            else None
        ),
    )
    wrapper = RetryChatModel(
        _StreamingModel([iterable]),
        retry_config=RetryConfig(enabled=False),
        rate_limit_config=RateLimitConfig(max_concurrent=1, max_qpm=0),
    )

    result = await wrapper(messages=[])
    with pytest.raises(_BusinessError) as raised:
        await result.__anext__()

    limiter = await get_rate_limiter()
    assert raised.value is business_error
    assert iterator.close_calls == 1
    assert iterable.close_calls == 1
    assert limiter.stats()["current_in_flight"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_kind", ["normal", "break", "cancel"])
async def test_started_stream_releases_slot_exactly_once(exit_kind):
    entered = asyncio.Event()

    class _LifecycleIterator(_CustomAsyncIterator):
        async def __anext__(self):
            if exit_kind == "cancel":
                entered.set()
                await asyncio.Event().wait()
            return await super().__anext__()

    stream = _LifecycleIterator(["chunk"])
    wrapper = RetryChatModel(
        _StreamingModel([stream]),
        retry_config=RetryConfig(enabled=False),
        rate_limit_config=RateLimitConfig(max_concurrent=1, max_qpm=0),
    )
    result = await wrapper(messages=[])

    if exit_kind == "normal":
        assert [chunk async for chunk in result] == ["chunk"]
    elif exit_kind == "break":
        async for chunk in result:
            assert chunk == "chunk"
            break
        await result.aclose()
    else:
        task = asyncio.create_task(result.__anext__())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    limiter = await get_rate_limiter()
    assert stream.close_calls == 1
    assert limiter.stats()["current_in_flight"] == 0
