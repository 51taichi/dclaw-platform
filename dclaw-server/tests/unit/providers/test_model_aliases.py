# -*- coding: utf-8 -*-
from types import SimpleNamespace

from qwenpaw.providers.model_aliases import (
    normalize_model_override,
    normalize_model_selection,
    resolve_task_model_override,
)


class _Provider:
    def __init__(self, *models: str, disabled: bool = False) -> None:
        self.disabled = disabled
        self.models = [
            SimpleNamespace(id=model, model_type="llm") for model in models
        ]
        self.extra_models = []

    def has_model(self, model: str) -> bool:
        return any(item.id == model for item in self.models)


class _Manager:
    def __init__(self, providers: dict[str, _Provider]) -> None:
        self.providers = providers

    def get_provider(self, provider_id: str):
        return self.providers.get(provider_id)


def test_legacy_deepseek_flash_is_canonicalized_to_volcengine_ga():
    assert normalize_model_selection(
        "deepseek",
        "deepseek-v4-flash",
    ) == ("volcengine-cn", "deepseek-v4-flash-ga-260731")
    assert normalize_model_override(
        {"provider_id": "deepseek", "model": "deepseek-v4-flash"},
    ) == {
        "provider_id": "volcengine-cn",
        "model": "deepseek-v4-flash-ga-260731",
    }


def test_valid_task_override_is_preserved():
    manager = _Manager({"openai": _Provider("gpt-5")})

    assert resolve_task_model_override(
        manager,
        {"provider_id": "openai", "model": "gpt-5"},
    ) == {"provider_id": "openai", "model": "gpt-5"}


def test_unavailable_or_disabled_task_override_is_cleared():
    manager = _Manager(
        {
            "disabled": _Provider("model-a", disabled=True),
            "active": _Provider("model-b"),
        },
    )

    assert resolve_task_model_override(
        manager,
        {"provider_id": "missing", "model": "model-a"},
    ) is None
    assert resolve_task_model_override(
        manager,
        {"provider_id": "disabled", "model": "model-a"},
    ) is None
    assert resolve_task_model_override(
        manager,
        {"provider_id": "active", "model": "deleted-model"},
    ) is None
