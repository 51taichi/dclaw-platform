# -*- coding: utf-8 -*-
"""Canonical model identifiers and task-override validation."""

from __future__ import annotations

from typing import Any


AUTO_MODEL = ("auto", "routing")

MODEL_ALIASES: dict[tuple[str, str], tuple[str, str]] = {
    ("deepseek", "deepseek-v4-flash"): (
        "volcengine-cn",
        "deepseek-v4-flash-ga-260731",
    ),
}


def normalize_model_selection(
    provider_id: str,
    model: str,
) -> tuple[str, str]:
    """Return the canonical provider/model pair for a persisted selection."""
    key = (str(provider_id or "").strip(), str(model or "").strip())
    return MODEL_ALIASES.get(key, key)


def normalize_model_override(value: object) -> dict[str, str] | None:
    """Normalize a task model override, rejecting malformed values."""
    if not isinstance(value, dict):
        return None
    provider_id, model = normalize_model_selection(
        str(value.get("provider_id") or ""),
        str(value.get("model") or ""),
    )
    if not provider_id or not model:
        return None
    return {"provider_id": provider_id, "model": model}


def is_model_selection_available(
    manager: Any,
    provider_id: str,
    model: str,
) -> bool:
    """Return whether a canonical LLM selection is runnable now."""
    if (provider_id, model) == AUTO_MODEL:
        return True
    provider = manager.get_provider(provider_id)
    if provider is None or bool(getattr(provider, "disabled", False)):
        return False
    if not provider.has_model(model):
        return False
    registered = list(getattr(provider, "models", ()) or ()) + list(
        getattr(provider, "extra_models", ()) or (),
    )
    model_info = next(
        (item for item in registered if getattr(item, "id", None) == model),
        None,
    )
    return getattr(model_info, "model_type", "llm") != "embedding"


def resolve_task_model_override(
    manager: Any,
    value: object,
) -> dict[str, str] | None:
    """Normalize a task override or clear it when it cannot be executed."""
    normalized = normalize_model_override(value)
    if normalized is None:
        return None
    if not is_model_selection_available(
        manager,
        normalized["provider_id"],
        normalized["model"],
    ):
        return None
    return normalized
