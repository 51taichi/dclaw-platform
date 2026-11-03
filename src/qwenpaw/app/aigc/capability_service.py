"""Shared published-model inventory and workflow capability projection."""

from __future__ import annotations

import logging
import re
from typing import Any

from ...aigc.workflow_contract import workflow_node_registry
from .models import (
    AigcCapabilityInfo,
    AigcCategoryDefaults,
    CapabilityList,
    WorkflowAvailableModel,
    WorkflowNodeCapability,
    WorkflowCapabilityCatalog,
)

logger = logging.getLogger(__name__)

SUPPORTED_AIGC_CAPABILITIES = {
    "text_to_image",
    "image_edit",
    "image_to_image",
    "mask_edit",
    "reference_image",
    "text_to_video",
    "image_to_video",
    "reference_video",
    "storyboard",
}
TEXT_MODEL_CAPABILITY_ALIASES = {
    "storyboard",
}
TEXT_MODEL_CAPABILITY_ALIASES_COMPACT = {
    item.replace("_", "") for item in TEXT_MODEL_CAPABILITY_ALIASES
}
OUTPUT_GENERATION_CAPABILITIES = {
    "text_to_image",
    "image_edit",
    "image_to_image",
    "mask_edit",
    "text_to_video",
    "image_to_video",
}

_MXAPI_SEEDANCE_ENDPOINTS = {"seedance2", "seedance2-fast", "seedance2-mini"}
_MXAPI_GROK_VIDEO_MODELS = {
    "grok-imagine-video-1.5-fast",
    "grok-imagine-video-1.5",
}
_MXAPI_JIMENG_VIDEO_MODELS = {
    "doubao-seedance-1-0-pro-fast-251015",
    "doubao-seedance-1-5-pro-251215",
}


def _aigc_generation_capabilities_from_model_id(model_id: str) -> list[str]:
    model_key = model_id.lower()
    if "seedream" in model_key:
        return ["text_to_image"]
    if "seededit" in model_key:
        return ["image_edit"]
    return []


def _normalized_capability_token(value: Any) -> str:
    return re.sub(
        r"[^0-9a-zA-Z_\u4e00-\u9fff]+",
        "_",
        str(value).strip(),
    ).lower()


def _is_text_model_capability(value: Any) -> bool:
    token = _normalized_capability_token(value)
    compact = token.replace("_", "")
    return (
        token in TEXT_MODEL_CAPABILITY_ALIASES
        or compact in TEXT_MODEL_CAPABILITY_ALIASES_COMPACT
    )


def _normalized_aigc_capabilities(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    capabilities: list[str] = []
    for item in values:
        if item is None:
            continue
        token = _normalized_capability_token(item)
        if not token:
            continue
        if token in SUPPORTED_AIGC_CAPABILITIES:
            capabilities.append(token)
            continue
        if token == "image_to_prompt":
            capabilities.extend(["storyboard", "reference_image"])
            continue
        if token in {"vision", "visual_text", "image_understanding"}:
            capabilities.extend(["storyboard", "reference_image"])
            continue
        if _is_text_model_capability(item):
            capabilities.append("storyboard")
    return list(dict.fromkeys(capabilities))


def _append_reference_capabilities(
    capabilities: list[str],
    model: Any,
) -> list[str]:
    next_capabilities = list(capabilities)
    if getattr(model, "supports_image", False):
        next_capabilities.append("reference_image")
    if getattr(model, "supports_video", False):
        next_capabilities.append("reference_video")
    return list(dict.fromkeys(next_capabilities))


def _has_output_generation_capability(capabilities: list[str]) -> bool:
    return any(item in OUTPUT_GENERATION_CAPABILITIES for item in capabilities)


def _capabilities_from_model(model: Any, provider: Any) -> list[str]:
    direct = _normalized_aigc_capabilities(
        list(getattr(model, "aigc_capabilities", []) or []),
    )
    if direct:
        if _has_output_generation_capability(direct):
            return direct
        return _append_reference_capabilities(direct, model)

    generate_kwargs = getattr(model, "generate_kwargs", {}) or {}
    from_kwargs = _normalized_aigc_capabilities(
        generate_kwargs.get("aigc_capabilities"),
    )
    if from_kwargs:
        if _has_output_generation_capability(from_kwargs):
            return from_kwargs
        return _append_reference_capabilities(from_kwargs, model)

    provider_meta = getattr(provider, "meta", {}) or {}
    provider_caps = provider_meta.get("aigc_capabilities", {})
    if isinstance(provider_caps, dict):
        caps = _normalized_aigc_capabilities(
            provider_caps.get(getattr(model, "id", "")),
        )
        if caps:
            if _has_output_generation_capability(caps):
                return caps
            return _append_reference_capabilities(caps, model)

    generation_caps = _aigc_generation_capabilities_from_model_id(
        str(getattr(model, "id", "") or ""),
    )
    if generation_caps:
        return generation_caps

    return []


def _tool_capabilities(tool_name: str) -> list[str]:
    name = tool_name.lower()
    if name.startswith("generate_image") or "text_to_image" in name:
        return ["text_to_image"]
    if name.startswith("edit_image") or "image_edit" in name:
        return ["image_edit"]
    if name.startswith("text_to_video"):
        return ["text_to_video"]
    if name.startswith("image_to_video"):
        return ["image_to_video"]
    if name.startswith("reference_to_video"):
        return ["reference_video", "text_to_video"]
    return []


def _reference_image_limit_for_model(
    *,
    provider_id: str = "",
    model_id: str = "",
    model_name: str = "",
    capability: str = "",
) -> int | None:
    if capability not in {"text_to_image", "image_to_image", "image_edit", "mask_edit"}:
        return None
    token = re.sub(
        r"[^a-z0-9]+",
        " ",
        f"{provider_id} {model_id} {model_name}".lower(),
    )
    if "gpt image" in token and "2" in token:
        return 16
    if "nano2" in token or "banana2" in token:
        return 16
    if "seedream" in token and "4 5" in token:
        return 10
    return 4


def _parameter_schema_for(
    capability: str,
    *,
    provider_id: str = "",
    model_id: str = "",
    model_name: str = "",
) -> dict[str, Any]:
    common: dict[str, Any] = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "negative_prompt": {"type": "string"},
            "seed": {"type": "integer"},
        },
    }
    if capability == "storyboard":
        common["properties"].update(
            {
                "textMode": {"type": "string"},
                "referenceImages": {"type": "array", "items": {"type": "string"}},
            },
        )
    elif capability.endswith("video"):
        common["properties"].update(
            {
                "duration": {
                    "type": "number",
                    "minimum": 4,
                    "maximum": 15,
                    "default": 5,
                },
                "aspect_ratio": {"type": "string"},
                "fps": {"type": "integer"},
            },
        )
        normalized_model_id = model_id.strip().lower()
        if normalized_model_id in _MXAPI_SEEDANCE_ENDPOINTS:
            is_compact = normalized_model_id in {"seedance2-fast", "seedance2-mini"}
            common["properties"].update(
                {
                    "duration": {
                        "type": "number",
                        "minimum": 4,
                        "maximum": 15,
                        "default": 5,
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "enum": [
                            "Auto",
                            "16:9",
                            "9:16",
                            "1:1",
                            "4:3",
                            "3:4",
                            "21:9",
                        ],
                        "default": "16:9",
                    },
                    "resolution": {
                        "type": "string",
                        "enum": (
                            ["480P", "720P"]
                            if is_compact
                            else ["480P", "720P", "1080P", "4K"]
                        ),
                        "default": "720P",
                    },
                    "generate_audio": {"type": "boolean", "default": False},
                    "return_last_frame": {"type": "boolean", "default": False},
                },
            )
        elif normalized_model_id in _MXAPI_GROK_VIDEO_MODELS:
            is_fast = normalized_model_id.endswith("-fast")
            minimum, maximum, default = (6, 30, 10) if is_fast else (5, 15, 5)
            reference_max = 7 if is_fast else 1
            common["max_reference_images"] = reference_max
            common["properties"].update(
                {
                    "duration": {
                        "type": "number",
                        "minimum": minimum,
                        "maximum": maximum,
                        "default": default,
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "enum": ["2:3", "3:2", "1:1", "9:16", "16:9"],
                        "default": "16:9",
                    },
                    "resolution": {
                        "type": "string",
                        "enum": (
                            ["480P", "720P"] if is_fast else ["480P", "720P", "1080P"]
                        ),
                        "default": "720P",
                    },
                    "referenceImages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 0 if is_fast else 1,
                        "maxItems": reference_max,
                    },
                },
            )
        elif normalized_model_id in _MXAPI_JIMENG_VIDEO_MODELS:
            is_first_last = normalized_model_id == "doubao-seedance-1-5-pro-251215"
            reference_min = 2 if is_first_last else 0
            reference_max = 2 if is_first_last else 1
            common["max_reference_images"] = reference_max
            common["supported_video_modes"] = (
                ["first_last_frames"]
                if is_first_last
                else ["text_to_video", "image_to_video"]
            )
            if is_first_last:
                common["preferred_video_mode"] = "first_last_frames"
            common["properties"].update(
                {
                    "duration": {
                        "type": "number",
                        "minimum": 2,
                        "maximum": 12,
                        "default": 5,
                    },
                    "aspect_ratio": {
                        "type": "string",
                        "enum": ["Auto", "16:9", "9:16", "1:1", "4:3", "3:4"],
                        "default": "16:9",
                    },
                    "resolution": {
                        "type": "string",
                        "enum": ["480P", "720P", "1080P"],
                        "default": "1080P",
                    },
                    "referenceImages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": reference_min,
                        "maxItems": reference_max,
                    },
                },
            )
    else:
        common["properties"].update(
            {
                "size": {"type": "string"},
                "quality": {"type": "string"},
                "n": {"type": "integer"},
            },
        )
        reference_limit = _reference_image_limit_for_model(
            provider_id=provider_id,
            model_id=model_id,
            model_name=model_name,
            capability=capability,
        )
        if reference_limit:
            common["max_reference_images"] = reference_limit
            common["properties"]["referenceImages"] = {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": reference_limit,
            }
    return common


def _provider_configured_for_aigc(provider: Any) -> bool:
    if bool(getattr(provider, "disabled", False)):
        return False
    if getattr(provider, "require_api_key", True) is False:
        return True
    return bool(str(getattr(provider, "api_key", "") or "").strip())


async def build_capability_list(
    manager: Any | None,
    *,
    include_unselected: bool = False,
) -> CapabilityList:
    """Build the AIGC inventory from an already resolved provider manager.

    This keeps the inventory reusable by non-HTTP callers such as sealed
    workspace runtimes without making them impersonate a Starlette request.
    """
    capabilities: list[AigcCapabilityInfo] = []
    published: set[tuple[str, str]] | None = None
    if manager is not None:
        from ..billing.model_publication import ModelPublicationService
        from ..storage.engine import get_app_engine
        from ..storage.repos.price_catalog_repo import PriceCatalogRepository

        published = ModelPublicationService(
            PriceCatalogRepository(get_app_engine())
        ).effective_pairs()
        if published is None:
            return CapabilityList(capabilities=[])
        for provider in await manager.list_provider_info():
            if not _provider_configured_for_aigc(provider):
                continue
            models = list(getattr(provider, "models", []) or []) + list(
                getattr(provider, "extra_models", []) or [],
            )
            for model in models:
                if (provider.id, model.id) not in published:
                    continue
                for capability in _capabilities_from_model(model, provider):
                    capabilities.append(
                        AigcCapabilityInfo(
                            provider_id=provider.id,
                            provider_name=provider.name,
                            model_id=model.id,
                            model_name=model.name,
                            capability=capability,
                            source="model_registry",
                            parameter_schema=_parameter_schema_for(
                                capability,
                                provider_id=provider.id,
                                model_id=model.id,
                                model_name=model.name,
                            ),
                        ),
                    )

    try:
        from ...plugins.registry import PluginRegistry

        registry = PluginRegistry()
        for manifest in registry.get_all_plugin_manifests().values():
            plugin_id = manifest.get("id") or manifest.get("name", "plugin")
            plugin_name = manifest.get("name", plugin_id)
            for tool in (manifest.get("meta") or {}).get("tools", []):
                if not isinstance(tool, dict) or not tool.get("name"):
                    continue
                for capability in _tool_capabilities(str(tool["name"])):
                    capabilities.append(
                        AigcCapabilityInfo(
                            provider_id=f"plugin:{plugin_id}",
                            provider_name=plugin_name,
                            model_id=str(tool["name"]),
                            model_name=tool.get("description") or str(tool["name"]),
                            capability=capability,
                            source="plugin_tool",
                            parameter_schema=_parameter_schema_for(
                                capability,
                                model_id=str(tool["name"]),
                                model_name=str(tool.get("description") or ""),
                            ),
                        ),
                    )
    except Exception:
        pass

    deduped = {
        (c.provider_id, c.model_id, c.capability, c.source): c for c in capabilities
    }
    result = CapabilityList(capabilities=list(deduped.values()))
    if manager is None or published is None:
        return result

    from ..aigc.model_policy import (
        AIGC_MODEL_CATEGORIES,
        AigcModelPolicyService,
        filter_capabilities,
        policy_enforcement_enabled,
    )
    from ..storage.repos.aigc_model_policy_repo import (
        AigcModelPolicyRepository,
    )

    if not policy_enforcement_enabled():
        return result

    policy_service = AigcModelPolicyService(
        AigcModelPolicyRepository(get_app_engine()),
        published_pairs=published,
        priced_pairs=published,
    )
    try:
        effective = {
            category: await policy_service.effective(
                category,
                manager,
                include_unselected=include_unselected,
            )
            for category in AIGC_MODEL_CATEGORIES
        }
    except Exception as exc:
        from sqlalchemy.exc import OperationalError, ProgrammingError

        if not isinstance(exc, (OperationalError, ProgrammingError)):
            raise
        logger.warning(
            "AIGC model-policy tables are unavailable; preserving legacy inventory",
        )
        return result
    # An explicit text policy also selects ordinary LLMs without an AIGC
    # storyboard tag. Project only its effective (published/priced/available)
    # entries so the inventory and job validation agree with the admin policy.
    text_policy = effective["text"]
    if text_policy.configured:
        existing_text_models = {
            (item.provider_id, item.model_id)
            for item in result.capabilities
            if item.capability == "storyboard" and item.source == "model_registry"
        }
        for item in text_policy.models:
            if (item.provider_id, item.model_id) in existing_text_models:
                continue
            result.capabilities.append(
                AigcCapabilityInfo(
                    provider_id=item.provider_id,
                    provider_name=item.provider_name,
                    model_id=item.model_id,
                    model_name=item.model_name,
                    capability="storyboard",
                    source="model_registry",
                    parameter_schema=_parameter_schema_for("storyboard"),
                ),
            )
            existing_text_models.add((item.provider_id, item.model_id))

    allowed = {
        category: {
            (item.provider_id, item.model_id) for item in policy.models
        }
        for category, policy in effective.items()
        if policy.configured
    }
    defaults = {
        category: AigcCategoryDefaults(
            configured=policy.configured,
            configured_default=(
                {
                    "provider_id": policy.configured_default.provider_id,
                    "model_id": policy.configured_default.model_id,
                }
                if policy.configured_default
                else None
            ),
            effective_default=(
                {
                    "provider_id": policy.effective_default.provider_id,
                    "model_id": policy.effective_default.model_id,
                }
                if policy.effective_default
                else None
            ),
            fallback_active=policy.fallback_active,
            fallback_reason=list(policy.fallback_reason),
        )
        for category, policy in effective.items()
    }
    return CapabilityList(
        capabilities=filter_capabilities(result.capabilities, allowed),
        defaults=defaults,
    )


def project_workflow_capability_catalog(
    inventory: CapabilityList,
) -> WorkflowCapabilityCatalog:
    """Project the live priced model inventory onto the closed node registry."""
    registry = workflow_node_registry()
    models = tuple(
        WorkflowAvailableModel(**item.model_dump(mode="python"))
        for item in sorted(
            inventory.capabilities,
            key=lambda value: (
                value.provider_id,
                value.model_id,
                value.capability,
                value.source,
            ),
        )
    )
    nodes = tuple(
        WorkflowNodeCapability(
            kind=registration.kind,
            title=registration.title,
            provisioning=registration.provisioning,
            provisioning_reason=registration.provisioning_reason,
            capabilities=registration.capabilities,
            input_keys=tuple(sorted(registration.input_keys)),
            parameter_keys=tuple(sorted(registration.parameter_keys)),
            input_slots={
                key: tuple(values)
                for key, values in sorted(registration.input_slots.items())
            },
            output_type=registration.output_type,
            control_id=registration.control_id,
            customer_actions=registration.customer_actions,
            input_schema=registration.input_schema,
            parameter_schema=registration.parameter_schema,
        )
        for registration in registry.values()
    )
    return WorkflowCapabilityCatalog(nodes=nodes, available_models=models)


async def build_workflow_capability_catalog(
    manager: Any | None,
) -> WorkflowCapabilityCatalog:
    """Return workflow nodes plus models enabled by the admin policy."""
    return project_workflow_capability_catalog(
        await build_capability_list(manager)
    )
