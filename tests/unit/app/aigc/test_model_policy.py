from types import SimpleNamespace

import pytest

from qwenpaw.app.aigc.model_policy import (
    AigcModelPolicyService,
    filter_capabilities,
    policy_enforcement_enabled,
)


class StubPolicies:
    def __init__(self, saved=None):
        self.saved = saved or {}

    def get(self, category):
        return self.saved.get(category)


class StubManager:
    def __init__(self, providers):
        self.providers = providers

    async def list_provider_info(self):
        return self.providers


def model(model_id, *, model_type="llm", capabilities=(), priced=True):
    return SimpleNamespace(
        id=model_id,
        name=model_id.replace("-", " ").title(),
        model_type=model_type,
        aigc_capabilities=list(capabilities),
        generate_kwargs={},
        supports_image=False,
        supports_video=False,
        billing_eligible=priced,
    )


def provider(provider_id, models, *, configured=True, disabled=False):
    return SimpleNamespace(
        id=provider_id,
        name=provider_id.title(),
        models=models,
        extra_models=[],
        require_api_key=True,
        api_key="secret" if configured else "",
        disabled=disabled,
        meta={},
    )


@pytest.mark.asyncio
async def test_inventory_shows_unpriced_and_unpublished_models_disabled():
    manager = StubManager(
        [
            provider(
                "mxapi",
                [model("gpt-image-2", model_type="image", priced=False)],
            ),
            provider("dashscope", [model("qwen-max")]),
        ]
    )
    service = AigcModelPolicyService(
        StubPolicies(),
        published_pairs={("mxapi", "gpt-image-2")},
        priced_pairs={("dashscope", "qwen-max")},
    )

    inventory = await service.inventory(manager)
    unpriced = inventory.find("image", "mxapi", "gpt-image-2")
    unpublished = inventory.find("text", "dashscope", "qwen-max")

    assert unpriced.selectable is False
    assert unpriced.reasons == ("unpriced",)
    assert unpublished.selectable is False
    assert unpublished.reasons == ("unpublished",)


@pytest.mark.asyncio
async def test_text_inventory_includes_ordinary_llms_without_storyboard_flag():
    manager = StubManager([provider("volcengine", [model("deepseek-v4")])])
    pairs = {("volcengine", "deepseek-v4")}
    service = AigcModelPolicyService(
        StubPolicies(), published_pairs=pairs, priced_pairs=pairs
    )

    item = (await service.inventory(manager)).find("text", "volcengine", "deepseek-v4")

    assert item.category == "text"
    assert item.selectable is True


@pytest.mark.asyncio
async def test_inventory_classifies_video_audio_and_multi_capability_image():
    models = [
        model("visual", capabilities=("text_to_image", "image_edit")),
        model("movie", model_type="video", capabilities=("text_to_video",)),
        model("voice", capabilities=("text_to_audio",)),
    ]
    manager = StubManager([provider("mxapi", models)])
    pairs = {("mxapi", item.id) for item in models}
    inventory = await AigcModelPolicyService(
        StubPolicies(), published_pairs=pairs, priced_pairs=pairs
    ).inventory(manager)

    assert inventory.find("image", "mxapi", "visual")
    assert inventory.find("video", "mxapi", "movie")
    assert inventory.find("audio", "mxapi", "voice")


@pytest.mark.asyncio
async def test_inventory_reports_provider_and_adapter_reasons_in_stable_order():
    manager = StubManager(
        [
            provider(
                "disabled", [model("unknown", model_type="embedding")], disabled=True
            )
        ]
    )
    service = AigcModelPolicyService(
        StubPolicies(),
        published_pairs=set(),
        priced_pairs=set(),
    )

    items = (await service.inventory(manager)).uncategorized

    assert items[0].reasons == (
        "provider_disabled",
        "unpublished",
        "unpriced",
        "adapter_unsupported",
    )


@pytest.mark.asyncio
async def test_unconfigured_category_preserves_all_effective_models():
    models = [
        model("gpt-image-2", model_type="image"),
        model("seedream-5", model_type="image"),
    ]
    manager = StubManager([provider("p", models)])
    pairs = {("p", item.id) for item in models}
    service = AigcModelPolicyService(
        StubPolicies(), published_pairs=pairs, priced_pairs=pairs
    )

    effective = await service.effective("image", manager)

    assert effective.configured is False
    assert {item.model_id for item in effective.models} == {
        "gpt-image-2",
        "seedream-5",
    }


@pytest.mark.asyncio
async def test_invalid_configured_default_falls_back_without_overwriting_it():
    models = [
        model("gpt-image-2", model_type="image"),
        model("seedream-5", model_type="image"),
    ]
    manager = StubManager([provider("p", models)])
    saved = {
        "image": {
            "configured": True,
            "version": 4,
            "models": [
                {
                    "provider_id": "p",
                    "model_id": "gpt-image-2",
                    "sort_order": 0,
                    "is_default": True,
                },
                {
                    "provider_id": "p",
                    "model_id": "seedream-5",
                    "sort_order": 1,
                    "is_default": False,
                },
            ],
        }
    }
    service = AigcModelPolicyService(
        StubPolicies(saved),
        published_pairs={("p", "gpt-image-2"), ("p", "seedream-5")},
        priced_pairs={("p", "seedream-5")},
    )

    effective = await service.effective("image", manager)

    assert effective.configured_default.model_id == "gpt-image-2"
    assert effective.effective_default.model_id == "seedream-5"
    assert effective.fallback_active is True
    assert effective.fallback_reason == ("unpriced",)


@pytest.mark.asyncio
async def test_configured_default_recovers_when_selectable_again():
    item = model("gpt-image-2", model_type="image")
    manager = StubManager([provider("p", [item])])
    saved = {
        "image": {
            "configured": True,
            "models": [
                {
                    "provider_id": "p",
                    "model_id": item.id,
                    "sort_order": 0,
                    "is_default": True,
                }
            ],
        }
    }
    pair = {("p", item.id)}
    service = AigcModelPolicyService(
        StubPolicies(saved), published_pairs=pair, priced_pairs=pair
    )

    effective = await service.effective("image", manager)

    assert effective.effective_default == effective.configured_default
    assert effective.fallback_active is False


def test_filter_capabilities_removes_disallowed_models_but_keeps_plugins():
    capabilities = [
        SimpleNamespace(
            provider_id="p",
            model_id="allowed",
            capability="text_to_image",
            source="model_registry",
        ),
        SimpleNamespace(
            provider_id="p",
            model_id="removed",
            capability="image_edit",
            source="model_registry",
        ),
        SimpleNamespace(
            provider_id="plugin:x",
            model_id="generate_image",
            capability="text_to_image",
            source="plugin_tool",
        ),
    ]

    filtered = filter_capabilities(
        capabilities,
        {"image": {("p", "allowed")}},
    )

    assert [item.model_id for item in filtered] == ["allowed", "generate_image"]


@pytest.mark.parametrize("value", ["0", "false", "OFF", " off "])
def test_policy_enforcement_can_be_explicitly_disabled(value):
    assert policy_enforcement_enabled({"AIGC_MODEL_POLICY_ENFORCEMENT": value}) is False


def test_policy_enforcement_defaults_to_enabled():
    assert policy_enforcement_enabled({}) is True
