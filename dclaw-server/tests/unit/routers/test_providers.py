# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from types import SimpleNamespace

from qwenpaw.app.routers.providers import (
    EmbeddingSlotRequest,
    ModelSlotRequest,
    TestModelRequest as ModelTestRequest,
    _embedding_model_for_test,
    clear_active_model,
    set_active_embedding_model,
    set_active_model,
    test_model as run_model_test,
)
from qwenpaw.config.config import (
    AgentProfileRef,
    AgentsConfig,
    Config,
    ModelSlotConfig,
)
from qwenpaw.config.utils import load_config, save_config
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

    def maybe_probe_multimodal(self, _provider_id: str, _model_id: str) -> None:
        return None

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


async def test_agent_model_endpoint_stores_external_runtime_override(
    tmp_path,
    monkeypatch,
) -> None:
    workspace_dir = tmp_path / "sealed" / "luyu"
    workspace_dir.mkdir(parents=True)
    package_config_path = workspace_dir / "agent.json"
    package_config_path.write_text(
        json.dumps({"id": "luyu", "name": "Luyu"}),
        encoding="utf-8",
    )
    original_package_config = package_config_path.read_bytes()

    monkeypatch.setattr("qwenpaw.config.utils.WORKING_DIR", tmp_path)
    save_config(
        Config(
            agents=AgentsConfig(
                active_agent="luyu",
                profiles={
                    "luyu": AgentProfileRef(
                        id="luyu",
                        workspace_dir=str(workspace_dir),
                    ),
                },
            ),
        ),
    )

    async def fake_get_agent_for_request(_request, agent_id=None):
        assert agent_id == "luyu"
        return SimpleNamespace(agent_id="luyu")

    monkeypatch.setattr(
        "qwenpaw.app.routers.providers.get_agent_for_request",
        fake_get_agent_for_request,
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.providers._validate_model_slot",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.providers.schedule_agent_reload",
        lambda *_args: None,
    )

    manager = FakeProviderManager(FakeProvider())
    response = await set_active_model(
        request=object(),
        manager=manager,
        body=ModelSlotRequest(
            provider_id="volcengine-cn",
            model="deepseek-v4",
            scope="agent",
            agent_id="luyu",
        ),
    )

    profile = load_config().agents.profiles["luyu"]
    assert response.active_llm == ModelSlotConfig(
        provider_id="volcengine-cn",
        model="deepseek-v4",
    )
    assert profile.active_model_override is True
    assert profile.active_model == response.active_llm
    assert package_config_path.read_bytes() == original_package_config


async def test_clear_agent_model_keeps_explicit_global_default_override(
    tmp_path,
    monkeypatch,
) -> None:
    workspace_dir = tmp_path / "sealed" / "luyu"
    workspace_dir.mkdir(parents=True)
    monkeypatch.setattr("qwenpaw.config.utils.WORKING_DIR", tmp_path)
    save_config(
        Config(
            agents=AgentsConfig(
                active_agent="luyu",
                profiles={
                    "luyu": AgentProfileRef(
                        id="luyu",
                        workspace_dir=str(workspace_dir),
                        active_model_override=True,
                        active_model=ModelSlotConfig(
                            provider_id="volcengine-cn",
                            model="deepseek-v4",
                        ),
                    ),
                },
            ),
        ),
    )

    async def fake_get_agent_for_request(_request, agent_id=None):
        assert agent_id == "luyu"
        return SimpleNamespace(agent_id="luyu")

    monkeypatch.setattr(
        "qwenpaw.app.routers.providers.get_agent_for_request",
        fake_get_agent_for_request,
    )
    monkeypatch.setattr(
        "qwenpaw.app.routers.providers.schedule_agent_reload",
        lambda *_args: None,
    )

    response = await clear_active_model(
        request=object(),
        manager=FakeProviderManager(FakeProvider()),
        scope="agent",
        agent_id="luyu",
    )

    profile = load_config().agents.profiles["luyu"]
    assert response == {"status": "success"}
    assert profile.active_model_override is True
    assert profile.active_model is None


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
