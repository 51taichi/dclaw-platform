from types import SimpleNamespace

import pytest

from qwenpaw.app.aigc.model_policy import AigcModelPolicyService


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
