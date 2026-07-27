# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from qwenpaw.agents.routing_chat_model import (
    AutoRoutingChatModel,
    RoutingEndpoint,
)
from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.agents import model_factory
from qwenpaw.providers.provider import ModelInfo


class FakeModel:
    def __init__(self, name: str, error: Exception | None = None) -> None:
        self.model_name = name
        self.stream = True
        self.calls: list[list[dict]] = []
        self.error = error

    async def __call__(self, messages, **_kwargs):
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return {"model": self.model_name}


def _endpoint(model_name: str) -> RoutingEndpoint:
    return RoutingEndpoint(
        provider_id="test-provider",
        model_name=model_name,
        model=FakeModel(model_name),
        formatter=None,
        formatter_family=object,
    )


class FakeModelError(Exception):
    status_code = 403


async def test_auto_routing_prefers_code_model_for_code_prompts() -> None:
    general = _endpoint("glm-4.7")
    coder = _endpoint("qwen3-coder-plus")
    router = AutoRoutingChatModel(
        endpoints=[general, coder],
        fallback_endpoint=general,
    )

    response = await router(
        messages=[
            {
                "role": "user",
                "content": "请帮我写一个 TypeScript 函数并修复 bug",
            },
        ],
    )

    assert response == {"model": "qwen3-coder-plus"}
    assert coder.model.calls
    assert not general.model.calls


async def test_auto_routing_falls_back_when_selected_endpoint_is_unauthorized() -> None:
    overdue = RoutingEndpoint(
        provider_id="dashscope",
        model_name="glm-5",
        model=FakeModel("glm-5", FakeModelError("AccountOverdueError")),
        formatter=None,
        formatter_family=object,
    )
    backup = _endpoint("big-pickle")
    router = AutoRoutingChatModel(
        endpoints=[overdue, backup],
        fallback_endpoint=overdue,
    )

    response = await router(
        messages=[
            {
                "role": "user",
                "content": "你好",
            },
        ],
    )

    assert response == {"model": "big-pickle"}
    assert overdue.model.calls
    assert backup.model.calls


async def test_auto_routing_tags_final_error_with_real_endpoint() -> None:
    overdue = RoutingEndpoint(
        provider_id="dashscope",
        model_name="glm-5",
        model=FakeModel("glm-5", FakeModelError("AccountOverdueError")),
        formatter=None,
        formatter_family=object,
    )
    router = AutoRoutingChatModel(
        endpoints=[overdue],
        fallback_endpoint=overdue,
    )

    with pytest.raises(FakeModelError) as exc_info:
        await router(
            messages=[
                {
                    "role": "user",
                    "content": "你好",
                },
            ],
        )

    assert getattr(exc_info.value, "model_name", None) == "dashscope/glm-5"


def test_auto_model_slot_is_explicitly_detected() -> None:
    assert model_factory.is_auto_model_slot(
        ModelSlotConfig(provider_id="auto", model="routing"),
    )
    assert not model_factory.is_auto_model_slot(
        ModelSlotConfig(provider_id="volcengine-cn", model="glm-4.7"),
    )


class FakeProvider:
    id = "volcengine-cn"
    api_key = "sk-test"
    base_url = "https://example.test/v1"
    is_local = False
    is_custom = False
    require_api_key = True
    models = [
        ModelInfo(id="glm-4.7", name="GLM-4.7"),
        ModelInfo(id="qwen3-coder-plus", name="Qwen3 Coder Plus"),
    ]
    extra_models = [
        ModelInfo(
            id="doubao-seedream",
            name="Doubao Seedream",
            aigc_capabilities=["text_to_image"],
        ),
    ]

    def get_chat_model_instance(self, model_id: str) -> FakeModel:
        return FakeModel(model_id)


class DisabledFakeProvider(FakeProvider):
    id = "disabled-provider"
    disabled = True
    api_key = "sk-disabled"
    models = [
        ModelInfo(id="disabled-chat", name="Disabled Chat"),
    ]


class FakeManager:
    builtin_providers = {
        "volcengine-cn": FakeProvider(),
        "disabled-provider": DisabledFakeProvider(),
    }
    custom_providers = {}
    plugin_providers = {}

    def get_active_model(self):
        return ModelSlotConfig(provider_id="volcengine-cn", model="glm-4.7")


def test_auto_routing_factory_uses_configured_chat_models_only() -> None:
    model, formatter = model_factory._build_auto_routing_model_and_formatter(
        FakeManager(),
        retry_config=None,
        rate_limit_config=None,
    )

    assert isinstance(model, AutoRoutingChatModel)
    assert formatter is not None
    assert [endpoint.model_name for endpoint in model.endpoints] == [
        "glm-4.7",
        "qwen3-coder-plus",
    ]


def test_auto_routing_factory_skips_disabled_providers() -> None:
    model, _formatter = model_factory._build_auto_routing_model_and_formatter(
        FakeManager(),
        retry_config=None,
        rate_limit_config=None,
    )

    assert all(
        endpoint.provider_id != "disabled-provider"
        for endpoint in model.endpoints
    )
