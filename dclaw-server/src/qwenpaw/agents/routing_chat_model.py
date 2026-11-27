# -*- coding: utf-8 -*-
"""ChatModel router for local/cloud model selection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Iterable, Literal, Type

from agentscope.formatter import FormatterBase
from agentscope.model import ChatModelBase
from agentscope.model import ChatResponse
from pydantic import BaseModel

from ..config.config import AgentsLLMRoutingConfig
from ..providers.agentscope2_compat import (
    LegacyModelNameMixin,
    initialize_model_wrapper,
)

logger = logging.getLogger(__name__)


Route = Literal["local", "cloud"]


@dataclass
class RoutingDecision:
    route: Route
    reasons: list[str] = field(default_factory=list)


class RoutingPolicy:
    """Select a route using the configured default mode."""

    def __init__(self, cfg: AgentsLLMRoutingConfig):
        self.cfg = cfg

    def decide(
        self,
        *,
        text: str = "",
        channel: str = "",
        tools_available: bool = True,
    ) -> RoutingDecision:
        del text, channel, tools_available

        if getattr(self.cfg, "mode", "local_first") == "cloud_first":
            return RoutingDecision(
                route="cloud",
                reasons=["mode:cloud_first"],
            )

        return RoutingDecision(
            route="local",
            reasons=["mode:local_first"],
        )


@dataclass(frozen=True)
class RoutingEndpoint:
    provider_id: str
    model_name: str
    model: ChatModelBase
    formatter: FormatterBase | None
    formatter_family: Type[FormatterBase]


CODE_ROUTE_KEYWORDS = (
    "api",
    "bug",
    "class",
    "code",
    "docker",
    "error",
    "exception",
    "function",
    "git",
    "javascript",
    "python",
    "react",
    "sql",
    "traceback",
    "typescript",
    "vue",
    "代码",
    "函数",
    "修复",
    "报错",
    "接口",
    "程序",
)

CODE_MODEL_MARKERS = ("code", "coder", "coding", "dev")

MODEL_ENDPOINT_ERROR_TYPE_MARKERS = (
    "api",
    "model",
    "openai",
    "anthropic",
    "completion",
    "chat",
    "generation",
    "inference",
    "llm",
    "permission",
    "connection",
    "timeout",
)

MODEL_ENDPOINT_ERROR_TEXT_MARKERS = (
    "api",
    "model",
    "token",
    "completion",
    "chat",
    "openai",
    "anthropic",
    "rate limit",
    "quota",
    "context length",
    "authentication",
    "unauthorized",
    "forbidden",
    "timeout",
    "timed out",
    "connection",
    "balance",
    "overdue",
)


def _flatten_message_text(messages: Iterable[dict]) -> str:
    parts: list[str] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict):
                    text = block.get("text")
                    if isinstance(text, str):
                        parts.append(text)
    return " ".join(parts)


def _endpoint_label(endpoint: RoutingEndpoint) -> str:
    return f"{endpoint.provider_id}/{endpoint.model_name}"


def _mark_endpoint_error(exc: Exception, endpoint: RoutingEndpoint) -> None:
    try:
        setattr(exc, "model_name", _endpoint_label(endpoint))
    except Exception:
        logger.debug("Failed to annotate Auto routing endpoint error")


def _is_model_endpoint_error(exc: Exception) -> bool:
    if hasattr(exc, "status_code"):
        return True

    type_name = type(exc).__name__.lower()
    if any(marker in type_name for marker in MODEL_ENDPOINT_ERROR_TYPE_MARKERS):
        return True

    message = str(exc).lower()
    return any(marker in message for marker in MODEL_ENDPOINT_ERROR_TEXT_MARKERS)


class AutoRoutingChatModel(LegacyModelNameMixin, ChatModelBase):
    """Route each request to a configured chat model using lightweight hints."""

    def __init__(
        self,
        *,
        endpoints: list[RoutingEndpoint],
        fallback_endpoint: RoutingEndpoint,
    ) -> None:
        initialize_model_wrapper(
            self,
            fallback_endpoint.model,
            model="auto/routing",
        )
        self.endpoints = endpoints
        self.fallback_endpoint = fallback_endpoint

    def _select_endpoint(self, messages: list[dict]) -> RoutingEndpoint:
        text = _flatten_message_text(messages).lower()
        if any(keyword in text for keyword in CODE_ROUTE_KEYWORDS):
            code_endpoint = next(
                (
                    endpoint
                    for endpoint in self.endpoints
                    if any(
                        marker in endpoint.model_name.lower()
                        for marker in CODE_MODEL_MARKERS
                    )
                ),
                None,
            )
            if code_endpoint is not None:
                return code_endpoint
        return self.fallback_endpoint

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        selected_endpoint = self._select_endpoint(messages)
        endpoints = [selected_endpoint] + [
            endpoint
            for endpoint in self.endpoints
            if endpoint is not selected_endpoint
        ]
        last_error: Exception | None = None

        for index, endpoint in enumerate(endpoints):
            logger.debug(
                "Auto LLM routing decision: provider=%s model=%s attempt=%s/%s",
                endpoint.provider_id,
                endpoint.model_name,
                index + 1,
                len(endpoints),
            )
            try:
                return await endpoint.model(
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    structured_model=structured_model,
                    **kwargs,
                )
            except Exception as exc:
                _mark_endpoint_error(exc, endpoint)
                last_error = exc

                if not _is_model_endpoint_error(exc):
                    raise
                if index >= len(endpoints) - 1:
                    raise

                logger.warning(
                    "Auto LLM endpoint failed; trying next endpoint: "
                    "provider=%s model=%s error=%s",
                    endpoint.provider_id,
                    endpoint.model_name,
                    exc,
                )

        if last_error is not None:
            raise last_error
        raise RuntimeError("Auto routing has no endpoints to call.")


class RoutingChatModel(LegacyModelNameMixin, ChatModelBase):
    """A ChatModelBase that routes between local and cloud slots."""

    def __init__(
        self,
        *,
        local_endpoint: RoutingEndpoint,
        cloud_endpoint: RoutingEndpoint,
        routing_cfg: AgentsLLMRoutingConfig,
    ) -> None:
        initialize_model_wrapper(self, local_endpoint.model, model="routing")
        self.local_endpoint = local_endpoint
        self.cloud_endpoint = cloud_endpoint
        self.routing_cfg = routing_cfg
        self.policy = RoutingPolicy(routing_cfg)

    async def __call__(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: Literal["auto", "none", "required"] | str | None = None,
        structured_model: Type[BaseModel] | None = None,
        **kwargs: Any,
    ) -> ChatResponse | AsyncGenerator[ChatResponse, None]:
        text = " ".join(
            message["content"]
            for message in messages
            if message.get("role") == "user"
            and isinstance(message.get("content"), str)
        )
        decision = self.policy.decide(
            text=text,
            tools_available=tools is not None,
        )
        endpoint = (
            self.local_endpoint
            if decision.route == "local"
            else self.cloud_endpoint
        )

        logger.debug(
            "LLM routing decision: route=%s provider=%s model=%s reasons=%s",
            decision.route,
            endpoint.provider_id,
            endpoint.model_name,
            ",".join(decision.reasons),
        )

        return await endpoint.model(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            structured_model=structured_model,
            **kwargs,
        )
