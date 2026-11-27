"""Build a network-free pricing inventory from configured providers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...providers.provider import ModelInfo


@dataclass(frozen=True)
class PriceableModel:
    provider_id: str
    provider_name: str
    model_key: str
    model_name: str
    category: str
    official_model_id: str | None = None
    capabilities: tuple[str, ...] = ()
    pricing_region: str | None = None


def pricing_region_for_endpoint(base_url: str) -> str | None:
    hostname = base_url.lower()
    if "dashscope-intl.aliyuncs.com" in hostname:
        return "ap-southeast-1"
    if "dashscope-us.aliyuncs.com" in hostname:
        return "us-east-1"
    if "dashscope.aliyuncs.com" in hostname:
        return "cn-beijing"
    if "ark.cn-beijing.volces.com" in hostname:
        return "cn-beijing"
    return None


def classify_model(model: ModelInfo) -> str:
    if model.model_type == "image":
        return "image"
    if model.model_type == "video":
        return "video"
    if model.model_type == "embedding":
        return "embedding_rerank"
    capabilities = {value.lower() for value in model.aigc_capabilities}
    if any("audio" in value or "speech" in value for value in capabilities):
        return "audio"
    if capabilities and not any(
        value.startswith(("text_", "image_", "video_"))
        for value in capabilities
    ):
        return "other"
    return "text"


class PricingModelInventory:
    def __init__(self, manager: Any) -> None:
        self.manager = manager

    def list_enabled(self) -> tuple[PriceableModel, ...]:
        rows: list[PriceableModel] = []
        providers = [
            (provider, True)
            for provider in self.manager.builtin_providers.values()
        ]
        providers.extend(
            (provider, False)
            for provider in self.manager.custom_providers.values()
        )
        providers.extend(
            (entry["info"], False)
            for entry in self.manager.plugin_providers.values()
        )
        for provider, has_official_identity in providers:
            if getattr(provider, "disabled", False):
                continue
            if (
                provider.require_api_key
                and not provider.api_key
                and not provider.is_local
            ):
                continue
            base_url = str(getattr(provider, "base_url", "") or "").strip()
            if not provider.is_local and not base_url:
                continue
            hidden = set(provider.meta.get("hidden_builtin_model_ids", []))
            for model in (*provider.models, *provider.extra_models):
                if model.id in hidden:
                    continue
                rows.append(
                    PriceableModel(
                        provider_id=provider.id,
                        provider_name=provider.name,
                        model_key=model.id,
                        model_name=model.name,
                        category=classify_model(model),
                        official_model_id=(
                            model.id if has_official_identity else None
                        ),
                        capabilities=tuple(sorted(model.aigc_capabilities)),
                        pricing_region=pricing_region_for_endpoint(base_url),
                    )
                )
        return tuple(
            sorted(
                rows,
                key=lambda row: (row.provider_id, row.category, row.model_key),
            )
        )
