"""Authoritative inventory and policy evaluation for AIGC models."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast

AigcModelCategory = Literal["text", "image", "video"]
AIGC_MODEL_CATEGORIES: tuple[AigcModelCategory, ...] = (
    "text",
    "image",
    "video",
)


def policy_enforcement_enabled(
    environ: Mapping[str, str] | None = None,
) -> bool:
    value = (environ or os.environ).get("AIGC_MODEL_POLICY_ENFORCEMENT", "")
    return value.strip().lower() not in {"0", "false", "off"}


def category_for_capability(capability: str) -> AigcModelCategory | None:
    normalized = str(capability).strip().lower()
    if normalized == "storyboard":
        return "text"
    if "audio" in normalized or "music" in normalized:
        return None
    if "video" in normalized:
        return "video"
    return "image"


def filter_capabilities(
    capabilities: list[Any],
    allowed_by_category: dict[AigcModelCategory, set[tuple[str, str]]],
) -> list[Any]:
    """Filter registry models while preserving non-model plugin capabilities."""
    filtered: list[Any] = []
    for item in capabilities:
        if getattr(item, "source", "model_registry") != "model_registry":
            filtered.append(item)
            continue
        category = category_for_capability(str(getattr(item, "capability", "")))
        if category is None:
            continue
        allowed = allowed_by_category.get(category)
        if (
            allowed is None
            or (
                str(getattr(item, "provider_id", "")),
                str(getattr(item, "model_id", "")),
            )
            in allowed
        ):
            filtered.append(item)
    return filtered


@dataclass(frozen=True)
class ModelRef:
    provider_id: str
    model_id: str


@dataclass(frozen=True)
class InventoryItem:
    provider_id: str
    provider_name: str
    model_id: str
    model_name: str
    category: AigcModelCategory | None
    selectable: bool
    reasons: tuple[str, ...] = ()
    selected: bool = False
    is_default: bool = False

    @property
    def ref(self) -> ModelRef:
        return ModelRef(self.provider_id, self.model_id)


@dataclass
class AigcPolicyInventory:
    categories: dict[AigcModelCategory, list[InventoryItem]] = field(
        default_factory=lambda: {category: [] for category in AIGC_MODEL_CATEGORIES}
    )
    uncategorized: list[InventoryItem] = field(default_factory=list)

    def find(
        self,
        category: AigcModelCategory,
        provider_id: str,
        model_id: str,
    ) -> InventoryItem:
        for item in self.categories[category]:
            if item.provider_id == provider_id and item.model_id == model_id:
                return item
        raise LookupError(f"unknown AIGC model: {category}/{provider_id}/{model_id}")


@dataclass(frozen=True)
class EffectiveCategoryPolicy:
    category: AigcModelCategory
    configured: bool
    models: tuple[InventoryItem, ...]
    configured_default: ModelRef | None
    effective_default: ModelRef | None
    fallback_active: bool
    fallback_reason: tuple[str, ...] = ()


def _model_categories(model: Any) -> tuple[AigcModelCategory, ...]:
    model_type = str(getattr(model, "model_type", "llm") or "llm")
    capabilities = {
        str(value).strip().lower()
        for value in (getattr(model, "aigc_capabilities", ()) or ())
    }
    generate_kwargs = getattr(model, "generate_kwargs", {}) or {}
    capabilities.update(
        str(value).strip().lower()
        for value in (generate_kwargs.get("aigc_capabilities", ()) or ())
    )
    removed_audio_generation = capabilities.intersection(
        {"text_to_audio", "text_to_music", "generate_audio", "generate_music"}
    )

    categories: list[AigcModelCategory] = []
    if model_type == "llm" and (
        not removed_audio_generation or "storyboard" in capabilities
    ):
        categories.append("text")
    if model_type == "image" or capabilities.intersection(
        {"text_to_image", "image_edit", "image_to_image", "mask_edit"}
    ):
        categories.append("image")
    if model_type == "video" or capabilities.intersection(
        {"text_to_video", "image_to_video", "reference_video"}
    ):
        categories.append("video")
    return tuple(dict.fromkeys(categories))


def _provider_configured(provider: Any) -> bool:
    if getattr(provider, "require_api_key", True) is False:
        return True
    return bool(str(getattr(provider, "api_key", "") or "").strip())


class AigcModelPolicyService:
    """Join persisted policy references with current model availability."""

    def __init__(
        self,
        policies: Any,
        *,
        published_pairs: set[tuple[str, str]],
        priced_pairs: set[tuple[str, str]],
    ) -> None:
        self.policies = policies
        self.published_pairs = published_pairs
        self.priced_pairs = priced_pairs

    async def inventory(self, manager: Any) -> AigcPolicyInventory:
        inventory = AigcPolicyInventory()
        saved = {
            category: self.policies.get(category) for category in AIGC_MODEL_CATEGORIES
        }
        selected = {
            category: {
                (str(item["provider_id"]), str(item["model_id"]))
                for item in (policy or {}).get("models", ())
            }
            for category, policy in saved.items()
        }
        defaults = {
            category: next(
                (
                    (str(item["provider_id"]), str(item["model_id"]))
                    for item in (policy or {}).get("models", ())
                    if item.get("is_default")
                ),
                None,
            )
            for category, policy in saved.items()
        }

        for provider in await manager.list_provider_info():
            provider_id = str(provider.id)
            provider_name = str(provider.name)
            disabled = bool(getattr(provider, "disabled", False))
            configured = _provider_configured(provider)
            models = list(getattr(provider, "models", ()) or ()) + list(
                getattr(provider, "extra_models", ()) or ()
            )
            for model in models:
                model_id = str(model.id)
                pair = (provider_id, model_id)
                reasons: list[str] = []
                if disabled:
                    reasons.append("provider_disabled")
                elif not configured:
                    reasons.append("provider_unconfigured")
                if pair not in self.published_pairs:
                    reasons.append("unpublished")
                if pair not in self.priced_pairs:
                    reasons.append("unpriced")
                categories = _model_categories(model)
                if not categories:
                    reasons.append("adapter_unsupported")
                    inventory.uncategorized.append(
                        InventoryItem(
                            provider_id=provider_id,
                            provider_name=provider_name,
                            model_id=model_id,
                            model_name=str(model.name),
                            category=None,
                            selectable=False,
                            reasons=tuple(reasons),
                        )
                    )
                    continue
                for category in categories:
                    inventory.categories[category].append(
                        InventoryItem(
                            provider_id=provider_id,
                            provider_name=provider_name,
                            model_id=model_id,
                            model_name=str(model.name),
                            category=cast(AigcModelCategory, category),
                            selectable=not reasons,
                            reasons=tuple(reasons),
                            selected=pair in selected[category],
                            is_default=pair == defaults[category],
                        )
                    )

        for category in AIGC_MODEL_CATEGORIES:
            inventory.categories[category].sort(
                key=lambda item: (
                    not item.is_default,
                    not item.selected,
                    item.provider_name.casefold(),
                    item.model_name.casefold(),
                    item.provider_id,
                    item.model_id,
                )
            )
        return inventory

    async def effective(
        self,
        category: AigcModelCategory,
        manager: Any,
    ) -> EffectiveCategoryPolicy:
        inventory = await self.inventory(manager)
        policy = self.policies.get(category)
        candidates = inventory.categories[category]
        by_key = {(item.provider_id, item.model_id): item for item in candidates}

        if not policy or not policy.get("configured", True):
            available = tuple(item for item in candidates if item.selectable)
            default = available[0].ref if available else None
            return EffectiveCategoryPolicy(
                category=category,
                configured=False,
                models=available,
                configured_default=None,
                effective_default=default,
                fallback_active=False,
            )

        ordered_refs = [
            ModelRef(str(item["provider_id"]), str(item["model_id"]))
            for item in sorted(
                policy.get("models", ()),
                key=lambda item: int(item.get("sort_order", 0)),
            )
        ]
        configured_default = next(
            (
                ModelRef(str(item["provider_id"]), str(item["model_id"]))
                for item in policy.get("models", ())
                if item.get("is_default")
            ),
            None,
        )
        selected_available = tuple(
            by_key[(ref.provider_id, ref.model_id)]
            for ref in ordered_refs
            if (ref.provider_id, ref.model_id) in by_key
            and by_key[(ref.provider_id, ref.model_id)].selectable
        )
        selected_keys = {
            (item.provider_id, item.model_id) for item in selected_available
        }
        available = selected_available + tuple(
            item
            for item in candidates
            if item.selectable
            and (item.provider_id, item.model_id) not in selected_keys
        )
        configured_item = (
            by_key.get((configured_default.provider_id, configured_default.model_id))
            if configured_default
            else None
        )
        configured_valid = bool(configured_item and configured_item.selectable)
        effective_default = (
            configured_default
            if configured_valid
            else (available[0].ref if available else None)
        )
        return EffectiveCategoryPolicy(
            category=category,
            configured=True,
            models=available,
            configured_default=configured_default,
            effective_default=effective_default,
            fallback_active=(
                configured_default is not None
                and effective_default != configured_default
            ),
            fallback_reason=(
                configured_item.reasons
                if configured_item and not configured_item.selectable
                else (
                    ("missing",) if configured_default and not configured_item else ()
                )
            ),
        )
