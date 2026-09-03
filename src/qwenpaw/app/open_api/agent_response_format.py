# -*- coding: utf-8 -*-
"""Request-scoped response-format policy for direct Agent OpenAPI calls."""

from __future__ import annotations

from typing import Any


def is_trusted_direct_agent_open_api(
    channel: str,
    channel_meta: Any,
) -> bool:
    """Return whether server-owned metadata identifies a direct Agent call."""
    if not str(channel or "").startswith("open:"):
        return False
    if not isinstance(channel_meta, dict):
        return False
    return bool(
        channel_meta.get("target_type") == "agent"
        and str(channel_meta.get("publication_id") or "").strip()
        and str(channel_meta.get("open_invocation_id") or "").strip()
    )


def install_open_api_agent_response_format(agent: Any) -> bool:
    """Install the response-format adapter when the model is eligible.

    The phase adapter is implemented in the next plan task. Keeping this
    function as the single activation point makes the policy easy to test and
    roll back without changing unrelated Runner behavior.
    """
    _ = agent
    return False
