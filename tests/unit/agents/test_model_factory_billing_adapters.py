# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Formatter-family selection for Task4 provider subclasses."""
from __future__ import annotations

import pytest

from qwenpaw.agents import model_factory
from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.providers.provider import ModelInfo
from qwenpaw.providers.billing_chat_model_adapters import (
    BillingAnthropicChatModel,
    BillingGeminiChatModel,
)


@pytest.mark.parametrize(
    ("chat_model_class", "expected_formatter"),
    [
        (BillingAnthropicChatModel, model_factory.AnthropicChatFormatter),
        (BillingGeminiChatModel, model_factory.GeminiChatFormatter),
    ],
)
def test_billing_adapter_subclass_keeps_its_native_formatter_family(
    chat_model_class,
    expected_formatter,
):
    """The same MRO lookup is used by normal and auto-routing factories."""
    assert (
        model_factory._get_formatter_for_chat_model(
            chat_model_class,
        )
        is expected_formatter
    )
    assert isinstance(
        model_factory._create_formatter_instance(chat_model_class),
        expected_formatter,
    )


@pytest.mark.parametrize(
    ("chat_model_class", "expected_formatter"),
    [
        (BillingAnthropicChatModel, model_factory.AnthropicChatFormatter),
        (BillingGeminiChatModel, model_factory.GeminiChatFormatter),
    ],
)
def test_auto_routing_uses_native_formatter_for_billing_adapter_subclass(
    chat_model_class,
    expected_formatter,
):
    class Provider:
        id = "provider"
        api_key = "configured"
        disabled = False
        models = [ModelInfo(id="model", name="model")]
        extra_models = []

        def get_chat_model_instance(self, model_id):
            instance = object.__new__(chat_model_class)
            instance.model_name = model_id
            instance.stream = True
            return instance

    class Manager:
        builtin_providers = {"provider": Provider()}
        custom_providers = {}
        plugin_providers = {}

        def get_active_model(self):
            return ModelSlotConfig(provider_id="provider", model="model")

    _model, formatter = model_factory._build_auto_routing_model_and_formatter(
        Manager(),
        retry_config=None,
        rate_limit_config=None,
    )

    assert isinstance(formatter, expected_formatter)


def test_auto_routing_threads_request_scoped_meter_to_each_endpoint():
    class Provider:
        id = "provider"
        api_key = "configured"
        disabled = False
        models = [ModelInfo(id="model", name="model")]
        extra_models = []

        def get_chat_model_instance(self, model_id):
            instance = object.__new__(BillingGeminiChatModel)
            instance.model_name = model_id
            instance.stream = True
            return instance

    class Manager:
        builtin_providers = {"provider": Provider()}
        custom_providers = {}
        plugin_providers = {}

        def get_active_model(self):
            return ModelSlotConfig(provider_id="provider", model="model")

    meter = object()
    routed, _formatter = model_factory._build_auto_routing_model_and_formatter(
        Manager(),
        retry_config=None,
        rate_limit_config=None,
        billing_meter=meter,
    )

    assert routed.endpoints[0].model._inner._meter is meter
