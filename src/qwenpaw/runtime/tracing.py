"""Small tracing decorator used by isolated runtime tests.

Production observability is implemented by DClaw's durable run history and
OpenTelemetry integration; this wrapper only preserves call semantics.
"""

import inspect
from functools import wraps
from typing import Any, Callable


def trace(*_args: Any, **_kwargs: Any) -> Callable:
    def decorate(function: Callable) -> Callable:
        if inspect.isasyncgenfunction(function):

            @wraps(function)
            async def wrapped_generator(*args: Any, **kwargs: Any):
                async for item in function(*args, **kwargs):
                    yield item

            return wrapped_generator

        @wraps(function)
        async def wrapped(*args: Any, **kwargs: Any):
            return await function(*args, **kwargs)

        return wrapped

    return decorate
