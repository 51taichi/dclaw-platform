# -*- coding: utf-8 -*-
from types import SimpleNamespace

from qwenpaw.agents import model_factory
from qwenpaw.app.agent_context import (
    get_current_chat_model,
    set_current_chat_model,
)
from qwenpaw.config.config import ModelSlotConfig


class _Provider:
    disabled = False
    extra_models = []

    def __init__(self, model_id: str, model_instance: object) -> None:
        self.model_id = model_id
        self.model_instance = model_instance
        self.models = [SimpleNamespace(id=model_id, model_type="llm")]

    def has_model(self, model_id: str) -> bool:
        return model_id == self.model_id

    def get_chat_model_instance(self, model_id: str) -> object:
        assert model_id == self.model_id
        return self.model_instance


class _Manager:
    def __init__(self, providers, global_slot) -> None:
        self.providers = providers
        self.global_slot = global_slot

    def get_provider(self, provider_id: str):
        return self.providers.get(provider_id)

    def get_active_model(self):
        return self.global_slot


def _install_factory_doubles(monkeypatch, manager, global_model):
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_instance",
        staticmethod(lambda: manager),
    )
    monkeypatch.setattr(
        model_factory.ProviderManager,
        "get_active_chat_model",
        staticmethod(lambda: global_model),
    )
    formatter = object()
    monkeypatch.setattr(
        model_factory,
        "_create_formatter_instance",
        lambda _model_class: formatter,
    )
    monkeypatch.setattr(
        model_factory,
        "_wrap_chat_model",
        lambda _provider_id, model, **_kwargs: model,
    )
    return formatter


def test_factory_uses_canonical_model_for_legacy_task_override(monkeypatch):
    ga_model = object()
    provider = _Provider("deepseek-v4-flash-ga-260731", ga_model)
    manager = _Manager(
        {"volcengine-cn": provider},
        ModelSlotConfig(provider_id="global", model="global-model"),
    )
    formatter = _install_factory_doubles(monkeypatch, manager, object())
    previous = get_current_chat_model()
    set_current_chat_model(
        {"provider_id": "deepseek", "model": "deepseek-v4-flash"},
    )
    try:
        model, selected_formatter = model_factory.create_model_and_formatter(
            agent_id="",
        )
    finally:
        set_current_chat_model(previous)

    assert model is ga_model
    assert selected_formatter is formatter


def test_factory_falls_back_when_task_override_is_unavailable(monkeypatch):
    global_model = object()
    global_slot = ModelSlotConfig(
        provider_id="volcengine-cn",
        model="deepseek-v4-flash-ga-260731",
    )
    manager = _Manager({}, global_slot)
    formatter = _install_factory_doubles(
        monkeypatch,
        manager,
        global_model,
    )
    previous = get_current_chat_model()
    set_current_chat_model(
        {"provider_id": "removed-provider", "model": "removed-model"},
    )
    try:
        model, selected_formatter = model_factory.create_model_and_formatter(
            agent_id="",
        )
    finally:
        set_current_chat_model(previous)

    assert model is global_model
    assert selected_formatter is formatter


def test_factory_migrates_legacy_global_model_at_runtime(monkeypatch):
    ga_model = object()
    provider = _Provider("deepseek-v4-flash-ga-260731", ga_model)
    manager = _Manager(
        {"volcengine-cn": provider},
        ModelSlotConfig(
            provider_id="deepseek",
            model="deepseek-v4-flash",
        ),
    )
    formatter = _install_factory_doubles(monkeypatch, manager, object())
    previous = get_current_chat_model()
    set_current_chat_model(None)
    try:
        model, selected_formatter = model_factory.create_model_and_formatter(
            agent_id="",
        )
    finally:
        set_current_chat_model(previous)

    assert model is ga_model
    assert selected_formatter is formatter
