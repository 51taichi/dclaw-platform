"""Authoritative inventory and policy evaluation for AIGC models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, cast

AigcModelCategory = Literal["text", "image", "video", "audio"]
AIGC_MODEL_CATEGORIES: tuple[AigcModelCategory, ...] = (
    "text",
    "image",
    "video",
    "audio",
)


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

    categories: list[AigcModelCategory] = []
    if model_type == "llm":
        categories.append("text")
    if model_type == "image" or capabilities.intersection(
        {"text_to_image", "image_edit", "image_to_image", "mask_edit"}
    ):
        categories.append("image")
    if model_type == "video" or capabilities.intersection(
        {"text_to_video", "image_to_video", "reference_video"}
    ):
        categories.append("video")
    if capabilities.intersection(
        {"text_to_audio", "text_to_music", "generate_audio", "generate_music"}
    ):
        categories.append("audio")
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
