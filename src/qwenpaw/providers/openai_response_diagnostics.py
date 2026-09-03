# -*- coding: utf-8 -*-
"""Private, content-free diagnostics for OpenAI-compatible responses."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import Lock
from typing import Any
from weakref import ref


@dataclass(frozen=True)
class OpenAIResponseDiagnostics:
    """Safe supplier facts; response text and credentials are never stored."""

    finish_reason: str | None = None
    content_length: int = 0
    reasoning_length: int = 0
    usage: dict[str, int] = field(default_factory=dict)


_diagnostics: dict[
    int,
    tuple[ref[Any], OpenAIResponseDiagnostics],
] = {}
_diagnostics_lock = Lock()
_capture_enabled: ContextVar[bool] = ContextVar(
    "openai_response_diagnostics_capture_enabled",
    default=False,
)


@contextmanager
def capture_openai_response_diagnostics() -> Iterator[None]:
    """Enable capture only within an OpenAPI adapter-owned model call."""
    token = _capture_enabled.set(True)
    try:
        yield
    finally:
        _capture_enabled.reset(token)


def is_openai_response_diagnostics_capture_enabled() -> bool:
    return _capture_enabled.get()


def stash_openai_response_diagnostics(
    response: Any,
    diagnostics: OpenAIResponseDiagnostics,
) -> None:
    """Associate safe diagnostics without serializing them to the caller."""
    identity = id(response)

    def cleanup(dead_reference: ref[Any]) -> None:
        with _diagnostics_lock:
            current = _diagnostics.get(identity)
            if current is not None and current[0] is dead_reference:
                _diagnostics.pop(identity, None)

    try:
        response_ref = ref(response, cleanup)
    except TypeError:
        return
    with _diagnostics_lock:
        _diagnostics[identity] = (response_ref, diagnostics)


def pop_openai_response_diagnostics(
    response: Any,
) -> OpenAIResponseDiagnostics:
    """Consume diagnostics once, verifying identity before returning them."""
    with _diagnostics_lock:
        stored = _diagnostics.pop(id(response), None)
    if stored is None or stored[0]() is not response:
        return OpenAIResponseDiagnostics()
    return stored[1]


__all__ = [
    "OpenAIResponseDiagnostics",
    "capture_openai_response_diagnostics",
    "is_openai_response_diagnostics_capture_enabled",
    "pop_openai_response_diagnostics",
    "stash_openai_response_diagnostics",
]
