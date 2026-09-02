"""Server-local capability marker for isolated Agent OpenAPI requests."""
from __future__ import annotations

from typing import Any

_ISOLATED_AGENT_OPEN_API_CAPABILITY = object()
_CAPABILITY_KEY = "_isolated_agent_open_api_capability"


def bind_isolated_agent_open_api(meta: dict[str, Any]) -> None:
    """Mark trusted in-process metadata created by the Agent OpenAPI route."""
    meta[_CAPABILITY_KEY] = _ISOLATED_AGENT_OPEN_API_CAPABILITY


def is_isolated_agent_open_api(meta: object) -> bool:
    """Return whether metadata carries the exact server-local capability."""
    return bool(
        isinstance(meta, dict)
        and meta.get(_CAPABILITY_KEY) is _ISOLATED_AGENT_OPEN_API_CAPABILITY
    )
