# -*- coding: utf-8 -*-
from __future__ import annotations

from qwenpaw.app.routers.providers import (
    EmbeddingSlotRequest,
    TestModelRequest as ModelTestRequest,
    _embedding_model_for_test,
    set_active_embedding_model,
    test_model as run_model_test,
)
from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.providers.provider import ModelInfo


class FakeProvider:
    id = "volcengine-cn"
    disabled = False
    models: list[ModelInfo] = []
    extra_models: list[ModelInfo] = []

    def __init__(self) -> None:
        self.checked_models: list[str] = []

    async def check_model_connection(self, model_id: str):
        self.checked_models.append(model_id)
        return False, "chat ping should not run"


class FakeProviderManager:
    def __init__(self, provider: FakeProvider) -> None:
        self.provider = provider
        self.active_embedding: ModelSlotConfig | None = None
        self.updated_configs: list[tuple[str, str, dict]] = []

    def get_provider(self, provider_id: str):
        return self.provider if provider_id == self.provider.id else None

    async def activate_embedding_model(
        self,
        provider_id: str,
        model_id: str,
    ) -> None:
        self.active_embedding = ModelSlotConfig(
            provider_id=provider_id,
            model=model_id,
        )

    def get_active_model(self):
        return None

    def get_active_embedding_model(self):
        return self.active_embedding

    async def update_model_config(self, provider_id, model_id, config):
        self.updated_configs.append((provider_id, model_id, config))
        model = next(
            item
            for item in self.provider.models + self.provider.extra_models
            if item.id == model_id
        )
        for key, value in config.items():
            setattr(model, key, value)
        return self.provider


async def test_seedream_image_model_test_skips_chat_ping() -> None:
    provider = FakeProvider()
    manager = FakeProviderManager(provider)

    response = await run_model_test(
        manager=manager,
        provider_id="volcengine-cn",
        body=ModelTestRequest(
            model_id="doubao-seedream-4-5-251128",
            model_type="image",
        ),
    )

    assert response.success is True
    assert provider.checked_models == []


async def test_registered_aigc_image_model_test_skips_chat_ping() -> None:
    provider = FakeProvider()
    provider.extra_models = [
        ModelInfo(
            id="custom-image-model",
            name="Custom Image Model",
            aigc_capabilities=["text_to_image"],
        ),
    ]
    manager = FakeProviderManager(provider)

    response = await run_model_test(
        manager=manager,
        provider_id="volcengine-cn",
        body=ModelTestRequest(model_id="custom-image-model"),
    )

    assert response.success is True
    assert provider.checked_models == []


async def test_llm_model_test_still_uses_chat_ping() -> None:
    provider = FakeProvider()
    manager = FakeProviderManager(provider)

    response = await run_model_test(
        manager=manager,
        provider_id="volcengine-cn",
        body=ModelTestRequest(model_id="doubao-seed-2-0-pro-260215"),
    )

    assert response.success is False
    assert provider.checked_models == ["doubao-seed-2-0-pro-260215"]


async def test_registered_embedding_model_uses_embedding_ping(
    monkeypatch,
) -> None:
    provider = FakeProvider()
    provider.extra_models = [
        ModelInfo(
            id="text-embedding-v4",
            name="Text Embedding V4",
            model_type="embedding",
            embedding_protocol="openai_compatible",
        ),
    ]
    manager = FakeProviderManager(provider)
    tested: list[str] = []

    async def fake_embedding_test(_provider, model):
        tested.append(model.id)
        return True, "Embedding connection successful (1024 dimensions)"

    monkeypatch.setattr(
        "qwenpaw.app.routers.providers._test_embedding_model",
        fake_embedding_test,
    )

    response = await run_model_test(
        manager=manager,
        provider_id="volcengine-cn",
        body=ModelTestRequest(model_id="text-embedding-v4"),
    )

    assert response.success is True
    assert tested == ["text-embedding-v4"]
    assert provider.checked_models == []


async def test_active_embedding_endpoint_tests_then_activates(
    monkeypatch,
) -> None:
    provider = FakeProvider()
    provider.extra_models = [
        ModelInfo(
            id="text-embedding-v4",
            name="Text Embedding V4",
            model_type="embedding",
            embedding_protocol="openai_compatible",
        ),
    ]
    manager = FakeProviderManager(provider)

    async def fake_embedding_test(_provider, _model):
        return True, "Embedding connection successful (1024 dimensions)"

    monkeypatch.setattr(
        "qwenpaw.app.routers.providers._test_embedding_model",
        fake_embedding_test,
    )

    response = await set_active_embedding_model(
        manager=manager,
        body=EmbeddingSlotRequest(
            provider_id="volcengine-cn",
            model="text-embedding-v4",
        ),
    )

    assert response.active_llm is None
    assert response.active_embedding == ModelSlotConfig(
        provider_id="volcengine-cn",
        model="text-embedding-v4",
    )


def test_dashscope_flash_embedding_uses_supported_dimension() -> None:
    model = _embedding_model_for_test(
        "dashscope",
        "tongyi-embedding-vision-flash-2026-03-06",
    )

    assert model.embedding_protocol == "dashscope_multimodal"
    assert model.embedding_dimensions == 768


async def test_registered_flash_embedding_repairs_stored_dimension(
    monkeypatch,
) -> None:
    provider = FakeProvider()
    provider.id = "dashscope"
    provider.extra_models = [
        ModelInfo(
            id="tongyi-embedding-vision-flash-2026-03-06",
            name="Tongyi Vision Flash",
            model_type="embedding",
            embedding_protocol="dashscope_multimodal",
            embedding_dimensions=1024,
        ),
    ]
    manager = FakeProviderManager(provider)

    async def fake_embedding_test(_provider, model):
        assert model.embedding_dimensions == 768
        return True, "Embedding connection successful (768 dimensions)"

    monkeypatch.setattr(
        "qwenpaw.app.routers.providers._test_embedding_model",
        fake_embedding_test,
    )

    response = await run_model_test(
        manager=manager,
        provider_id="dashscope",
        body=ModelTestRequest(
            model_id="tongyi-embedding-vision-flash-2026-03-06",
        ),
    )

    assert response.success is True
    assert provider.extra_models[0].embedding_dimensions == 768
    assert manager.updated_configs[0][2]["embedding_dimensions"] == 768
