# -*- coding: utf-8 -*-
"""Retry wrapper for ChatModelBase instances.

Transparently retries LLM API calls on transient errors (rate-limit,
timeout, connection) with configurable exponential back-off.

Concurrency and rate-limit control (LLMRateLimiter):
- A global semaphore caps the number of concurrent in-flight LLM calls,
  preventing a burst of requests from hammering the upstream API.
- When a 429 is received every concurrent caller is paused for the same
  duration (plus per-caller jitter) before re-trying, eliminating the
  thundering-herd problem where multiple callers retry at the same instant.

Semaphore ownership rules:
- Non-streaming: __call__'s finally block always releases the slot
  (owns_semaphore stays True throughout).
- Streaming: ownership transfers to an explicit async-iterator owner before
  __call__ returns. The owner can therefore close the already-created inner
  stream and release its slot even if no chunk is ever requested.
- Cancellation safety: the boolean flag `acquired` tracks whether the
  semaphore slot has actually been taken; the final block only releases
  when acquired is True, preventing a spurious release on CancelledError.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator
from dataclasses import dataclass
from typing import Any

from agentscope.model import ChatModelBase
from agentscope.model._model_response import ChatResponse
from agentscope_runtime.engine.schemas.exception import (
    RateLimitExceededException,
)

from ..constant import (
    LLM_ACQUIRE_TIMEOUT,
    LLM_BACKOFF_BASE,
    LLM_BACKOFF_CAP,
    LLM_MAX_CONCURRENT,
    LLM_MAX_RETRIES,
    LLM_MAX_QPM,
    LLM_RATE_LIMIT_JITTER,
    LLM_RATE_LIMIT_PAUSE,
)
from .model_capability_cache import get_capability_cache
from .rate_limiter import LLMRateLimiter, get_rate_limiter

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504, 529}

_openai_retryable: tuple[type[Exception], ...] | None = None
_anthropic_retryable: tuple[type[Exception], ...] | None = None
_httpx_retryable: tuple[type[Exception], ...] | None = None


@dataclass(frozen=True, slots=True)
class RetryConfig:
    """Retry policy for transient LLM API failures."""

    enabled: bool = LLM_MAX_RETRIES > 0
    max_retries: int = max(LLM_MAX_RETRIES, 1)
    backoff_base: float = LLM_BACKOFF_BASE
    backoff_cap: float = LLM_BACKOFF_CAP


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    """Rate-limiting policy for LLM calls.

    The global LLMRateLimiter policy is loaded from platform environment
    variables. Per-agent values remain in this compatibility object, but they
    do not reconfigure the shared limiter. ``acquire_timeout`` still controls
    how long this caller waits for a platform slot.

    Attributes:
        max_concurrent: Legacy per-agent compatibility value.
        max_qpm: Legacy per-agent compatibility value.
        pause_seconds: Legacy per-agent compatibility value.
        jitter_range: Legacy per-agent compatibility value.
        acquire_timeout: Max seconds to wait for a slot before raising.
    """

    max_concurrent: int = LLM_MAX_CONCURRENT
    max_qpm: int = LLM_MAX_QPM
    pause_seconds: float = LLM_RATE_LIMIT_PAUSE
    jitter_range: float = LLM_RATE_LIMIT_JITTER
    acquire_timeout: float = LLM_ACQUIRE_TIMEOUT


def _get_openai_retryable() -> tuple[type[Exception], ...]:
    global _openai_retryable
    if _openai_retryable is None:
        try:
            import openai

            _openai_retryable = (
                openai.RateLimitError,
                openai.APITimeoutError,
                openai.APIConnectionError,
            )
        except ImportError:
            _openai_retryable = ()
    return _openai_retryable


def _get_anthropic_retryable() -> tuple[type[Exception], ...]:
    global _anthropic_retryable
    if _anthropic_retryable is None:
        try:
            import anthropic

            _anthropic_retryable = (
                anthropic.RateLimitError,
                anthropic.APITimeoutError,
                anthropic.APIConnectionError,
            )
        except ImportError:
            _anthropic_retryable = ()
    return _anthropic_retryable


def _get_httpx_retryable() -> tuple[type[Exception], ...]:
    global _httpx_retryable
    if _httpx_retryable is None:
        try:
            import httpx

            _httpx_retryable = (
                httpx.RemoteProtocolError,
                httpx.TimeoutException,
            )
        except ImportError:
            _httpx_retryable = ()
    return _httpx_retryable


def _is_retryable(exc: Exception) -> bool:
    """Return *True* if *exc* should trigger a retry."""
    retryable = (
        _get_openai_retryable()
        + _get_anthropic_retryable()
        + _get_httpx_retryable()
    )
    if retryable and isinstance(exc, retryable):
        return True

    status = getattr(exc, "status_code", None)
    if status is not None and status in RETRYABLE_STATUS_CODES:
        return True

    return False


def _is_rate_limit(exc: Exception) -> bool:
    """Return *True* if *exc* is specifically a 429 rate-limit error."""
    return getattr(exc, "status_code", None) == 429


def _is_missing_reasoning_content_error(exc: Exception) -> bool:
    """Return *True* if *exc* is a 400 about missing ``reasoning_content``.

    DeepSeek (and compatible providers) require every assistant message to
    carry ``reasoning_content`` when thinking mode is active.  When the
    conversation history was produced by a non-reasoning model, these
    fields are absent and the API rejects the request with a 400.
    """
    if getattr(exc, "status_code", None) != 400:
        return False
    return "reasoning_content" in str(exc)


def _inject_reasoning_content(
    args: tuple,
    kwargs: dict[str, Any],
) -> bool:
    """Add ``reasoning_content = " "`` to assistant messages that lack it.

    Modifies the formatted message dicts **in-place** so the subsequent
    retry sees the updated values.  Returns *True* when at least one
    message was patched.
    """
    messages: list[dict] | None = kwargs.get("messages")
    if messages is None and args:
        candidate = args[0]
        if isinstance(candidate, list):
            messages = candidate

    if not messages:
        return False

    modified = False
    for msg in messages:
        if (
            isinstance(msg, dict)
            and msg.get("role") == "assistant"
            and "reasoning_content" not in msg
        ):
            msg["reasoning_content"] = " "
            modified = True

    return modified


def _extract_retry_after(exc: Exception) -> float | None:
    """Parse the Retry-After header value (in seconds) from an exception.

    Handles both OpenAI and Anthropic SDK exception shapes, which expose
    headers either directly on the exception or on an attached response object.
    """
    headers = getattr(exc, "headers", None) or getattr(
        getattr(exc, "response", None),
        "headers",
        None,
    )
    if headers:
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
    return None


def _normalize_retry_config(retry_config: RetryConfig | None) -> RetryConfig:
    """Normalize externally supplied retry config into safe bounds."""
    if retry_config is None:
        return RetryConfig()
    normalized_backoff_base = max(0.1, retry_config.backoff_base)
    normalized_backoff_cap = max(
        0.5,
        retry_config.backoff_cap,
        normalized_backoff_base,
    )
    return RetryConfig(
        enabled=retry_config.enabled,
        max_retries=max(1, retry_config.max_retries),
        backoff_base=normalized_backoff_base,
        backoff_cap=normalized_backoff_cap,
    )


def _normalize_rate_limit_config(
    cfg: RateLimitConfig | None,
) -> RateLimitConfig:
    """Normalize externally supplied rate-limit config into safe bounds."""
    if cfg is None:
        return RateLimitConfig()
    return RateLimitConfig(
        max_concurrent=max(1, cfg.max_concurrent),
        max_qpm=max(0, cfg.max_qpm),
        pause_seconds=max(1.0, cfg.pause_seconds),
        jitter_range=max(0.0, cfg.jitter_range),
        acquire_timeout=max(10.0, cfg.acquire_timeout),
    )


def _compute_backoff(attempt: int, retry_config: RetryConfig) -> float:
    """Exponential back-off: base * 2^(attempt-1), capped."""
    return min(
        retry_config.backoff_cap,
        retry_config.backoff_base * (2 ** max(0, attempt - 1)),
    )


class RetryChatModel(ChatModelBase):
    """Transparent retry wrapper around any :class:`ChatModelBase`.

    The wrapper delegates every call to the underlying *inner* model and
    retries on transient errors with exponential back-off.  Streaming
    responses are also covered: if the stream fails mid-consumption the
    entire request is retried from scratch.

    A global LLMRateLimiter is consulted on every call to cap concurrency and
    to coordinate a shared pause across all callers when a 429 is received.
    """

    def __init__(
        self,
        inner: ChatModelBase,
        retry_config: RetryConfig | None = None,
        rate_limit_config: RateLimitConfig | None = None,
    ) -> None:
        super().__init__(model_name=inner.model_name, stream=inner.stream)
        self._inner = inner
        self._retry_config = _normalize_retry_config(retry_config)
        self._rate_limit_config = _normalize_rate_limit_config(
            rate_limit_config,
        )

    # Expose the real model's class so that formatter mapping keeps working
    # when code inspects ``model.__class__`` after wrapping.
    @property
    def inner_class(self) -> type:
        return self._inner.__class__

    @property
    def model_key(self) -> str:
        """Stable key for the underlying model: ``provider_id:model_name``."""
        provider_id = getattr(self._inner, "_provider_id", None)
        name = self._inner.model_name
        return f"{provider_id}:{name}" if provider_id else name

    async def __call__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> ChatResponse | AsyncIterator[ChatResponse]:
        cache = get_capability_cache()
        key = self.model_key

        if cache.get(key, "needs_reasoning_content", False):
            _inject_reasoning_content(args, kwargs)

        # This limiter is shared by all agents in the process. Its policy must
        # come from platform configuration rather than whichever agent makes
        # the first model call after startup.
        limiter = await get_rate_limiter()

        retries = (
            self._retry_config.max_retries if self._retry_config.enabled else 0
        )
        attempts = retries + 1
        last_exc: Exception | None = None

        for attempt in range(1, attempts + 1):
            # Acquire a semaphore slot, with a timeout to prevent
            # indefinite blocking. `acquired` tracks whether the slot was
            # taken so the final block can skip the release on
            # CancelledError (slot was never acquired).
            acquired = False
            owns_semaphore = True
            try:
                try:
                    await asyncio.wait_for(
                        limiter.acquire(),
                        timeout=self._rate_limit_config.acquire_timeout,
                    )
                    acquired = True
                except asyncio.TimeoutError as exc:
                    raise RateLimitExceededException(
                        operation="LLM execution",
                        retry_after=int(
                            self._rate_limit_config.acquire_timeout,
                        ),
                        details={
                            "reason": "Timed out waiting for execution slot",
                        },
                    ) from exc

                try:
                    result = await self._inner(*args, **kwargs)
                except Exception as inner_exc:
                    if not (
                        _is_missing_reasoning_content_error(inner_exc)
                        and _inject_reasoning_content(args, kwargs)
                    ):
                        raise
                    cache.learn(key, "needs_reasoning_content", True)
                    logger.warning(
                        "Thinking-mode model requires reasoning_content "
                        "on every assistant message. Injecting empty "
                        "values and retrying (learned for future calls).",
                    )
                    result = await self._inner(*args, **kwargs)

                if _is_async_iterable(result):
                    owner = await _RetryStreamOwner.create(
                        inner=self._inner,
                        retry_config=self._retry_config,
                        acquire_timeout=(
                            self._rate_limit_config.acquire_timeout
                        ),
                        stream=result,
                        call_args=args,
                        call_kwargs=kwargs,
                        current_attempt=attempt,
                        max_attempts=attempts,
                        limiter=limiter,
                    )
                    # Transfer only after the explicit owner exists. If
                    # __aiter__ or construction raises, this frame still owns
                    # and releases the acquired permit in its finally block.
                    owns_semaphore = False
                    return owner

                return result

            except Exception as exc:
                last_exc = exc
                if _is_retryable(exc) and _is_rate_limit(exc):
                    await limiter.report_rate_limit(_extract_retry_after(exc))

                if not _is_retryable(exc) or attempt >= attempts:
                    raise

                delay = _compute_backoff(attempt, self._retry_config)
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s. "
                    "Retrying in %.1fs ...",
                    attempt,
                    attempts,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

            finally:
                if owns_semaphore and acquired:
                    limiter.release()

        # Should be unreachable, but satisfies the type-checker.
        raise last_exc  # type: ignore[misc]


class _RetryStreamOwner(AsyncGenerator[ChatResponse, None]):
    """Own one retrying stream and its current concurrency permit eagerly."""

    def __init__(
        self,
        *,
        inner: ChatModelBase,
        retry_config: RetryConfig,
        acquire_timeout: float,
        stream: AsyncIterable[ChatResponse],
        iterator: AsyncIterator[ChatResponse],
        call_args: tuple,
        call_kwargs: dict,
        current_attempt: int,
        max_attempts: int,
        limiter: LLMRateLimiter,
    ) -> None:
        self._inner = inner
        self._retry_config = retry_config
        self._acquire_timeout = acquire_timeout
        self._stream: AsyncIterable[ChatResponse] | None = stream
        self._iterator: AsyncIterator[ChatResponse] | None = iterator
        self._call_args = call_args
        self._call_kwargs = call_kwargs
        self._attempt = current_attempt
        self._max_attempts = max_attempts
        self._limiter = limiter
        self._owns_permit = True
        self._stream_active = False
        self._closed = False

    @classmethod
    async def create(
        cls,
        *,
        inner: ChatModelBase,
        retry_config: RetryConfig,
        acquire_timeout: float,
        stream: AsyncIterable[ChatResponse],
        call_args: tuple,
        call_kwargs: dict,
        current_attempt: int,
        max_attempts: int,
        limiter: LLMRateLimiter,
    ) -> "_RetryStreamOwner":
        """Resolve the iterator before the caller transfers its permit."""
        try:
            iterator = _get_async_iterator(stream)
        except BaseException:
            try:
                await _close_async_iterable(stream)
            except BaseException as cleanup_error:
                logger.warning(
                    "LLM stream cleanup failed while resolving its iterator",
                    exc_info=(
                        type(cleanup_error),
                        cleanup_error,
                        cleanup_error.__traceback__,
                    ),
                )
            raise
        return cls(
            inner=inner,
            retry_config=retry_config,
            acquire_timeout=acquire_timeout,
            stream=stream,
            iterator=iterator,
            call_args=call_args,
            call_kwargs=call_kwargs,
            current_attempt=current_attempt,
            max_attempts=max_attempts,
            limiter=limiter,
        )

    def __aiter__(self) -> "_RetryStreamOwner":
        return self

    async def asend(self, value: None) -> ChatResponse:
        """Preserve the standard async-generator protocol for consumers."""
        if value is not None:
            raise TypeError("cannot send a non-None value to this stream")
        return await self.__anext__()

    async def athrow(
        self,
        typ: type[BaseException] | BaseException,
        val: Any = None,
        tb: Any = None,
    ) -> ChatResponse:
        """Close the provider stream before propagating an injected error."""
        if isinstance(typ, BaseException):
            error = typ
        elif val is None:
            error = typ()
        elif isinstance(val, BaseException):
            error = val
        else:
            error = typ(val)
        if tb is not None:
            error = error.with_traceback(tb)
        await self.aclose()
        raise error

    async def __anext__(self) -> ChatResponse:
        if self._closed:
            raise StopAsyncIteration

        failure: BaseException | None = None
        while True:
            if failure is not None:
                if (
                    not isinstance(failure, Exception)
                    or not _is_retryable(failure)
                    or self._attempt >= self._max_attempts
                ):
                    self._closed = True
                    raise failure
                try:
                    await self._prepare_retry(failure)
                    self._attempt += 1
                    await self._acquire_permit()
                    result = await self._inner(
                        *self._call_args,
                        **self._call_kwargs,
                    )
                    if not _is_async_iterable(result):
                        self._closed = True
                        self._release_permit()
                        return result
                    self._install_stream(result)
                    failure = None
                except BaseException as retry_exc:
                    await self._cleanup_current(retry_exc)
                    failure = retry_exc
                continue

            iterator = self._iterator
            if iterator is None:
                self._closed = True
                raise StopAsyncIteration
            try:
                chunk = await iterator.__anext__()
            except StopAsyncIteration:
                self._closed = True
                cleanup_errors = await self._cleanup_current()
                _raise_cleanup_cancellation(cleanup_errors)
                raise
            except BaseException as stream_exc:
                await self._cleanup_current(stream_exc)
                failure = stream_exc
                continue

            # Once the provider starts delivering, move it from the admission
            # permit counter to the active-stream counter without creating a
            # gap in the monitoring snapshot.
            if not self._stream_active:
                self._limiter.mark_stream_started()
                self._stream_active = True
                self._release_permit()
            return chunk

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        cleanup_errors = await self._cleanup_current()
        _raise_cleanup_cancellation(cleanup_errors)

    async def _prepare_retry(self, failure: Exception) -> None:
        if _is_rate_limit(failure):
            await self._limiter.report_rate_limit(
                _extract_retry_after(failure),
            )
        delay = _compute_backoff(
            self._attempt,
            self._retry_config,
        )
        logger.warning(
            "LLM stream failed (attempt %d/%d): %s. Retrying in %.1fs ...",
            self._attempt,
            self._max_attempts,
            failure,
            delay,
        )
        await asyncio.sleep(delay)

    async def _acquire_permit(self) -> None:
        try:
            await asyncio.wait_for(
                self._limiter.acquire(),
                timeout=self._acquire_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise RateLimitExceededException(
                operation="LLM execution (stream retry)",
                retry_after=int(self._acquire_timeout),
                details={
                    "reason": "Timed out waiting for execution slot",
                },
            ) from exc
        self._owns_permit = True

    def _install_stream(self, stream: AsyncIterable[ChatResponse]) -> None:
        self._stream = stream
        self._iterator = _get_async_iterator(stream)

    async def _cleanup_current(
        self,
        primary_error: BaseException | None = None,
    ) -> list[BaseException]:
        iterator = self._iterator
        stream = self._stream
        self._iterator = None
        self._stream = None
        cleanup_errors: list[BaseException] = []
        try:
            candidates: list[Any | None] = [iterator]
            if stream is not iterator:
                candidates.append(stream)
            for candidate in candidates:
                if candidate is None:
                    continue
                try:
                    await _close_async_iterable(candidate)
                except BaseException as cleanup_error:
                    cleanup_errors.append(cleanup_error)
                    logger.warning(
                        "LLM stream cleanup failed; preserving %s",
                        (
                            type(primary_error).__name__
                            if primary_error is not None
                            else "stream outcome"
                        ),
                        exc_info=(
                            type(cleanup_error),
                            cleanup_error,
                            cleanup_error.__traceback__,
                        ),
                    )
        finally:
            self._finish_stream()
            self._release_permit()
        return cleanup_errors

    def _finish_stream(self) -> None:
        if not self._stream_active:
            return
        self._stream_active = False
        self._limiter.mark_stream_finished()

    def _release_permit(self) -> None:
        if not self._owns_permit:
            return
        self._owns_permit = False
        self._limiter.release()


def _is_async_iterable(value: Any) -> bool:
    """Recognize SDK iterator wrappers as well as native async generators."""
    try:
        return isinstance(value, AsyncIterable) or callable(
            getattr(value, "__aiter__", None),
        )
    except (AttributeError, KeyError, TypeError):
        return False


def _get_async_iterator(
    stream: AsyncIterable[ChatResponse],
) -> AsyncIterator[ChatResponse]:
    """Resolve the concrete iterator while the caller still owns cleanup."""
    iterator = stream.__aiter__()
    if not callable(getattr(iterator, "__anext__", None)):
        raise TypeError("async iterable returned an invalid iterator")
    return iterator


def _raise_cleanup_cancellation(errors: list[BaseException]) -> None:
    """Do not swallow cancellation raised by cleanup without a primary."""
    for error in errors:
        if not isinstance(error, Exception):
            raise error


async def _close_async_iterable(stream: Any) -> None:
    """Close native generators and SDK async iterators when supported."""
    try:
        close = getattr(stream, "aclose", None)
    except (AttributeError, KeyError, TypeError):
        return
    if not callable(close):
        return
    result = close()
    if inspect.isawaitable(result):
        await result
