"""Narrow compatibility shims for ReMeLight on AgentScope 2."""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

from ..utils.estimate_token_counter import EstimatedTokenCounter


class ReMeTokenCounter(EstimatedTokenCounter):
    """Provide the AgentScope 1 token-counter name used by ReMeLight."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        super().__init__()


def install_reme_agentscope2_compat() -> None:
    """Install aliases removed by AgentScope 2 and MCP 2."""
    import agentscope
    import mcp.client.streamable_http as streamable_http

    if not hasattr(streamable_http, "streamablehttp_client"):
        streamable_http.streamablehttp_client = (
            streamable_http.streamable_http_client
        )

    token_module = sys.modules.get("agentscope.token")
    if token_module is None:
        token_module = ModuleType("agentscope.token")
        sys.modules["agentscope.token"] = token_module
        agentscope.token = token_module
    if not hasattr(token_module, "HuggingFaceTokenCounter"):
        token_module.HuggingFaceTokenCounter = ReMeTokenCounter

