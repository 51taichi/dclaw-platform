from types import SimpleNamespace

from qwenpaw.app.billing.pricing_inventory import (
    PricingModelInventory,
    classify_model,
)
from qwenpaw.providers.provider import ModelInfo


def test_classify_all_supported_categories():
    assert classify_model(ModelInfo(id="chat", name="Chat")) == "text"
    assert (
        classify_model(ModelInfo(id="img", name="Image", model_type="image"))
        == "image"
    )
    assert (
        classify_model(ModelInfo(id="vid", name="Video", model_type="video"))
        == "video"
    )
    assert (
        classify_model(
            ModelInfo(id="emb", name="Embedding", model_type="embedding")
        )
        == "embedding_rerank"
    )
    assert (
        classify_model(
            ModelInfo(
                id="tts", name="TTS", aigc_capabilities=["text_to_audio"]
            )
        )
        == "audio"
    )
    assert (
        classify_model(
            ModelInfo(
                id="odd", name="Odd", aigc_capabilities=["custom_operation"]
            )
        )
        == "other"
    )


def test_inventory_excludes_unconfigured_and_hidden_models():
    visible = ModelInfo(id="qwen-plus", name="Qwen Plus")
    hidden = ModelInfo(id="qwen-hidden", name="Hidden")
    configured = SimpleNamespace(
        id="dashscope",
        name="百炼",
        api_key="secret",
        require_api_key=True,
        is_local=False,
        models=[visible, hidden],
        extra_models=[],
        meta={"hidden_builtin_model_ids": ["qwen-hidden"]},
    )
    unconfigured = SimpleNamespace(
        id="openai",
        name="OpenAI",
        api_key="",
        require_api_key=True,
        is_local=False,
        models=[visible],
        extra_models=[],
        meta={},
    )
    manager = SimpleNamespace(
        builtin_providers={"dashscope": configured, "openai": unconfigured},
        custom_providers={},
        plugin_providers={},
    )
    rows = PricingModelInventory(manager).list_enabled()
    assert [
        (row.provider_id, row.model_key, row.category) for row in rows
    ] == [
        ("dashscope", "qwen-plus", "text"),
    ]
    assert rows[0].official_model_id == "qwen-plus"


def test_custom_inventory_requires_explicit_official_mapping():
    model = ModelInfo(id="qwen-alias", name="Qwen Alias")
    custom = SimpleNamespace(
        id="custom-qwen",
        name="Custom Qwen",
        api_key="secret",
        require_api_key=True,
        is_local=False,
        models=[model],
        extra_models=[],
        meta={},
    )
    manager = SimpleNamespace(
        builtin_providers={},
        custom_providers={"custom-qwen": custom},
        plugin_providers={},
    )

    assert (
        PricingModelInventory(manager).list_enabled()[0].official_model_id
        is None
    )
