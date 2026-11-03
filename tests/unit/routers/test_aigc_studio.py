# -*- coding: utf-8 -*-
"""Unit tests for AIGC Studio router."""

from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from qwenpaw.providers.provider import ModelInfo, ProviderInfo
from qwenpaw.app.routers import aigc_studio
from qwenpaw.app.routers.aigc_studio import public_router, router
from qwenpaw.app.runtime.event_bus import MemoryRuntimeEventBus
from qwenpaw.app.billing.model_publication import ModelPublicationService
from qwenpaw.app.storage.engine import create_engine_from_settings
from qwenpaw.app.storage.repos.aigc_model_policy_repo import (
    AigcModelPolicyRepository,
)
from qwenpaw.app.storage.schema import create_all
from qwenpaw.app.storage.settings import get_storage_settings


@pytest.fixture(autouse=True)
def execution_repository(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from qwenpaw.app.storage.repos.aigc_execution_repo import AigcExecutionRepository

    engine = create_engine(f"sqlite:///{tmp_path / 'aigc-core.sqlite'}")
    create_all(engine)
    monkeypatch.setattr("qwenpaw.app.storage.engine.get_app_engine", lambda: engine)
    yield AigcExecutionRepository(engine)
    engine.dispose()


@pytest.mark.asyncio
async def test_resolve_owned_asset_for_agent_review_returns_bound_local_media(
    tmp_path,
    monkeypatch,
):
    media_path = tmp_path / "result.mp4"
    media_path.write_bytes(b"video")
    asset = aigc_studio.AigcAsset(
        id="asset-review",
        kind="video",
        name="result.mp4",
        path=str(media_path),
        url="/api/aigc-studio/assets/asset-review/file",
        mime_type="video/mp4",
        created_at="2026-09-02T00:00:00Z",
        meta={"canvas_id": "canvas-1", "node_id": "node-1"},
    )
    monkeypatch.setattr(aigc_studio, "_load_asset_for_request", lambda *_args: asset)
    monkeypatch.setattr(aigc_studio, "_signed_cloud_asset_url", lambda _asset: None)

    async def artifact_root(*_args):
        return tmp_path

    monkeypatch.setattr(aigc_studio, "_artifact_root_for_request", artifact_root)
    monkeypatch.setattr(aigc_studio, "STUDIO_ROOT", tmp_path / "studio")
    block = await aigc_studio.resolve_owned_asset_for_agent_review(
        SimpleNamespace(),
        "asset-review",
        canvas_id="canvas-1",
        node_ids={"node-1", "node-2"},
    )
    assert block == {
        "type": "video",
        "source": {"type": "url", "url": media_path.as_uri()},
    }


@pytest.mark.asyncio
async def test_resolve_owned_asset_for_agent_review_rejects_binding_mismatch(
    monkeypatch,
):
    asset = aigc_studio.AigcAsset(
        id="asset-review",
        kind="image",
        name="result.png",
        path="result.png",
        url="/api/aigc-studio/assets/asset-review/file",
        mime_type="image/png",
        created_at="2026-09-02T00:00:00Z",
        meta={"canvas_id": "canvas-other", "node_id": "node-1"},
    )
    monkeypatch.setattr(aigc_studio, "_load_asset_for_request", lambda *_args: asset)
    with pytest.raises(HTTPException) as exc_info:
        await aigc_studio.resolve_owned_asset_for_agent_review(
            SimpleNamespace(),
            "asset-review",
            canvas_id="canvas-1",
            node_ids={"node-1"},
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_validate_job_submission_allows_authorized_workflow_model_override(
    monkeypatch, execution_repository
):
    from qwenpaw.app.aigc.workflow_execution import WorkflowExecutionBinding

    execution_repository.register_bindings([WorkflowExecutionBinding(
        owner_user_id="user-a", canvas_id="canvas-1", workflow_id="workflow-1",
        workflow_revision=1, node_id="video-1", logical_node_id="clip",
        provider_id="provider-1", model_id="video-1", capability="image_to_video",
    )], "test-workflow")
    canvas = aigc_studio.Canvas(
        id="canvas-1",
        name="Workflow",
        meta={"owner_user_id": "user-a"},
        nodes=[
            aigc_studio.CanvasNode(
                id="video-1",
                type="video_generate",
                position={"x": 0, "y": 0},
                data={
                    "workflowLogicalNodeId": "clip",
                    "providerId": "provider-1",
                    "modelId": "video-1",
                    "modelCapability": "image_to_video",
                },
            )
        ],
        edges=[],
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )
    monkeypatch.setattr(aigc_studio, "_load_canvas_for_request", lambda *_a: canvas)

    async def available(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(aigc_studio, "_find_capability", available)
    body = aigc_studio.AigcJobCreate(
        canvas_id="canvas-1",
        node_id="video-1",
        capability="image_to_video",
        provider_id="provider-2",
        model_id="video-2",
    )

    await aigc_studio._validate_job_submission(SimpleNamespace(), body)


@pytest.mark.asyncio
async def test_validate_job_submission_keeps_workflow_capability_binding_after_canvas_tamper(
    monkeypatch,
):
    canvas = aigc_studio.Canvas(
        id="canvas-1",
        name="Tampered workflow",
        nodes=[
            aigc_studio.CanvasNode(
                id="video-1",
                type="video_generate",
                position={"x": 0, "y": 0},
                data={
                    "providerId": "attacker-provider",
                    "modelId": "attacker-model",
                    "modelCapability": "text_to_video",
                },
            )
        ],
        edges=[],
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )
    monkeypatch.setattr(aigc_studio, "_load_canvas_for_request", lambda *_a: canvas)
    monkeypatch.setattr(
        aigc_studio,
        "_authoritative_workflow_execution_binding",
        lambda *_a: aigc_studio.WorkflowExecutionBinding(
            owner_user_id="user-a", canvas_id="canvas-1", workflow_id="workflow-1",
            workflow_revision=1, node_id="video-1", logical_node_id="clip",
            provider_id="provider-1", model_id="video-1", capability="image_to_video",
        ),
    )

    async def available(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(aigc_studio, "_find_capability", available)
    tampered = aigc_studio.AigcJobCreate(
        canvas_id="canvas-1",
        node_id="video-1",
        capability="text_to_video",
        provider_id="attacker-provider",
        model_id="attacker-model",
    )

    with pytest.raises(HTTPException) as exc_info:
        await aigc_studio._validate_job_submission(SimpleNamespace(), tampered)

    assert exc_info.value.status_code == 409
    await aigc_studio._validate_job_submission(
        SimpleNamespace(),
        tampered.model_copy(
            update={
                "capability": "image_to_video",
            }
        ),
    )


@pytest.mark.asyncio
async def test_validate_job_submission_restores_workflow_image_edit_mode(
    monkeypatch,
):
    canvas = aigc_studio.Canvas(
        id="canvas-1",
        name="Workflow image edit",
        nodes=[
            aigc_studio.CanvasNode(
                id="image-1",
                type="image_generate",
                position={"x": 0, "y": 0},
                data={
                    "workflowLogicalNodeId": "repair_image",
                    "providerId": "mxapi",
                    "modelId": "gpt-image-2",
                    "modelCapability": "text_to_image",
                },
            ),
        ],
        edges=[],
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )
    monkeypatch.setattr(
        aigc_studio,
        "_load_canvas_for_request",
        lambda *_args: canvas,
    )
    monkeypatch.setattr(
        aigc_studio,
        "_authoritative_workflow_execution_binding",
        lambda *_args: aigc_studio.WorkflowExecutionBinding(
            owner_user_id="user-a",
            canvas_id="canvas-1",
            workflow_id="workflow-1",
            workflow_revision=1,
            node_id="image-1",
            logical_node_id="repair_image",
            provider_id="mxapi",
            model_id="gpt-image-2",
            capability="image_edit",
        ),
    )
    observed = []

    async def available(
        _request,
        _provider_id,
        _model_id,
        capability,
        **_kwargs,
    ):
        observed.append(capability)
        return object()

    monkeypatch.setattr(aigc_studio, "_find_capability", available)
    body = aigc_studio.AigcJobCreate(
        canvas_id="canvas-1",
        node_id="image-1",
        capability="text_to_image",
        provider_id="mxapi",
        model_id="gpt-image-2",
        inputs={"reference_nodes": [{"asset_id": "reference"}]},
    )

    await aigc_studio._validate_job_submission(SimpleNamespace(), body)

    assert body.capability == "image_edit"
    assert observed == ["image_edit"]


class _AllPublished(set):
    def __bool__(self):
        return True

    def __contains__(self, _value):
        return True


@pytest.fixture(autouse=True)
def _publish_fixture_models(monkeypatch):
    monkeypatch.setattr(
        ModelPublicationService,
        "effective_pairs",
        lambda _self: _AllPublished(),
    )


class FakeProviderManager:
    """Minimal provider manager for capability tests."""

    async def list_provider_info(self):
        return [
            ProviderInfo(
                id="openai",
                name="OpenAI",
                api_key="******",
                models=[
                    ModelInfo(
                        id="gpt-image-2",
                        name="GPT Image 2",
                        aigc_capabilities=["text_to_image", "image_edit"],
                    ),
                ],
            ),
            ProviderInfo(
                id="volcengine",
                name="Volcengine",
                api_key="******",
                extra_models=[
                    ModelInfo(
                        id="glm-5-chat",
                        name="GLM-5 Chat",
                        aigc_capabilities=["storyboard"],
                    ),
                    ModelInfo(
                        id="deepseek-chat",
                        name="DeepSeek Chat",
                        aigc_capabilities=["storyboard"],
                    ),
                    ModelInfo(
                        id="generic-llm",
                        name="Generic LLM",
                        aigc_capabilities=["llm"],
                    ),
                    ModelInfo(
                        id="generic-chat-completion",
                        name="Generic Chat Completion",
                        aigc_capabilities=["chat_completion"],
                    ),
                    ModelInfo(
                        id="kimi-k2",
                        name="Kimi K2",
                    ),
                    ModelInfo(
                        id="doubao-seedream-3-0-t2i",
                        name="Doubao Seedream 3.0",
                        aigc_capabilities=["text_to_image"],
                    ),
                    ModelInfo(
                        id="doubao-seedream-5-0-260128",
                        name="Doubao Seedream 5.0",
                        supports_image=True,
                    ),
                    ModelInfo(
                        id="doubao-seededit-3-0-i2i",
                        name="Doubao SeedEdit 3.0",
                        supports_image=True,
                    ),
                    ModelInfo(
                        id="custom-image-model",
                        name="Custom image model",
                        aigc_capabilities=["text_to_image"],
                    ),
                    ModelInfo(
                        id="seedance-pro",
                        name="Seedance Pro",
                        aigc_capabilities=["text_to_video", "image_to_video"],
                    ),
                ],
            ),
            ProviderInfo(
                id="stub-aigc",
                name="Stub AIGC",
                api_key="******",
                meta={"aigc_adapter": "artifact_stub"},
                models=[
                    ModelInfo(
                        id="stub-image",
                        name="Stub Image",
                        aigc_capabilities=["text_to_image"],
                    ),
                ],
            ),
            ProviderInfo(
                id="opencode",
                name="OpenCode",
                require_api_key=False,
                models=[
                    ModelInfo(
                        id="big-pickle",
                        name="Big Pickle",
                    ),
                ],
            ),
            ProviderInfo(
                id="modelscope",
                name="ModelScope",
                models=[
                    ModelInfo(
                        id="Qwen/Qwen3.5-122B-A10B",
                        name="Qwen3.5-122B-A10B",
                    ),
                ],
            ),
        ]


class FakeTextModel:
    """Minimal async chat model used by text-generation jobs."""

    def __init__(
        self,
        text: str = "生成后的屋顶机器人故事",
        *,
        stream: bool = False,
    ):
        self.text = text
        self.stream = stream
        self.calls: list[list[dict]] = []

    async def __call__(self, messages):
        self.calls.append(messages)
        if self.stream:

            async def chunks():
                yield SimpleNamespace(content=[{"type": "text", "text": self.text}])

            return chunks()
        return SimpleNamespace(content=self.text)


class FakeTextRuntimeProvider:
    def __init__(self, *, supports_image: bool = False, stream: bool = False):
        self.id = "text-provider"
        self.name = "Text Provider"
        self.meta = {}
        self.api_key = "sk-text"
        self.base_url = "https://text.example.test/v1"
        self.chat_model = FakeTextModel(stream=stream)
        self.models = [
            ModelInfo(
                id="gvlm-3-1",
                name="GVLM 3.1",
                aigc_capabilities=["storyboard"],
                supports_image=supports_image,
            )
        ]
        self.extra_models = []

    def get_chat_model_instance(self, model_id: str):
        if model_id != "gvlm-3-1":
            raise KeyError(model_id)
        return self.chat_model


class FakeTextProviderManager:
    """Provider manager with a runtime chat model for storyboard jobs."""

    def __init__(self, *, supports_image: bool = False, stream: bool = False):
        self.provider = FakeTextRuntimeProvider(
            supports_image=supports_image,
            stream=stream,
        )

    def get_provider(self, provider_id: str):
        return self.provider if provider_id == self.provider.id else None

    async def list_provider_info(self):
        return [
            ProviderInfo(
                id=self.provider.id,
                name=self.provider.name,
                api_key="******",
                base_url=self.provider.base_url,
                models=self.provider.models,
            )
        ]


class FakeMediaAdapterProviderManager:
    """Provider manager with a generic configured AIGC adapter."""

    def __init__(self):
        self.provider = ProviderInfo(
            id="media-stub",
            name="Media Stub",
            api_key="******",
            meta={"aigc_adapter": "artifact_stub"},
            models=[
                ModelInfo(
                    id="stub-video",
                    name="Stub Video",
                    aigc_capabilities=["text_to_video"],
                ),
                ModelInfo(
                    id="stub-audio",
                    name="Stub Audio",
                    aigc_capabilities=["text_to_audio"],
                ),
            ],
        )

    def get_provider(self, provider_id: str):
        return self.provider if provider_id == self.provider.id else None

    async def list_provider_info(self):
        return [self.provider]


class FakeOpenAIProviderManager:
    """Provider manager with a configured OpenAI image model."""

    async def list_provider_info(self):
        return [
            ProviderInfo(
                id="openai",
                name="OpenAI",
                api_key="sk-test",
                base_url="https://api.openai.com/v1",
                models=[
                    ModelInfo(
                        id="gpt-image-2",
                        name="GPT Image 2",
                        aigc_capabilities=["text_to_image"],
                    ),
                ],
            ),
        ]


class FakeSeedreamProviderManager:
    """Provider manager with a Volcengine Seedream image model."""

    def __init__(self):
        self.provider = ProviderInfo(
            id="volcengine",
            name="Volcengine",
            api_key="ark-runtime-key",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            extra_models=[
                ModelInfo(
                    id="doubao-seedream-3-0-t2i",
                    name="Doubao Seedream 3.0",
                    aigc_capabilities=["text_to_image"],
                ),
                ModelInfo(
                    id="doubao-seedream-4-5-251128",
                    name="Doubao Seedream 4.5",
                    aigc_capabilities=["text_to_image"],
                ),
            ],
        )

    def get_provider(self, provider_id: str):
        return self.provider if provider_id == self.provider.id else None

    async def list_provider_info(self):
        return [
            ProviderInfo(
                id="volcengine",
                name="Volcengine",
                api_key="******",
                base_url="https://ark.cn-beijing.volces.com/api/v3",
                extra_models=[
                    ModelInfo(
                        id="doubao-seedream-3-0-t2i",
                        name="Doubao Seedream 3.0",
                        aigc_capabilities=["text_to_image"],
                    ),
                    ModelInfo(
                        id="doubao-seedream-4-5-251128",
                        name="Doubao Seedream 4.5",
                        aigc_capabilities=["text_to_image"],
                    ),
                ],
            ),
        ]


class FakeMxapiProviderManager:
    """Provider manager with an MXAPI GPT Image 2 model."""

    def __init__(self):
        self.provider = ProviderInfo(
            id="mxapi",
            name="MXAPI",
            api_key="mxapi-test-key",
            base_url="https://open.mxapi.org",
            custom_headers={
                "X-Channel": "official",
                "X-Provider-Trace": "enabled",
                "Authorization": "must-not-override-api-key",
            },
            meta={"aigc_adapter": "mxapi_gpt_image", "channel": "default"},
            models=[
                ModelInfo(
                    id="gpt-image-2",
                    name="GPT Image 2",
                    aigc_capabilities=["text_to_image", "image_to_image", "image_edit"],
                ),
                ModelInfo(
                    id="nano2",
                    name="Nano Banana2",
                    generate_kwargs={"aigc_adapter": "mxapi_nano2"},
                    aigc_capabilities=["text_to_image", "image_to_image", "image_edit"],
                ),
                ModelInfo(
                    id="seedance2",
                    name="Seedance 2.0",
                    supports_image=True,
                    supports_video=True,
                    probe_source="documentation",
                    generate_kwargs={
                        "aigc_adapter": "mxapi_seedance2",
                        "mxapi_video_endpoint": "seedance2",
                    },
                    aigc_capabilities=[
                        "text_to_video",
                        "image_to_video",
                        "reference_video",
                    ],
                ),
                ModelInfo(
                    id="seedance2-fast",
                    name="Seedance 2.0 Fast",
                    supports_image=True,
                    supports_video=True,
                    probe_source="documentation",
                    generate_kwargs={
                        "aigc_adapter": "mxapi_seedance2",
                        "mxapi_video_endpoint": "seedance2-fast",
                    },
                    aigc_capabilities=[
                        "text_to_video",
                        "image_to_video",
                        "reference_video",
                    ],
                ),
                ModelInfo(
                    id="seedance2-mini",
                    name="Seedance 2.0 Mini",
                    supports_image=True,
                    supports_video=True,
                    probe_source="documentation",
                    generate_kwargs={
                        "aigc_adapter": "mxapi_seedance2",
                        "mxapi_video_endpoint": "seedance2-mini",
                    },
                    aigc_capabilities=[
                        "text_to_video",
                        "image_to_video",
                        "reference_video",
                    ],
                ),
            ],
        )

    def get_provider(self, provider_id: str):
        return self.provider if provider_id == self.provider.id else None

    async def list_provider_info(self):
        return [
            ProviderInfo(
                id="mxapi",
                name="MXAPI",
                api_key="******",
                base_url="https://open.mxapi.org",
                meta={"aigc_adapter": "mxapi_gpt_image", "channel": "default"},
                models=[
                    ModelInfo(
                        id="gpt-image-2",
                        name="GPT Image 2",
                        aigc_capabilities=[
                            "text_to_image",
                            "image_to_image",
                            "image_edit",
                        ],
                    ),
                    ModelInfo(
                        id="nano2",
                        name="Nano Banana2",
                        generate_kwargs={"aigc_adapter": "mxapi_nano2"},
                        aigc_capabilities=[
                            "text_to_image",
                            "image_to_image",
                            "image_edit",
                        ],
                    ),
                    ModelInfo(
                        id="seedance2",
                        name="Seedance 2.0",
                        supports_image=True,
                        supports_video=True,
                        probe_source="documentation",
                        generate_kwargs={
                            "aigc_adapter": "mxapi_seedance2",
                            "mxapi_video_endpoint": "seedance2",
                        },
                        aigc_capabilities=[
                            "text_to_video",
                            "image_to_video",
                            "reference_video",
                        ],
                    ),
                    ModelInfo(
                        id="seedance2-fast",
                        name="Seedance 2.0 Fast",
                        supports_image=True,
                        supports_video=True,
                        probe_source="documentation",
                        generate_kwargs={
                            "aigc_adapter": "mxapi_seedance2",
                            "mxapi_video_endpoint": "seedance2-fast",
                        },
                        aigc_capabilities=[
                            "text_to_video",
                            "image_to_video",
                            "reference_video",
                        ],
                    ),
                    ModelInfo(
                        id="seedance2-mini",
                        name="Seedance 2.0 Mini",
                        supports_image=True,
                        supports_video=True,
                        probe_source="documentation",
                        generate_kwargs={
                            "aigc_adapter": "mxapi_seedance2",
                            "mxapi_video_endpoint": "seedance2-mini",
                        },
                        aigc_capabilities=[
                            "text_to_video",
                            "image_to_video",
                            "reference_video",
                        ],
                    ),
                ],
            ),
        ]


def make_app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.state.provider_manager = FakeProviderManager()
    app.state.aigc_artifact_root = tmp_path / "workspace"
    install_test_user_middleware(app)
    app.include_router(router, prefix="/api")
    app.include_router(public_router, prefix="/api")
    return app


def install_test_user_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def _set_default_user(request, call_next):
        if getattr(request.state, "user_id", None) is None:
            request.state.user_id = "0"
            request.state.role = "user"
        return await call_next(request)


def make_text_app(
    tmp_path: Path,
    *,
    supports_image: bool = False,
    stream: bool = False,
) -> FastAPI:
    app = FastAPI()
    app.state.provider_manager = FakeTextProviderManager(
        supports_image=supports_image,
        stream=stream,
    )
    app.state.aigc_artifact_root = tmp_path / "workspace"
    install_test_user_middleware(app)
    app.include_router(router, prefix="/api")
    app.include_router(public_router, prefix="/api")
    return app


def make_media_adapter_app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.state.provider_manager = FakeMediaAdapterProviderManager()
    app.state.aigc_artifact_root = tmp_path / "workspace"
    install_test_user_middleware(app)
    app.include_router(router, prefix="/api")
    app.include_router(public_router, prefix="/api")
    return app


def make_role_app(tmp_path: Path, role: str) -> FastAPI:
    app = make_app(tmp_path)

    @app.middleware("http")
    async def _set_role(request, call_next):
        request.state.user_id = 1
        request.state.role = role
        return await call_next(request)

    return app


def make_user_switching_app(tmp_path: Path) -> FastAPI:
    app = make_app(tmp_path)

    @app.middleware("http")
    async def _set_user(request, call_next):
        request.state.user_id = request.headers.get("x-test-user-id", "1")
        request.state.role = request.headers.get("x-test-role", "user")
        return await call_next(request)

    return app


def make_openai_app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.state.provider_manager = FakeOpenAIProviderManager()
    app.state.aigc_artifact_root = tmp_path / "workspace"
    install_test_user_middleware(app)
    app.include_router(router, prefix="/api")
    app.include_router(public_router, prefix="/api")
    return app


def make_seedream_app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.state.provider_manager = FakeSeedreamProviderManager()
    app.state.aigc_artifact_root = tmp_path / "workspace"
    install_test_user_middleware(app)
    app.include_router(router, prefix="/api")
    app.include_router(public_router, prefix="/api")
    return app


def make_mxapi_app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.state.provider_manager = FakeMxapiProviderManager()
    app.state.aigc_artifact_root = tmp_path / "workspace"
    install_test_user_middleware(app)
    app.include_router(router, prefix="/api")
    app.include_router(public_router, prefix="/api")
    return app


async def test_capabilities_are_loaded_from_model_registry(tmp_path):
    """Capabilities should come from provider/model metadata, not constants."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/aigc-studio/capabilities")

    assert resp.status_code == 200
    capabilities = resp.json()["capabilities"]
    assert any(
        item["provider_id"] == "openai"
        and item["model_id"] == "gpt-image-2"
        and item["capability"] == "text_to_image"
        and item["source"] == "model_registry"
        for item in capabilities
    )
    gpt_image = next(
        item
        for item in capabilities
        if item["provider_id"] == "openai"
        and item["model_id"] == "gpt-image-2"
        and item["capability"] == "text_to_image"
    )
    assert gpt_image["parameter_schema"]["max_reference_images"] == 16
    assert (
        gpt_image["parameter_schema"]["properties"]["referenceImages"]["maxItems"] == 16
    )
    assert any(
        item["provider_id"] == "volcengine"
        and item["model_id"] == "seedance-pro"
        and item["capability"] == "image_to_video"
        and item["source"] == "model_registry"
        for item in capabilities
    )
    seedance_video = next(
        item
        for item in capabilities
        if item["provider_id"] == "volcengine"
        and item["model_id"] == "seedance-pro"
        and item["capability"] == "text_to_video"
    )
    duration_schema = seedance_video["parameter_schema"]["properties"]["duration"]
    assert duration_schema["minimum"] == 4
    assert duration_schema["maximum"] == 15
    assert duration_schema["default"] == 5
    assert any(
        item["provider_id"] == "volcengine"
        and item["model_id"] == "doubao-seedream-5-0-260128"
        and item["capability"] == "text_to_image"
        and item["source"] == "model_registry"
        for item in capabilities
    )
    assert any(
        item["provider_id"] == "volcengine"
        and item["model_id"] == "doubao-seededit-3-0-i2i"
        and item["capability"] == "image_edit"
        and item["source"] == "model_registry"
        for item in capabilities
    )
    storyboard_models = {
        item["model_id"]
        for item in capabilities
        if item["provider_id"] == "volcengine" and item["capability"] == "storyboard"
    }
    assert {"glm-5-chat", "deepseek-chat"}.issubset(
        storyboard_models,
    )
    assert "generic-llm" not in storyboard_models
    assert "generic-chat-completion" not in storyboard_models
    assert "kimi-k2" not in storyboard_models
    assert "doubao-seedream-3-0-t2i" not in storyboard_models
    assert not any(
        item["provider_id"] == "opencode" and item["model_id"] == "big-pickle"
        for item in capabilities
    )
    assert not any(
        item["provider_id"] == "modelscope"
        and item["model_id"] == "Qwen/Qwen3.5-122B-A10B"
        for item in capabilities
    )


async def test_capabilities_fail_closed_without_effective_catalog(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        ModelPublicationService,
        "effective_pairs",
        lambda _self: None,
    )
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/aigc-studio/capabilities")

    assert response.status_code == 200
    assert response.json() == {"capabilities": [], "defaults": {}}


async def test_configured_image_policy_filters_capabilities_and_returns_default(
    tmp_path,
    monkeypatch,
):
    engine = create_engine_from_settings(
        get_storage_settings({"QWENPAW_SQLITE_PATH": str(tmp_path / "policy.sqlite")})
    )
    create_all(engine)
    repository = AigcModelPolicyRepository(engine)
    selected = {"provider_id": "stub-aigc", "model_id": "stub-image"}
    repository.replace("image", None, [selected], selected, 7)
    monkeypatch.setattr(
        "qwenpaw.app.storage.engine.get_app_engine",
        lambda: engine,
    )
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/aigc-studio/capabilities")
        workflow_response = await client.get(
            "/api/aigc-studio/workflow-capabilities"
        )

    assert response.status_code == 200
    payload = response.json()
    image_pairs = {
        (item["provider_id"], item["model_id"])
        for item in payload["capabilities"]
        if item["capability"] in {"text_to_image", "image_edit"}
        and item["source"] == "model_registry"
    }
    assert image_pairs == {("stub-aigc", "stub-image")}
    assert payload["defaults"]["image"] == {
        "configured": True,
        "configured_default": selected,
        "effective_default": selected,
        "fallback_active": False,
        "fallback_reason": [],
    }
    workflow_image_pairs = {
        (item["provider_id"], item["model_id"])
        for item in workflow_response.json()["available_models"]
        if item["capability"] in {"text_to_image", "image_edit"}
        and item["source"] == "model_registry"
    }
    assert workflow_image_pairs == {
        ("stub-aigc", "stub-image"),
        ("openai", "gpt-image-2"),
        ("volcengine", "custom-image-model"),
        ("volcengine", "doubao-seedream-3-0-t2i"),
    }
    engine.dispose()


@pytest.mark.parametrize(
    "configured,published,disabled,api_key,tagged,expected",
    [
        (True, True, False, "configured", False, True),
        (True, True, False, "configured", True, True),
        (False, True, False, "configured", False, False),
        (True, False, False, "configured", False, False),
        (True, True, True, "configured", False, False),
        (True, True, False, "", False, False),
    ],
)
async def test_text_policy_inventory_preserves_availability_and_selection_gates(
    tmp_path, monkeypatch, configured, published, disabled, api_key,
    tagged, expected,
):
    from qwenpaw.app.storage.engine import get_app_engine

    selected = {"provider_id": "text-provider", "model_id": "configured-llm"}
    if configured:
        AigcModelPolicyRepository(get_app_engine()).replace(
            "text", None, [selected], selected, 7,
        )
    provider = ProviderInfo(
        id="text-provider", name="Text Provider", api_key=api_key,
        disabled=disabled,
        models=[
            ModelInfo(
                id="configured-llm", name="Configured LLM",
                aigc_capabilities=["storyboard"] if tagged else [],
            ),
            ModelInfo(id="not-selected", name="Unselected LLM"),
        ],
    )

    class Manager:
        async def list_provider_info(self):
            return [provider]

    monkeypatch.setattr(
        ModelPublicationService, "effective_pairs",
        lambda _self: (
            {("text-provider", "configured-llm"),
             ("text-provider", "not-selected")}
            if published else set()
        ),
    )
    app = make_app(tmp_path)
    app.state.provider_manager = Manager()
    request = SimpleNamespace(app=app)
    inventory = await aigc_studio.list_capabilities(request)
    projected = [
        item.model_id for item in inventory.capabilities
        if item.provider_id == "text-provider" and item.capability == "storyboard"
    ]
    assert projected == (["configured-llm"] if expected else [])
    # Submission uses the same capability lookup, not just the visible menu.
    found = await aigc_studio._find_capability(
        request, "text-provider", "configured-llm", "storyboard",
    )
    assert (found is not None) == expected
    alternative = await aigc_studio._find_capability(
        request, "text-provider", "not-selected", "storyboard",
    )
    assert alternative is None


async def test_job_submission_rejects_model_removed_from_allowlist(
    tmp_path,
    monkeypatch,
):
    engine = create_engine_from_settings(
        get_storage_settings(
            {"QWENPAW_SQLITE_PATH": str(tmp_path / "policy-job.sqlite")}
        )
    )
    create_all(engine)
    repository = AigcModelPolicyRepository(engine)
    selected = {"provider_id": "stub-aigc", "model_id": "stub-image"}
    repository.replace("image", None, [selected], selected, 7)
    monkeypatch.setattr(
        "qwenpaw.app.storage.engine.get_app_engine",
        lambda: engine,
    )
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "policy",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            response = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "openai",
                    "model_id": "gpt-image-2",
                    "inputs": {"prompt": "blocked"},
                },
            )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "aigc_model_not_allowed"
    engine.dispose()


async def test_visual_dna_catalog_search_and_compile_endpoints(tmp_path):
    """Visual DNA should be queryable and compilable without provider coupling."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        dimensions = await client.get("/api/aigc-studio/visual-dna/dimensions")
        elements = await client.get(
            "/api/aigc-studio/visual-dna/elements",
            params={"dimension": "lighting", "q": "电影"},
        )
        compiled = await client.post(
            "/api/aigc-studio/visual-dna/compile",
            json={
                "selections": [
                    {
                        "element_id": "lighting.cinematic_contrast",
                        "weight": 0.9,
                    },
                    {
                        "element_id": "constraint.preserve_product",
                        "weight": 1,
                    },
                ],
                "provider_id": "openai",
                "model_id": "gpt-image-2",
            },
        )

    assert dimensions.status_code == 200
    assert any(
        item["id"] == "lighting" and item["element_count"] >= 3
        for item in dimensions.json()["dimensions"]
    )
    assert elements.status_code == 200
    assert elements.json()["total"] == 1
    assert elements.json()["elements"][0]["id"] == "lighting.cinematic_contrast"
    assert compiled.status_code == 200
    assert "【光影】" in compiled.json()["prompt_appendix"]
    assert any("保持产品外形" in item for item in compiled.json()["constraints"])


def test_image_prompt_compiles_visual_dna_instead_of_repeating_flat_style_text():
    job = aigc_studio.AigcJob(
        id="job-visual-dna",
        canvas_id="canvas-1",
        node_id="image-1",
        capability="text_to_image",
        provider_id="openai",
        model_id="gpt-image-2",
        inputs={"prompt": "一个站在海边的人物"},
        parameters={
            "styleRuntimeMode": "prompt_style",
            "styleReferenceName": "电影感",
            "styleDescription": "旧的扁平风格描述",
            "styleKeywords": "旧关键词",
            "visualDna": [
                {"element_id": "lighting.golden_hour_rim", "weight": 0.9},
                {"element_id": "environment.ocean_breeze", "weight": 0.7},
            ],
        },
        status="queued",
        created_at=aigc_studio._now(),
        updated_at=aigc_studio._now(),
    )

    prompt = aigc_studio._image_prompt_from_job(job)

    assert prompt.startswith("一个站在海边的人物")
    assert "风格参考：电影感" in prompt
    assert "【结构化视觉 DNA】" in prompt
    assert "黄金时刻轮廓光" in prompt
    assert "海风环境" in prompt
    assert "旧的扁平风格描述" not in prompt
    assert "旧关键词" not in prompt


def test_image_prompt_uses_aesthetic_profile_snapshot_and_style_references():
    style_reference = "/api/user/aigc-studio/assets/style-reference/file"
    job = aigc_studio.AigcJob(
        id="job-aesthetic-profile",
        canvas_id="canvas-1",
        node_id="image-1",
        capability="text_to_image",
        provider_id="volcengine",
        model_id="doubao-seedream-4-5-251128",
        inputs={"prompt": "一个产品静物画面"},
        parameters={
            "styleRuntimeMode": "prompt_style",
            "aestheticProfileSnapshot": {
                "id": "style-premium",
                "title": "高端编辑视觉",
                "version": "1.0",
                "supplemental_prompt": "装饰保持克制。",
                "visual_dna": [
                    {
                        "element_id": "art_direction.premium_editorial",
                        "weight": 0.9,
                    }
                ],
                "reference_image_urls": [style_reference],
            },
        },
        status="queued",
        created_at=aigc_studio._now(),
        updated_at=aigc_studio._now(),
    )

    prompt = aigc_studio._image_prompt_from_job(job)

    assert "风格参考：高端编辑视觉" in prompt
    assert "高端编辑视觉（强）" in prompt
    assert "风格补充说明：装饰保持克制。" in prompt
    assert aigc_studio.STYLE_REFERENCE_IMAGE_PROMPT in prompt
    assert aigc_studio.REFERENCE_IMAGE_PRESERVATION_PROMPT not in prompt
    assert style_reference in aigc_studio._seedream_reference_candidates(job)


async def test_style_templates_can_be_created_filtered_and_marked_used(tmp_path):
    """Style templates should be a real AIGC registry, not frontend-only mock data."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)
    payload = {
        "id": "style-cgv2",
        "title": "一键国漫CGV2",
        "type": "style",
        "provider": "libtv",
        "model_family": "seedream-4.5",
        "cover_url": "https://cdn.example.test/cgv2.jpg",
        "category": "推荐",
        "tags": ["推荐", "商用"],
        "keywords": "国漫, CG, 冷色调",
        "description": "国漫 CG 风格，冷色调金属质感。",
        "prompt_template": "主体：{主体}\n场景：{场景}",
        "commercial": True,
        "runtime_mode": "native_effect",
        "effect_template_uuid": "dbc6dfc0990d46d28215bcdff87d53c3",
        "effect_id": 22910748,
        "use_count": 3300,
        "status": "enabled",
    }

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/aigc-studio/style-templates",
                json=payload,
            )
            assert created.status_code == 201

            listed = await client.get(
                "/api/aigc-studio/style-templates",
                params={
                    "type": "style",
                    "model_family": "seedream-4.5",
                    "category": "推荐",
                    "q": "国漫",
                    "commercial_only": "true",
                },
            )
            assert listed.status_code == 200
            templates = listed.json()["templates"]
            assert [item["id"] for item in templates] == ["style-cgv2"]
            assert templates[0]["effect_template_uuid"] == (
                "dbc6dfc0990d46d28215bcdff87d53c3"
            )
            assert templates[0]["prompt_template"] == "主体：{主体}\n场景：{场景}"

            used = await client.post(
                "/api/aigc-studio/style-templates/style-cgv2/use",
            )
            assert used.status_code == 200
            assert used.json()["use_count"] == 3301

            recent = await client.get("/api/aigc-studio/style-templates/recent")
    assert recent.status_code == 200
    assert recent.json()["templates"][0]["id"] == "style-cgv2"


async def test_default_style_templates_include_brand_strength_poster_prompt(tmp_path):
    """The built-in brand-strength poster should live in creation templates."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            listed = await client.get(
                "/api/aigc-studio/style-templates",
                params={"q": "高端品牌实力海报"},
            )

    assert listed.status_code == 200
    templates = listed.json()["templates"]
    assert [item["id"] for item in templates] == ["style-brand-strength-poster"]
    template = templates[0]
    assert template["title"] == "高端品牌实力海报"
    assert template["type"] == "play"
    assert template["runtime_mode"] == "prompt_style"
    assert "【风格气质】" in template["description"]
    assert "高端、沉稳、工业质感、品牌大片感" in template["description"]
    assert "产品和场景要自然融合" in template["description"]
    assert "不要把产品放进生硬的浅色矩形卡片" in template["description"]
    assert "【画面结构】" not in template["description"]
    assert "【品牌信息】" not in template["description"]
    assert "只出现以下文字" not in template["description"]
    assert "「{品牌名称}」" not in template["description"]
    assert "品牌名称：{品牌名称}" in template["prompt_template"]
    assert "产品名称：{产品名称}" in template["prompt_template"]
    assert "画面主体：" in template["prompt_template"]
    assert "产品和场景要自然融合" not in template["prompt_template"]
    assert template["prompt_template"] != template["description"]
    assert "【视觉风格】" not in template["prompt_template"]
    assert template["visual_dna"] == []
    assert (
        "不要复刻原图构图、字体、光线、产品角度、文字内容或具体排版。"
        not in template["prompt_template"]
    )


async def test_aesthetic_profile_and_creation_templates_are_queryable_separately(
    tmp_path,
):
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            styles = await client.get(
                "/api/aigc-studio/style-templates",
                params={"type": "style", "q": "高端工业品牌大片"},
            )
            plays = await client.get(
                "/api/aigc-studio/style-templates",
                params={"type": "play", "category": "海报场景"},
            )

    assert [item["id"] for item in styles.json()["templates"]] == [
        "style-premium-industrial-editorial"
    ]
    profile = styles.json()["templates"][0]
    assert profile["model_family"] is None
    assert profile["prompt_template"] == ""
    assert {item["element_id"] for item in profile["visual_dna"]} >= {
        "art_direction.premium_editorial",
        "lighting.cinematic_contrast",
        "environment.industrial_depth",
    }
    assert plays.json()["templates"]
    assert all(item["type"] == "play" for item in plays.json()["templates"])
    assert all(item["model_family"] is None for item in plays.json()["templates"])
    assert all(item["prompt_template"] for item in plays.json()["templates"])


async def test_default_style_templates_include_factory_hero_poster_prompt(tmp_path):
    """The factory hero poster preset should match the giant-title manufacturing layout."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            listed = await client.get(
                "/api/aigc-studio/style-templates",
                params={"q": "两省三厂"},
            )

    assert listed.status_code == 200
    templates = listed.json()["templates"]
    assert [item["id"] for item in templates] == ["style-factory-hero-poster"]
    template = templates[0]
    assert template["title"] == "巨幅标题工厂背书海报"
    assert template["category"] == "海报场景"
    assert template["type"] == "play"
    assert template["runtime_mode"] == "prompt_style"
    assert "巨幅标题压迫感" in template["description"]
    assert "真实生产车间纵深" in template["description"]
    assert "浅色矩形卡片" in template["description"]
    assert "主标题：{如：两省三厂}" in template["prompt_template"]
    assert "核心视觉：产品作为左下前景英雄位" in template["prompt_template"]
    assert "卖点1：{如：两省三厂}" in template["prompt_template"]
    assert "右侧三个徽章卖点" in template["prompt_template"]
    assert "巨幅标题压迫感" not in template["prompt_template"]


async def test_default_style_templates_include_poster_scene_suite(tmp_path):
    """Poster scene presets should be parallel task templates, not one catch-all style."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            listed = await client.get(
                "/api/aigc-studio/style-templates",
                params={"category": "海报场景"},
            )

    assert listed.status_code == 200
    templates = listed.json()["templates"]
    by_id = {template["id"]: template for template in templates}
    expected = {
        "style-brand-strength-poster": "高端品牌实力海报",
        "style-factory-hero-poster": "巨幅标题工厂背书海报",
        "style-product-selling-points-poster": "产品卖点海报",
        "style-source-ingredient-poster": "源头原料海报",
        "style-process-flow-poster": "工艺流程海报",
        "style-channel-recruitment-poster": "招商渠道海报",
        "style-new-product-launch-poster": "新品发布海报",
        "style-festival-promotion-poster": "节日促销海报",
        "style-social-seeding-poster": "朋友圈种草海报",
        "style-store-display-poster": "门店陈列海报",
    }
    assert {
        template_id: by_id[template_id]["title"] for template_id in expected
    } == expected
    assert all(
        by_id[template_id]["runtime_mode"] == "prompt_style" for template_id in expected
    )
    assert all(by_id[template_id]["type"] == "play" for template_id in expected)
    assert all(by_id[template_id]["prompt_template"] for template_id in expected)
    assert (
        "品牌名称：{品牌名称}"
        in by_id["style-product-selling-points-poster"]["prompt_template"]
    )
    assert (
        "产品名称：{产品名称}" in by_id["style-store-display-poster"]["prompt_template"]
    )
    assert (
        "【画面结构】"
        not in by_id["style-product-selling-points-poster"]["prompt_template"]
    )
    assert (
        by_id["style-product-selling-points-poster"]["prompt_template"]
        != by_id["style-product-selling-points-poster"]["description"]
    )
    assert all("【画面结构】" not in item["description"] for item in templates)
    assert all("【文字要求】" not in item["description"] for item in templates)
    assert all("【画面内容】" in item["prompt_template"] for item in templates)
    assert all("【文字内容】" in item["prompt_template"] for item in templates)
    assert (
        "突出产品核心利益点"
        in by_id["style-product-selling-points-poster"]["description"]
    )
    assert (
        "原料产地、采摘、筛选" in by_id["style-source-ingredient-poster"]["description"]
    )
    assert "步骤编号或流程线" in by_id["style-process-flow-poster"]["description"]
    assert (
        "渠道政策、供货能力" in by_id["style-channel-recruitment-poster"]["description"]
    )
    assert (
        "新品发布会、首发上市"
        in by_id["style-new-product-launch-poster"]["description"]
    )
    assert (
        "节日氛围、限时活动" in by_id["style-festival-promotion-poster"]["description"]
    )
    assert "真实生活方式场景" in by_id["style-social-seeding-poster"]["description"]
    assert (
        "门店货架、收银台、陈列端架"
        in by_id["style-store-display-poster"]["description"]
    )


async def test_default_style_templates_refresh_existing_builtin_metadata(tmp_path):
    """Changed built-in templates should refresh without losing usage stats."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)
    template_dir = tmp_path / "style_templates"
    template_dir.mkdir(parents=True)
    (template_dir / "style-brand-strength-poster.json").write_text(
        json.dumps(
            {
                "id": "style-brand-strength-poster",
                "title": "高端品牌实力海报",
                "type": "style",
                "provider": "internal",
                "model_family": "seedream-4.5",
                "cover_url": None,
                "category": "品牌海报",
                "tags": ["品牌"],
                "keywords": "旧关键词",
                "description": "旧版提示词",
                "commercial": True,
                "runtime_mode": "prompt_style",
                "effect_template_uuid": None,
                "effect_id": None,
                "use_count": 8,
                "favorite": True,
                "status": "enabled",
                "created_at": "2026-06-01T00:00:00+00:00",
                "updated_at": "2026-06-01T00:00:00+00:00",
                "last_used_at": "2026-06-24T00:00:00+00:00",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            listed = await client.get(
                "/api/aigc-studio/style-templates",
                params={"category": "海报场景", "q": "高端品牌实力海报"},
            )

    assert listed.status_code == 200
    templates = listed.json()["templates"]
    assert len(templates) == 1
    template = templates[0]
    assert template["category"] == "海报场景"
    assert template["type"] == "play"
    assert "高端、沉稳、工业质感、品牌大片感" in template["description"]
    assert "【画面结构】" not in template["description"]
    assert "品牌名称：{品牌名称}" in template["prompt_template"]
    assert template["use_count"] == 8
    assert template["favorite"] is True
    assert template["last_used_at"] == "2026-06-24T00:00:00+00:00"
    assert template["created_at"] == "2026-06-01T00:00:00+00:00"


async def test_user_style_templates_can_be_updated_and_deleted(tmp_path):
    """User-created prompt styles should be editable without making built-in styles mutable."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)
    payload = {
        "id": "style-custom-brand",
        "title": "旧品牌海报",
        "type": "style",
        "provider": "internal",
        "model_family": "seedream-4.5",
        "cover_url": None,
        "category": "我的风格",
        "tags": ["我的风格"],
        "keywords": "",
        "description": "旧提示词",
        "prompt_template": "旧模板：{旧字段}",
        "commercial": False,
        "runtime_mode": "prompt_style",
        "use_count": 0,
        "status": "enabled",
    }

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/aigc-studio/style-templates",
                json=payload,
            )
            assert created.status_code == 201

            updated = await client.put(
                "/api/aigc-studio/style-templates/style-custom-brand",
                json={
                    "title": "高端品牌海报",
                    "description": "只影响背景、光影、版式和氛围。",
                    "prompt_template": "品牌名称：{品牌名称}\n主标题：{主标题}",
                    "visual_dna": [
                        {
                            "element_id": "lighting.cinematic_contrast",
                            "weight": 0.85,
                        },
                        {
                            "element_id": "composition.centered_hero",
                            "weight": 0.75,
                        },
                    ],
                    "category": "我的风格",
                    "tags": ["我的风格"],
                    "model_family": "seedream-4.5",
                    "runtime_mode": "prompt_style",
                },
            )
            assert updated.status_code == 200
            assert updated.json()["title"] == "高端品牌海报"
            assert updated.json()["description"] == "只影响背景、光影、版式和氛围。"
            assert (
                updated.json()["prompt_template"]
                == "品牌名称：{品牌名称}\n主标题：{主标题}"
            )
            assert updated.json()["visual_dna"] == [
                {
                    "element_id": "lighting.cinematic_contrast",
                    "weight": 0.85,
                    "note": "",
                },
                {
                    "element_id": "composition.centered_hero",
                    "weight": 0.75,
                    "note": "",
                },
            ]

            builtin_delete = await client.delete(
                "/api/aigc-studio/style-templates/style-cgv2",
            )
            assert builtin_delete.status_code == 403

            deleted = await client.delete(
                "/api/aigc-studio/style-templates/style-custom-brand",
            )
            assert deleted.status_code == 204

            listed = await client.get(
                "/api/aigc-studio/style-templates",
                params={"q": "高端品牌海报"},
            )
            assert listed.status_code == 200
            assert listed.json()["templates"] == []


async def test_non_admin_cannot_update_builtin_style_templates(tmp_path):
    """System templates should remain read-only for ordinary users."""
    app = make_role_app(tmp_path, "user")
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            updated = await client.put(
                "/api/aigc-studio/style-templates/style-brand-strength-poster",
                json={
                    "title": "普通用户改系统模板",
                    "description": "普通用户不应该可以改系统模板。",
                    "category": "海报场景",
                    "tags": ["海报场景"],
                },
            )
            deleted = await client.delete(
                "/api/aigc-studio/style-templates/style-brand-strength-poster",
            )

    assert updated.status_code == 403
    assert deleted.status_code == 403


async def test_admin_can_update_builtin_prompt_style_templates(tmp_path):
    """Admins should be able to maintain built-in prompt-style templates."""
    app = make_role_app(tmp_path, "admin")
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            updated = await client.put(
                "/api/aigc-studio/style-templates/style-brand-strength-poster",
                json={
                    "title": "高端品牌实力海报 V2",
                    "description": "管理员新版提示词，强调品牌实力和产品前景。",
                    "prompt_template": "品牌名称：{品牌名称}\n主标题：{主标题}",
                    "category": "海报场景",
                    "tags": ["海报场景", "商用"],
                    "keywords": "品牌实力, 工厂, 产品背书",
                    "runtime_mode": "prompt_style",
                    "status": "enabled",
                },
            )

    assert updated.status_code == 200
    template = updated.json()
    assert template["id"] == "style-brand-strength-poster"
    assert template["title"] == "高端品牌实力海报 V2"
    assert template["description"] == "管理员新版提示词，强调品牌实力和产品前景。"
    assert template["prompt_template"] == "品牌名称：{品牌名称}\n主标题：{主标题}"
    assert template["category"] == "海报场景"
    assert template["tags"] == ["海报场景", "商用"]
    assert template["keywords"] == "品牌实力, 工厂, 产品背书"
    assert template["provider"] == "internal"
    assert template["runtime_mode"] == "prompt_style"


async def test_admin_builtin_style_template_cover_survives_default_refresh(tmp_path):
    """Admin-set built-in template covers should still appear after defaults refresh."""
    app = make_role_app(tmp_path, "admin")
    transport = ASGITransport(app=app)
    cover_url = "/api/user/aigc-studio/assets/asset-cover/file"

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            updated = await client.put(
                "/api/aigc-studio/style-templates/style-brand-strength-poster",
                json={
                    "title": "高端品牌实力海报",
                    "description": "管理员新版提示词，强调品牌实力和产品前景。",
                    "prompt_template": "管理员模板：{品牌名称}",
                    "category": "海报场景",
                    "tags": ["海报场景", "商用"],
                    "cover_url": cover_url,
                    "runtime_mode": "prompt_style",
                    "status": "enabled",
                },
            )
            listed = await client.get(
                "/api/aigc-studio/style-templates",
                params={"q": "高端品牌实力海报"},
            )

    assert updated.status_code == 200
    assert updated.json()["cover_url"] == cover_url
    assert listed.status_code == 200
    templates_by_id = {
        template["id"]: template for template in listed.json()["templates"]
    }
    assert templates_by_id["style-brand-strength-poster"]["cover_url"] == cover_url
    assert (
        templates_by_id["style-brand-strength-poster"]["prompt_template"]
        == "管理员模板：{品牌名称}"
    )


async def test_admin_delete_builtin_style_template_disables_it(tmp_path):
    """Deleting a built-in template should hide it without letting defaults recreate it."""
    app = make_role_app(tmp_path, "admin")
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            deleted = await client.delete(
                "/api/aigc-studio/style-templates/style-product-selling-points-poster",
            )
            listed = await client.get(
                "/api/aigc-studio/style-templates",
                params={"category": "海报场景"},
            )

        disabled_payload = json.loads(
            (
                tmp_path
                / "style_templates"
                / "style-product-selling-points-poster.json"
            ).read_text("utf-8")
        )

    assert deleted.status_code == 204
    assert listed.status_code == 200
    ids = {template["id"] for template in listed.json()["templates"]}
    assert "style-product-selling-points-poster" not in ids
    assert disabled_payload["status"] == "disabled"


async def test_canvas_crud_persists_nodes_edges_and_viewport(tmp_path):
    """A canvas should roundtrip through the JSON-backed store."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)
    payload = {
        "name": "Launch film board",
        "nodes": [
            {
                "id": "prompt-1",
                "type": "prompt",
                "position": {"x": 120, "y": 80},
                "data": {"text": "A cinematic product shot"},
            }
        ],
        "edges": [],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post("/api/aigc-studio/canvases", json=payload)
            assert created.status_code == 201
            canvas_id = created.json()["id"]

            fetched = await client.get(f"/api/aigc-studio/canvases/{canvas_id}")
            assert fetched.status_code == 200
            assert fetched.json()["name"] == "Launch film board"
            assert (
                fetched.json()["nodes"][0]["data"]["text"]
                == payload["nodes"][0]["data"]["text"]
            )

            updated = await client.put(
                f"/api/aigc-studio/canvases/{canvas_id}",
                json={
                    **payload,
                    "name": "Updated board",
                    "edges": [{"id": "e1", "source": "prompt-1", "target": "image-1"}],
                },
            )
            assert updated.status_code == 200
            assert updated.json()["name"] == "Updated board"
            assert updated.json()["edges"][0]["target"] == "image-1"


async def test_aigc_canvas_job_and_asset_routes_are_user_isolated(tmp_path):
    """AIGC projects and their derived records should be scoped to the current user."""
    app = make_user_switching_app(tmp_path)
    transport = ASGITransport(app=app)
    user_1 = {"x-test-user-id": "101"}
    user_2 = {"x-test-user-id": "202"}
    canvas_payload = {
        "name": "Private launch board",
        "nodes": [
            {
                "id": "image-1",
                "type": "image_generate",
                "position": {"x": 120, "y": 80},
                "data": {"text": "A private perfume bottle"},
            }
        ],
        "edges": [],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/aigc-studio/canvases",
                json=canvas_payload,
                headers=user_1,
            )
            assert created.status_code == 201
            canvas_id = created.json()["id"]

            upload = await client.post(
                "/api/aigc-studio/assets/upload",
                files={"file": ("private.png", b"private", "image/png")},
                headers=user_1,
            )
            assert upload.status_code == 201
            asset_id = upload.json()["id"]

            job = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas_id,
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "openai",
                    "model_id": "gpt-image-2",
                    "inputs": {"prompt": "A private perfume bottle"},
                },
                headers=user_1,
            )
            assert job.status_code == 202
            job_id = job.json()["id"]

            assert (
                await client.get(
                    f"/api/aigc-studio/canvases/{canvas_id}",
                    headers=user_1,
                )
            ).status_code == 200
            assert (
                await client.get(f"/api/aigc-studio/jobs/{job_id}", headers=user_1)
            ).status_code == 200
            assert (
                await client.get(
                    f"/api/aigc-studio/assets/{asset_id}/file",
                    headers=user_1,
                )
            ).status_code == 200

            assert (
                await client.get(
                    "/api/aigc-studio/canvases",
                    headers=user_2,
                )
            ).json()["canvases"] == []
            assert (
                await client.get(
                    f"/api/aigc-studio/canvases/{canvas_id}",
                    headers=user_2,
                )
            ).status_code == 404
            assert (await client.get("/api/aigc-studio/jobs", headers=user_2)).json()[
                "jobs"
            ] == []
            assert (
                await client.get(f"/api/aigc-studio/jobs/{job_id}", headers=user_2)
            ).status_code == 404
            assert (await client.get("/api/aigc-studio/assets", headers=user_2)).json()[
                "assets"
            ] == []
            assert (
                await client.get(
                    f"/api/aigc-studio/assets/{asset_id}/file",
                    headers=user_2,
                )
            ).status_code == 404
            forbidden_job = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas_id,
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "openai",
                    "model_id": "gpt-image-2",
                },
                headers=user_2,
            )
            assert forbidden_job.status_code == 404


async def test_admin_can_claim_legacy_ownerless_aigc_canvas(tmp_path):
    """Ownerless legacy canvases should not disappear after user isolation deploys."""
    app = make_user_switching_app(tmp_path)
    transport = ASGITransport(app=app)
    legacy = aigc_studio.Canvas(
        id="legacy-canvas",
        name="Legacy launch board",
        nodes=[
            {
                "id": "prompt-1",
                "type": "prompt",
                "position": {"x": 0, "y": 0},
                "data": {"text": "Legacy prompt"},
            }
        ],
        edges=[],
        created_at="2026-06-30T00:00:00Z",
        updated_at="2026-06-30T00:00:00Z",
        meta={},
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        aigc_studio._write_json(aigc_studio._json_path("canvases", legacy.id), legacy)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            user_list = await client.get(
                "/api/aigc-studio/canvases",
                headers={"x-test-user-id": "2", "x-test-role": "user"},
            )
            admin_list = await client.get(
                "/api/aigc-studio/canvases",
                headers={"x-test-user-id": "1", "x-test-role": "admin"},
            )
            admin_update = await client.put(
                f"/api/aigc-studio/canvases/{legacy.id}",
                headers={"x-test-user-id": "1", "x-test-role": "admin"},
                json={
                    "name": "Legacy launch board",
                    "nodes": [item.model_dump() for item in legacy.nodes],
                    "edges": [],
                    "viewport": legacy.viewport.model_dump(),
                    "meta": {},
                },
            )

            user_after_claim = await client.get(
                "/api/aigc-studio/canvases",
                headers={"x-test-user-id": "2", "x-test-role": "user"},
            )

    assert user_list.status_code == 200
    assert user_list.json()["canvases"] == []
    assert admin_list.status_code == 200
    assert [item["id"] for item in admin_list.json()["canvases"]] == [legacy.id]
    assert admin_update.status_code == 200
    assert admin_update.json()["meta"]["owner_user_id"] == "1"
    assert user_after_claim.status_code == 200
    assert user_after_claim.json()["canvases"] == []


async def test_admin_can_recover_legacy_ownerless_aigc_asset(tmp_path):
    """Ownerless standalone assets should be recoverable without exposing them to users."""
    app = make_user_switching_app(tmp_path)
    transport = ASGITransport(app=app)
    studio_root = tmp_path / "studio"
    asset_file = studio_root / "asset_files" / "legacy-reference.png"
    asset_file.parent.mkdir(parents=True, exist_ok=True)
    asset_file.write_bytes(b"legacy-reference")
    legacy_asset = aigc_studio.AigcAsset(
        id="legacy-asset",
        kind="image",
        name="legacy-reference.png",
        path=str(asset_file),
        url="/api/aigc-studio/assets/legacy-asset/file",
        mime_type="image/png",
        created_at="2026-06-30T00:00:00Z",
        meta={},
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", studio_root):
        aigc_studio._write_json(
            aigc_studio._json_path("assets", legacy_asset.id),
            legacy_asset,
        )
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            user_list = await client.get(
                "/api/aigc-studio/assets",
                headers={"x-test-user-id": "2", "x-test-role": "user"},
            )
            user_file = await client.get(
                f"/api/aigc-studio/assets/{legacy_asset.id}/file",
                headers={"x-test-user-id": "2", "x-test-role": "user"},
            )
            admin_list = await client.get(
                "/api/aigc-studio/assets",
                headers={"x-test-user-id": "1", "x-test-role": "admin"},
            )
            admin_file = await client.get(
                f"/api/aigc-studio/assets/{legacy_asset.id}/file",
                headers={"x-test-user-id": "1", "x-test-role": "admin"},
            )

    assert user_list.status_code == 200
    assert user_list.json()["assets"] == []
    assert user_file.status_code == 404
    assert admin_list.status_code == 200
    assert [item["id"] for item in admin_list.json()["assets"]] == [legacy_asset.id]
    assert admin_file.status_code == 200
    assert admin_file.content == b"legacy-reference"


async def test_submit_job_records_status_for_canvas_node(tmp_path):
    """Submitting a generation node should create a queryable job record."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)
    canvas_payload = {
        "name": "Launch film board",
        "nodes": [
            {
                "id": "image-1",
                "type": "image_generate",
                "position": {"x": 120, "y": 80},
                "data": {"text": "A glossy perfume bottle"},
            }
        ],
        "edges": [],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post("/api/aigc-studio/canvases", json=canvas_payload)
            assert canvas.status_code == 201

            resp = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "openai",
                    "model_id": "gpt-image-2",
                    "inputs": {"prompt": "A glossy perfume bottle"},
                    "parameters": {"size": "1024x1024"},
                },
            )

            assert resp.status_code == 202
            job = resp.json()
            assert job["status"] == "queued"
            assert job["capability"] == "text_to_image"

            fetched = await client.get(f"/api/aigc-studio/jobs/{job['id']}")
            assert fetched.status_code == 200
            assert fetched.json()["node_id"] == "image-1"


async def test_aigc_job_status_changes_publish_runtime_events(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)
    bus = MemoryRuntimeEventBus(max_events=20, max_age_seconds=60)
    monkeypatch.setattr(
        aigc_studio, "get_runtime_event_bus", lambda: bus, raising=False
    )
    canvas_payload = {
        "name": "Launch film board",
        "nodes": [
            {
                "id": "image-1",
                "type": "image_generate",
                "position": {"x": 120, "y": 80},
                "data": {"text": "A glossy perfume bottle"},
            }
        ],
        "edges": [],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post("/api/aigc-studio/canvases", json=canvas_payload)
            assert canvas.status_code == 201

            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "openai",
                    "model_id": "gpt-image-2",
                    "inputs": {"prompt": "A glossy perfume bottle"},
                },
            )
            assert created.status_code == 202
            job_id = created.json()["id"]

            cancelled = await client.post(f"/api/aigc-studio/jobs/{job_id}/cancel")
            assert cancelled.status_code == 200

    events = await bus.replay(session_id=None, since_id=None)

    assert [event.type for event in events] == [
        "aigc.job.updated",
        "aigc.job.updated",
    ]
    assert [event.status for event in events] == ["queued", "cancelled"]
    assert {event.job_id for event in events} == {job_id}
    assert events[-1].payload["canvas_id"] == canvas.json()["id"]


async def test_submit_job_rejects_missing_canvas_without_creating_job(tmp_path):
    """A job should not be queued for a canvas that does not exist."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": "missing-canvas",
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "openai",
                    "model_id": "gpt-image-2",
                },
            )

            assert resp.status_code == 404

            jobs = await client.get("/api/aigc-studio/jobs")
            assert jobs.status_code == 200
            assert jobs.json()["jobs"] == []


async def test_submit_job_rejects_missing_node_without_creating_job(tmp_path):
    """A job should not be queued for a node outside the target canvas."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Empty board",
                    "nodes": [],
                    "edges": [],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            )

            resp = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "openai",
                    "model_id": "gpt-image-2",
                },
            )

            assert resp.status_code == 400
            assert "node" in resp.json()["detail"].lower()

            jobs = await client.get("/api/aigc-studio/jobs")
            assert jobs.json()["jobs"] == []


async def test_submit_job_rejects_unsupported_model_capability(tmp_path):
    """Selected provider/model must advertise the requested capability."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Launch film board",
                    "nodes": [
                        {
                            "id": "video-1",
                            "type": "video_generate",
                            "position": {"x": 120, "y": 80},
                            "data": {"text": "A moody launch film"},
                        }
                    ],
                    "edges": [],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            )

            resp = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "video-1",
                    "capability": "text_to_video",
                    "provider_id": "openai",
                    "model_id": "gpt-image-2",
                },
            )

            assert resp.status_code == 400
            assert "capability" in resp.json()["detail"].lower()

            jobs = await client.get("/api/aigc-studio/jobs")
            assert jobs.json()["jobs"] == []


async def test_cancel_and_retry_job_keep_queryable_history(tmp_path):
    """Cancelled jobs should stay in history and retry should create a new queued job."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Launch film board",
                    "nodes": [
                        {
                            "id": "image-1",
                            "type": "image_generate",
                            "position": {"x": 120, "y": 80},
                            "data": {"text": "A glossy perfume bottle"},
                        }
                    ],
                    "edges": [],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "openai",
                    "model_id": "gpt-image-2",
                },
            )

            cancelled = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/cancel",
            )
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "cancelled"

            retry = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/retry",
            )
            assert retry.status_code == 202
            assert retry.json()["status"] == "queued"
            assert retry.json()["id"] != created.json()["id"]
            assert retry.json()["canvas_id"] == canvas.json()["id"]

            jobs = await client.get(
                f"/api/aigc-studio/jobs?canvas_id={canvas.json()['id']}",
            )
            assert [job["status"] for job in jobs.json()["jobs"]] == [
                "queued",
                "cancelled",
            ]


async def test_delete_canvas_removes_canvas_jobs_but_keeps_assets(tmp_path):
    """Deleting a canvas should not touch uploaded asset records."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Launch film board",
                    "nodes": [
                        {
                            "id": "image-1",
                            "type": "image_generate",
                            "position": {"x": 120, "y": 80},
                            "data": {},
                        }
                    ],
                    "edges": [],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            )
            await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "openai",
                    "model_id": "gpt-image-2",
                },
            )
            upload = await client.post(
                "/api/aigc-studio/assets/upload",
                files={"file": ("reference.png", b"png-bytes", "image/png")},
            )
            assert upload.status_code == 201

            deleted = await client.delete(
                f"/api/aigc-studio/canvases/{canvas.json()['id']}",
            )
            assert deleted.status_code == 204

            assert (
                await client.get(f"/api/aigc-studio/canvases/{canvas.json()['id']}")
            ).status_code == 404
            assert (await client.get("/api/aigc-studio/jobs")).json()["jobs"] == []
            assert (
                len((await client.get("/api/aigc-studio/assets")).json()["assets"]) == 1
            )


async def test_run_job_creates_workspace_artifact_and_asset(tmp_path):
    """Running a job should persist reusable outputs without touching other workspace files."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)
    workspace = tmp_path / "workspace"
    existing_file = workspace / "existing.md"
    existing_file.parent.mkdir(parents=True, exist_ok=True)
    existing_file.write_text("keep me", encoding="utf-8")

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Launch film board",
                    "nodes": [
                        {
                            "id": "image-1",
                            "type": "image_generate",
                            "position": {"x": 120, "y": 80},
                            "data": {"text": "A glossy perfume bottle"},
                        }
                    ],
                    "edges": [],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "stub-aigc",
                    "model_id": "stub-image",
                    "inputs": {"prompt": "A glossy perfume bottle"},
                    "parameters": {"size": "1024x1024"},
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

            assert ran.status_code == 200
            job = ran.json()
            assert job["status"] == "succeeded"
            assert job["outputs"][0]["kind"] == "image"
            assert job["outputs"][0]["path"].startswith("aigc_studio/")
            assert job["outputs"][0]["url"].endswith(
                f"/api/aigc-studio/assets/{job['outputs'][0]['id']}/file",
            )
            artifact_path = workspace / job["outputs"][0]["path"]
            assert artifact_path.exists()
            assert "A glossy perfume bottle" in artifact_path.read_text("utf-8")
            assert existing_file.read_text("utf-8") == "keep me"

            asset_file = await client.get(job["outputs"][0]["url"])
            assert asset_file.status_code == 200
            assert asset_file.headers["content-type"].startswith("image/svg+xml")
            assert "A glossy perfume bottle" in asset_file.text

            assets = await client.get("/api/aigc-studio/assets")
            assert assets.status_code == 200
            assert assets.json()["assets"][0]["id"] == job["outputs"][0]["id"]


async def test_run_job_settles_aigc_billing_before_success_projection(
    tmp_path,
    monkeypatch,
):
    events = []

    class Reservation:
        def settle_success(self, *, outputs, supplier_reference):
            events.append(("settled", len(outputs), supplier_reference))

        def settle_failure(self, **_kwargs):
            events.append(("released",))

    def reserve(job, owner):
        events.append(("reserved", job.id, owner))
        return Reservation()

    monkeypatch.setattr(
        "qwenpaw.app.aigc.billing.reserve_aigc_job",
        reserve,
    )
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Billing board",
                    "nodes": [
                        {
                            "id": "image-1",
                            "type": "image_generate",
                            "position": {"x": 0, "y": 0},
                            "data": {},
                        },
                    ],
                    "edges": [],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "stub-aigc",
                    "model_id": "stub-image",
                    "inputs": {"prompt": "Billing integration"},
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    assert ran.json()["status"] == "succeeded"
    assert events[0] == ("reserved", created.json()["id"], "0")
    assert events[1] == ("settled", 1, created.json()["id"])


async def test_export_long_image_creates_full_image_and_upload_slices(tmp_path):
    """Long-image export should compose upstream text and image nodes into assets."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            upload = await client.post(
                "/api/aigc-studio/assets/upload",
                files={"file": ("scene.png", png_bytes, "image/png")},
            )
            assert upload.status_code == 201
            source_asset = upload.json()

            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "小说推文长图",
                    "nodes": [
                        {
                            "id": "text-1",
                            "type": "prompt",
                            "position": {"x": 80, "y": 80},
                            "data": {
                                "title": "小说推文",
                                "text": "她推开门，看见满城灯火。\n\n下一秒，命运开始反转。",
                            },
                        },
                        {
                            "id": "image-1",
                            "type": "image_generate",
                            "position": {"x": 520, "y": 80},
                            "data": {
                                "title": "剧情插图",
                                "imageState": "generated",
                                "outputs": [source_asset],
                            },
                        },
                        {
                            "id": "long-1",
                            "type": "long_image_export",
                            "position": {"x": 960, "y": 80},
                            "data": {"title": "公众号长图", "sliceHeight": 520},
                        },
                    ],
                    "edges": [
                        {
                            "id": "edge-text-long",
                            "source": "text-1",
                            "target": "long-1",
                        },
                        {
                            "id": "edge-image-long",
                            "source": "image-1",
                            "target": "long-1",
                        },
                    ],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            )
            assert canvas.status_code == 201

            exported = await client.post(
                "/api/aigc-studio/long-image-exports",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "long-1",
                    "width": 750,
                    "slice_height": 520,
                },
            )

            assert exported.status_code == 201
            payload = exported.json()
            assert payload["full_asset"]["kind"] == "image"
            assert payload["full_asset"]["mime_type"] == "image/png"
            assert payload["slice_assets"]
            assert payload["section_count"] >= 2
            assert payload["height"] > 520
            assert payload["slice_assets"][0]["name"].startswith("long-1-slice-")
            assert payload["full_asset"]["meta"]["adapter"] == "long_image_export"
            assert payload["full_asset"]["meta"]["canvas_id"] == canvas.json()["id"]

            jobs = await client.get(
                "/api/aigc-studio/jobs",
                params={"canvas_id": canvas.json()["id"]},
            )
            assert jobs.status_code == 200
            persisted = jobs.json()["jobs"]
            assert len(persisted) == 1
            assert persisted[0]["node_id"] == "long-1"
            assert persisted[0]["status"] == "succeeded"
            assert persisted[0]["outputs"][0]["id"] == payload["full_asset"]["id"]

            slice_file = await client.get(payload["slice_assets"][0]["url"])
            assert slice_file.status_code == 200
            assert slice_file.headers["content-type"].startswith("image/png")
            assert slice_file.content.startswith(b"\x89PNG")


def test_long_image_font_loader_prefers_docker_cjk_font(monkeypatch):
    """Long-image text rendering should use the CJK font installed in Docker."""
    requested: list[tuple[str, int]] = []

    class FakePath:
        def __init__(self, value):
            self.value = str(value)

        def exists(self):
            return self.value == "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"

    class FakeImageFont:
        @staticmethod
        def truetype(path, size):
            requested.append((str(path), size))
            return SimpleNamespace(path=str(path), size=size)

        @staticmethod
        def load_default():
            raise AssertionError("should not fall back to default bitmap font")

    monkeypatch.setattr(aigc_studio, "Path", FakePath)
    monkeypatch.setattr("PIL.ImageFont.truetype", FakeImageFont.truetype)
    monkeypatch.setattr("PIL.ImageFont.load_default", FakeImageFont.load_default)

    font = aigc_studio._load_long_image_font(28)

    assert font.path == "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
    assert requested == [("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 28)]


async def test_run_job_background_mode_returns_before_provider_finishes(
    tmp_path,
    monkeypatch,
):
    """Background run mode should not hold the HTTP request open for generation."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)
    provider_started = asyncio.Event()
    provider_release = asyncio.Event()

    async def slow_execute_job(request, job, execution=None):
        provider_started.set()
        await provider_release.wait()
        return [
            aigc_studio.AigcAsset(
                id="asset-background",
                kind="image",
                name="background.svg",
                path="aigc_studio/generated/background.svg",
                url="/api/aigc-studio/assets/asset-background/file",
                mime_type="image/svg+xml",
                created_at=aigc_studio._now(),
            )
        ]

    monkeypatch.setattr(aigc_studio, "_execute_job", slow_execute_job)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Background run board",
                    "nodes": [
                        {
                            "id": "image-1",
                            "type": "image_generate",
                            "position": {"x": 120, "y": 80},
                            "data": {"text": "A slow product poster"},
                        }
                    ],
                    "edges": [],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "stub-aigc",
                    "model_id": "stub-image",
                    "inputs": {"prompt": "A slow product poster"},
                },
            )
            job_id = created.json()["id"]

            started = await client.post(
                f"/api/aigc-studio/jobs/{job_id}/run?background=true",
            )

            assert started.status_code == 200
            assert started.json()["status"] == "running"
            await asyncio.wait_for(provider_started.wait(), timeout=1)
            stored = await client.get(f"/api/aigc-studio/jobs/{job_id}")
            assert stored.json()["status"] == "running"

            provider_release.set()
            for _ in range(50):
                finished = await client.get(f"/api/aigc-studio/jobs/{job_id}")
                if finished.json()["status"] == "succeeded":
                    break
                await asyncio.sleep(0.01)

            assert finished.json()["status"] == "succeeded"
            assert finished.json()["outputs"][0]["id"] == "asset-background"


@pytest.mark.parametrize("configured_ordinary_llm", [False, True])
async def test_run_storyboard_job_uses_chat_model_and_saves_text_meta(
    tmp_path, configured_ordinary_llm,
):
    """Text nodes should run through a chat model and keep text in asset metadata."""
    app = make_text_app(tmp_path)
    transport = ASGITransport(app=app)
    manager = app.state.provider_manager

    if configured_ordinary_llm:
        from qwenpaw.app.storage.engine import get_app_engine

        manager.provider.models[0].aigc_capabilities = []
        selected = {"provider_id": "text-provider", "model_id": "gvlm-3-1"}
        AigcModelPolicyRepository(get_app_engine()).replace(
            "text", None, [selected], selected, 7,
        )

    inventory = await aigc_studio.list_capabilities(SimpleNamespace(app=app))
    text_models = [
        item for item in inventory.capabilities if item.capability == "storyboard"
    ]
    assert [(item.provider_id, item.model_id) for item in text_models] == [
        ("text-provider", "gvlm-3-1"),
    ]

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Storyboard board",
                    "nodes": [
                        {
                            "id": "prompt-1",
                            "type": "prompt",
                            "position": {"x": 120, "y": 80},
                            "data": {"composerText": "写一个屋顶机器人故事"},
                        }
                    ],
                    "edges": [],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "prompt-1",
                    "capability": "storyboard",
                    "provider_id": "text-provider",
                    "model_id": "gvlm-3-1",
                    "inputs": {"prompt": "写一个屋顶机器人故事"},
                    "parameters": {"textMode": "generated"},
                },
            )

            assert created.status_code == 202, created.text
            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

            assert ran.status_code == 200
            job = ran.json()
            assert job["status"] == "succeeded"
            assert job["outputs"][0]["kind"] == "file"
            assert job["outputs"][0]["mime_type"] == "text/plain"
            assert job["outputs"][0]["meta"]["text"] == "生成后的屋顶机器人故事"
            assert job["outputs"][0]["meta"]["adapter"] == "chat_model"

            artifact_path = tmp_path / "workspace" / job["outputs"][0]["path"]
            assert artifact_path.read_text("utf-8") == "生成后的屋顶机器人故事"
            assert "写一个屋顶机器人故事" in json.dumps(
                manager.provider.chat_model.calls[0],
                ensure_ascii=False,
            )


async def test_run_storyboard_script_job_instructs_json_shot_output(tmp_path):
    """Storyboard script jobs should ask the model for parseable shot JSON."""
    app = make_text_app(tmp_path)
    transport = ASGITransport(app=app)
    manager = app.state.provider_manager

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Structured storyboard board",
                    "nodes": [
                        {
                            "id": "script-1",
                            "type": "script_generate",
                            "position": {"x": 120, "y": 80},
                            "data": {"scriptPrompt": "把瓦房院子的童年记忆拆成分镜"},
                        }
                    ],
                    "edges": [],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "script-1",
                    "capability": "storyboard",
                    "provider_id": "text-provider",
                    "model_id": "gvlm-3-1",
                    "inputs": {"prompt": "小时候我住在瓦房的大院里，院子里有梧桐树"},
                    "parameters": {
                        "textMode": "storyboard_script",
                        "outputFormat": "storyboard_shots_json",
                    },
                },
            )

            await client.post(f"/api/aigc-studio/jobs/{created.json()['id']}/run")

            messages = json.dumps(
                manager.provider.chat_model.calls[0],
                ensure_ascii=False,
            )
            assert "JSON" in messages
            assert "shots" in messages
            assert "imageDescription" in messages
            assert "finalPrompt" in messages
            assert "不要输出 Markdown" in messages


async def test_run_storyboard_job_consumes_streaming_chat_response(tmp_path):
    """Streaming chat models should not be treated as empty text."""
    app = make_text_app(tmp_path, stream=True)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Streaming storyboard board",
                    "nodes": [
                        {
                            "id": "prompt-1",
                            "type": "prompt",
                            "position": {"x": 120, "y": 80},
                            "data": {"composerText": "你好"},
                        }
                    ],
                    "edges": [],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "prompt-1",
                    "capability": "storyboard",
                    "provider_id": "text-provider",
                    "model_id": "gvlm-3-1",
                    "inputs": {"prompt": "你好"},
                    "parameters": {"textMode": "generated"},
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

            assert ran.status_code == 200
            job = ran.json()
            assert job["status"] == "succeeded"
            assert job["outputs"][0]["meta"]["text"] == "生成后的屋顶机器人故事"


async def test_run_image_to_prompt_fails_without_visual_text_model(tmp_path):
    """Image reverse prompting needs a multimodal text model instead of a silent fallback."""
    app = make_text_app(tmp_path, supports_image=False)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Image prompt board",
                    "nodes": [
                        {
                            "id": "prompt-1",
                            "type": "prompt",
                            "position": {"x": 120, "y": 80},
                            "data": {"textMode": "image_to_prompt"},
                        }
                    ],
                    "edges": [],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "prompt-1",
                    "capability": "storyboard",
                    "provider_id": "text-provider",
                    "model_id": "gvlm-3-1",
                    "inputs": {
                        "prompt": "把图片反推成提示词",
                        "reference_nodes": [
                            {
                                "node_id": "image-1",
                                "preview_url": "/api/aigc-studio/assets/ref/file",
                            }
                        ],
                    },
                    "parameters": {"textMode": "image_to_prompt"},
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

            assert ran.status_code == 200
            assert ran.json()["status"] == "failed"
            assert "does not support image understanding" in ran.json()["error"]


async def test_run_text_media_jobs_use_configured_generic_adapter(tmp_path):
    """Video stays executable while removed independent audio jobs are rejected."""
    app = make_media_adapter_app(tmp_path)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            capabilities = await client.get("/api/aigc-studio/capabilities")
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Media board",
                    "nodes": [
                        {
                            "id": "video-1",
                            "type": "video_generate",
                            "position": {"x": 120, "y": 80},
                            "data": {"text": "生成一支品牌视频"},
                        },
                        {
                            "id": "audio-1",
                            "type": "audio_generate",
                            "position": {"x": 520, "y": 80},
                            "data": {"text": "生成一段品牌音乐"},
                        },
                    ],
                    "edges": [],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            )

            video = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "video-1",
                    "capability": "text_to_video",
                    "provider_id": "media-stub",
                    "model_id": "stub-video",
                    "inputs": {"prompt": "生成一支品牌视频"},
                },
            )
            audio = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "audio-1",
                    "capability": "text_to_audio",
                    "provider_id": "media-stub",
                    "model_id": "stub-audio",
                    "inputs": {"prompt": "生成一段品牌音乐"},
                },
            )

            ran_video = await client.post(
                f"/api/aigc-studio/jobs/{video.json()['id']}/run",
            )

    assert ran_video.status_code == 200
    assert ran_video.json()["status"] == "succeeded"
    assert ran_video.json()["outputs"][0]["kind"] == "video"
    assert ran_video.json()["outputs"][0]["meta"]["adapter"] == "artifact_stub"

    assert capabilities.status_code == 200
    assert not any(
        item["capability"] == "text_to_audio"
        for item in capabilities.json()["capabilities"]
    )
    assert audio.status_code == 400
    assert "Requested capability is not available" in audio.text


async def test_run_job_uploads_generated_asset_to_object_storage_without_local_file(
    tmp_path,
    monkeypatch,
):
    """When object storage is enabled, generated outputs should not consume ECS disk."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)
    workspace = tmp_path / "workspace"
    uploads: list[dict] = []
    downloads: list[str] = []

    class FakeObjectStorageClient:
        async def upload(self, *, relative_path: str, content, mime_type: str):
            body = content.encode("utf-8") if isinstance(content, str) else content
            uploads.append(
                {
                    "relative_path": relative_path,
                    "content": body,
                    "mime_type": mime_type,
                }
            )
            return {
                "provider": "aliyun_oss",
                "bucket": "qwenpaw-aigc",
                "endpoint": "https://oss-cn-hangzhou.aliyuncs.com",
                "object_key": f"aigc/generated/{relative_path}",
                "size": len(body),
            }

        async def download(self, object_key: str):
            downloads.append(object_key)
            return uploads[0]["content"], uploads[0]["mime_type"]

    fake_storage = FakeObjectStorageClient()
    monkeypatch.setattr(
        aigc_studio,
        "get_object_storage_client",
        lambda **_kwargs: fake_storage,
        raising=False,
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Cloud artifact board",
                    "nodes": [
                        {
                            "id": "image-1",
                            "type": "image_generate",
                            "position": {"x": 120, "y": 80},
                            "data": {"text": "A cloud-backed perfume bottle"},
                        }
                    ],
                    "edges": [],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "stub-aigc",
                    "model_id": "stub-image",
                    "inputs": {"prompt": "A cloud-backed perfume bottle"},
                    "parameters": {"size": "1024x1024"},
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

            assert ran.status_code == 200
            job = ran.json()
            output = job["outputs"][0]
            assert output["path"].startswith("oss://qwenpaw-aigc/")
            assert output["url"].endswith(
                f"/api/aigc-studio/assets/{output['id']}/file",
            )
            assert output["meta"]["storage"]["provider"] == "aliyun_oss"
            assert uploads[0]["relative_path"].startswith("aigc_studio/")
            assert uploads[0]["mime_type"] == "image/svg+xml"
            assert b"A cloud-backed perfume bottle" in uploads[0]["content"]

            artifact_path = workspace / uploads[0]["relative_path"]
            assert not artifact_path.exists()

            asset_file = await client.get(output["url"])
            assert asset_file.status_code == 200
            assert asset_file.headers["content-type"].startswith("image/svg+xml")
            assert b"A cloud-backed perfume bottle" in asset_file.content
            assert downloads == [output["meta"]["storage"]["object_key"]]


async def test_upload_asset_uses_object_storage_when_enabled(
    tmp_path,
    monkeypatch,
):
    """Uploaded reference assets should use OSS so MXAPI can consume signed URLs."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)
    uploads: list[dict] = []
    downloads: list[str] = []

    class FakeObjectStorageClient:
        async def upload(self, *, relative_path: str, content, mime_type: str):
            body = content.encode("utf-8") if isinstance(content, str) else content
            uploads.append(
                {
                    "relative_path": relative_path,
                    "content": body,
                    "mime_type": mime_type,
                }
            )
            return {
                "provider": "aliyun_oss",
                "bucket": "qwenpaw-aigc",
                "endpoint": "https://oss-cn-hangzhou.aliyuncs.com",
                "object_key": f"aigc/generated/{relative_path}",
                "size": len(body),
            }

        async def download(self, object_key: str):
            downloads.append(object_key)
            return uploads[0]["content"], uploads[0]["mime_type"]

    fake_storage = FakeObjectStorageClient()
    monkeypatch.setattr(
        aigc_studio,
        "get_object_storage_client",
        lambda **_kwargs: fake_storage,
        raising=False,
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            uploaded = await client.post(
                "/api/aigc-studio/assets/upload",
                files={"file": ("reference.png", b"reference-bytes", "image/png")},
            )

            assert uploaded.status_code == 201
            asset = uploaded.json()
            assert asset["kind"] == "image"
            assert asset["path"].startswith("oss://qwenpaw-aigc/")
            assert asset["meta"]["storage"]["provider"] == "aliyun_oss"
            assert uploads == [
                {
                    "relative_path": f"aigc_studio/uploads/{asset['id']}.png",
                    "content": b"reference-bytes",
                    "mime_type": "image/png",
                }
            ]
            assert not (tmp_path / "studio" / "asset_files").exists()

            asset_file = await client.get(asset["url"])
            assert asset_file.status_code == 200
            assert asset_file.headers["content-type"].startswith("image/png")
            assert asset_file.content == b"reference-bytes"
            assert downloads == [asset["meta"]["storage"]["object_key"]]


async def test_cloud_asset_signed_url_uses_oss_without_proxying_bytes(
    tmp_path,
    monkeypatch,
):
    """Preview clients should be able to direct-read cloud assets from OSS/CDN."""
    signed_urls: list[str] = []
    downloads: list[str] = []

    class FakeObjectStorageClient:
        config = SimpleNamespace(signed_url_ttl_seconds=600)

        def signed_get_url(self, object_key: str, **_kwargs) -> str:
            signed_urls.append(object_key)
            return f"https://static.example.test/{object_key}?signature=1"

        async def download(self, object_key: str):
            downloads.append(object_key)
            return b"should-not-proxy", "image/png"

    monkeypatch.setattr(
        aigc_studio,
        "get_object_storage_client",
        lambda **_kwargs: FakeObjectStorageClient(),
        raising=False,
    )
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)
    asset = aigc_studio.AigcAsset(
        id="remote-asset",
        kind="image",
        name="remote.png",
        path="oss://qwenpaw-aigc/aigc/generated/result.png",
        url="/api/aigc-studio/assets/remote-asset/file",
        mime_type="image/png",
        created_at="2026-06-27T00:00:00Z",
        meta={
            "storage": {
                "provider": "aliyun_oss",
                "bucket": "qwenpaw-aigc",
                "object_key": "aigc/generated/result.png",
            }
        },
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        aigc_studio._write_json(aigc_studio._json_path("assets", asset.id), asset)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                f"/api/aigc-studio/assets/{asset.id}/signed-url"
            )

    assert response.status_code == 200
    assert response.json()["url"].startswith("https://static.example.test/")
    assert signed_urls == ["aigc/generated/result.png"]
    assert downloads == []


async def test_upload_asset_url_uses_public_base_url_for_https_deploy(
    tmp_path,
    monkeypatch,
):
    """Reverse-proxied deployments should not persist internal/http asset URLs."""
    monkeypatch.setenv("AIGC_STUDIO_PUBLIC_BASE_URL", "https://dclaw.deepmega.cn")

    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(
            transport=transport, base_url="http://internal"
        ) as client:
            uploaded = await client.post(
                "/api/aigc-studio/assets/upload",
                files={"file": ("reference.png", b"reference-bytes", "image/png")},
            )

    assert uploaded.status_code == 201
    asset = uploaded.json()
    assert asset["url"].startswith("https://dclaw.deepmega.cn/api/aigc-studio/assets/")
    assert asset["url"].endswith("/file")
    assert "http://internal" not in asset["url"]


async def test_direct_upload_to_object_storage_completes_asset_without_server_bytes(
    tmp_path,
    monkeypatch,
):
    """Large uploads should use browser-to-OSS PUT and only persist metadata here."""
    signed_puts: list[dict] = []
    uploads: list[dict] = []

    class FakeObjectStorageClient:
        config = SimpleNamespace(bucket="qwenpaw-aigc", endpoint="https://oss.test")

        def build_object_key(self, relative_path: str) -> str:
            return f"aigc/generated/{relative_path}"

        def signed_put_url(self, object_key: str, mime_type: str) -> str:
            signed_puts.append({"object_key": object_key, "mime_type": mime_type})
            return f"https://static.example.test/{object_key}?put-signature=1"

        async def upload(self, **_kwargs):
            uploads.append(_kwargs)
            raise AssertionError("direct upload should not proxy bytes")

    monkeypatch.setenv("AIGC_STUDIO_PUBLIC_ASSET_SECRET", "direct-upload-secret")
    aigc_studio._public_asset_signing_secret.cache_clear()
    monkeypatch.setattr(
        aigc_studio,
        "get_object_storage_client",
        lambda **_kwargs: FakeObjectStorageClient(),
        raising=False,
    )
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            prepared = await client.post(
                "/api/aigc-studio/assets/direct-upload",
                json={
                    "filename": "reference.png",
                    "mime_type": "image/png",
                    "size": 15,
                },
            )
            assert prepared.status_code == 200
            payload = prepared.json()

            completed = await client.post(
                "/api/aigc-studio/assets/direct-upload/complete",
                json={
                    "asset_id": payload["asset_id"],
                    "token": payload["token"],
                },
            )

    assert payload["method"] == "PUT"
    assert payload["headers"] == {"Content-Type": "image/png"}
    assert payload["upload_url"].startswith("https://static.example.test/")
    assert signed_puts == [
        {
            "object_key": f"aigc/generated/aigc_studio/uploads/{payload['asset_id']}.png",
            "mime_type": "image/png",
        }
    ]
    assert completed.status_code == 201
    asset = completed.json()
    assert asset["id"] == payload["asset_id"]
    assert asset["kind"] == "image"
    assert asset["name"] == "reference.png"
    assert asset["path"].startswith("oss://qwenpaw-aigc/")
    assert asset["url"].endswith(f"/api/aigc-studio/assets/{payload['asset_id']}/file")
    assert asset["meta"]["storage"]["object_key"].endswith(
        f"aigc_studio/uploads/{payload['asset_id']}.png"
    )
    assert uploads == []


async def test_asset_to_image_data_url_downloads_cloud_backed_asset(
    tmp_path,
    monkeypatch,
):
    """Cloud-backed generated images should remain usable as reference images."""
    downloads: list[str] = []

    class FakeObjectStorageClient:
        async def download(self, object_key: str):
            downloads.append(object_key)
            return b"remote-png", "image/png"

    monkeypatch.setattr(
        aigc_studio,
        "get_object_storage_client",
        lambda **_kwargs: FakeObjectStorageClient(),
        raising=False,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(aigc_artifact_root=tmp_path / "workspace")
        ),
        state=SimpleNamespace(user_id="0"),
    )
    asset = aigc_studio.AigcAsset(
        id="remote-asset",
        kind="image",
        name="remote.png",
        path="oss://qwenpaw-aigc/aigc/generated/result.png",
        url="/api/aigc-studio/assets/remote-asset/file",
        mime_type="image/png",
        created_at="2026-06-25T00:00:00Z",
        meta={
            "storage": {
                "provider": "aliyun_oss",
                "bucket": "qwenpaw-aigc",
                "object_key": "aigc/generated/result.png",
            }
        },
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        aigc_studio._write_json(aigc_studio._json_path("assets", asset.id), asset)

        data_url = await aigc_studio._asset_to_image_data_url(
            request,
            "remote-asset",
        )

    assert data_url == "data:image/png;base64,cmVtb3RlLXBuZw=="
    assert downloads == ["aigc/generated/result.png"]


async def test_run_unconfigured_aigc_model_fails_without_stub_artifact(tmp_path):
    """AIGC-capable models need an explicit runtime adapter before execution."""
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Image board",
                    "nodes": [
                        {
                            "id": "image-1",
                            "type": "image_generate",
                            "position": {"x": 120, "y": 80},
                            "data": {"text": "小女孩"},
                        }
                    ],
                    "edges": [],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "volcengine",
                    "model_id": "custom-image-model",
                    "inputs": {"prompt": "小女孩"},
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    job = ran.json()
    assert job["status"] == "failed"
    assert (
        "No AIGC adapter is configured for volcengine/custom-image-model"
        in job["error"]
    )
    assert job["outputs"] == []
    assert list((tmp_path / "workspace").glob("aigc_studio/**/*.svg")) == []


async def test_run_volcengine_seedream_job_saves_url_image(tmp_path, monkeypatch):
    """Volcengine Seedream should use the OpenAI-compatible image API and persist URL outputs."""
    app = make_seedream_app(tmp_path)
    transport = ASGITransport(app=app)
    client_args = {}
    calls = {}
    downloads = []

    class FakeImages:
        async def generate(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                data=[{"url": "https://cdn.example.test/seedream.png"}]
            )

    class FakeOpenAIClient:
        images = FakeImages()

    def fake_openai_client(api_key, base_url=None):
        client_args.update({"api_key": api_key, "base_url": base_url})
        return FakeOpenAIClient()

    async def fake_download(url):
        downloads.append(url)
        return b"seedream-png-bytes", "image/png"

    monkeypatch.setattr(aigc_studio, "_openai_client", fake_openai_client)
    monkeypatch.setattr(
        aigc_studio, "_download_remote_asset", fake_download, raising=False
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Image board",
                    "nodes": [
                        {
                            "id": "image-1",
                            "type": "image_generate",
                            "position": {"x": 120, "y": 80},
                            "data": {"text": "小女孩"},
                        }
                    ],
                    "edges": [],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "volcengine",
                    "model_id": "doubao-seedream-3-0-t2i",
                    "inputs": {"prompt": "小女孩"},
                    "parameters": {
                        "aspectRatio": "16:9",
                        "resolution": "2K",
                        "imageQuality": "standard",
                        "imageCount": 1,
                    },
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )
            updated_canvas = await client.get(
                f"/api/aigc-studio/canvases/{canvas.json()['id']}",
            )

    assert ran.status_code == 200
    job = ran.json()
    assert job["status"] == "succeeded"
    assert client_args == {
        "api_key": "ark-runtime-key",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
    }
    assert calls == {
        "model": "doubao-seedream-3-0-t2i",
        "prompt": "小女孩",
        "size": "2848x1600",
        "response_format": "url",
        "extra_body": {
            "watermark": True,
        },
    }
    assert downloads == ["https://cdn.example.test/seedream.png"]
    assert job["outputs"][0]["meta"]["adapter"] == "volcengine_seedream"
    assert job["outputs"][0]["meta"]["parameters"]["aspectRatio"] == "16:9"
    assert updated_canvas.json()["nodes"][0]["data"]["generatedAspectRatio"] == "16:9"
    artifact = tmp_path / "workspace" / job["outputs"][0]["path"]
    assert artifact.suffix == ".png"
    assert artifact.read_bytes() == b"seedream-png-bytes"


async def test_run_mxapi_gpt_image_job_polls_and_saves_url_image(
    tmp_path,
    monkeypatch,
):
    """MXAPI GPT Image 2 should submit an async task, poll it, and persist the result image."""
    app = make_mxapi_app(tmp_path)
    transport = ASGITransport(app=app)
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(
            self,
            payload: dict[str, object],
            *,
            content: bytes = b"",
            headers: dict[str, str] | None = None,
        ):
            self._payload = payload
            self.content = content
            self.headers = headers or {}

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            requests.append({"type": "client", "kwargs": kwargs})

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            requests.append({"type": "post", "url": url, "kwargs": kwargs})
            return FakeResponse({"code": 200, "data": {"task_id": "task-123"}})

        async def get(self, url, **kwargs):
            requests.append({"type": "get", "url": url, "kwargs": kwargs})
            if "gpt-image/task" in url:
                return FakeResponse(
                    {
                        "data": {
                            "status": "completed",
                            "result": {
                                "images": ["https://cdn.example.test/mxapi.png"],
                            },
                        },
                    },
                )
            return FakeResponse(
                {},
                content=b"mxapi-png-bytes",
                headers={"content-type": "image/png"},
            )

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(aigc_studio.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(aigc_studio, "_mxapi_sleep", no_sleep, raising=False)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "MXAPI board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "mxapi",
                    "model_id": "gpt-image-2",
                    "inputs": {"prompt": "一只可爱的猫咪"},
                    "parameters": {
                        "aspectRatio": "1:1",
                        "resolution": "1K",
                        "quality": "auto",
                    },
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    job = ran.json()
    assert job["status"] == "succeeded"
    post_call = next(item for item in requests if item["type"] == "post")
    assert post_call["url"] == "https://open.mxapi.org/api/v2/gpt-image-2"
    assert post_call["kwargs"]["headers"] == {
        "X-Provider-Trace": "enabled",
        "Authorization": "Bearer mxapi-test-key",
        "Content-Type": "application/json",
        "X-Channel": "official",
    }
    assert post_call["kwargs"]["json"] == {
        "prompt": "一只可爱的猫咪",
        "aspect_ratio": "1:1",
        "quality": "auto",
        "resolution": "1K",
    }
    assert any(
        item["type"] == "get"
        and item["url"]
        == "https://open.mxapi.org/api/v2/gpt-image/task?task_id=task-123"
        and item["kwargs"]["headers"] == {
            "X-Channel": "official",
            "X-Provider-Trace": "enabled",
            "Authorization": "Bearer mxapi-test-key",
        }
        for item in requests
    )
    assert any(
        item["type"] == "get" and item["url"] == "https://cdn.example.test/mxapi.png"
        for item in requests
    )
    artifact = tmp_path / "workspace" / job["outputs"][0]["path"]
    assert artifact.suffix == ".png"
    assert artifact.read_bytes() == b"mxapi-png-bytes"
    assert job["outputs"][0]["meta"]["adapter"] == "mxapi_gpt_image"
    assert job["outputs"][0]["meta"]["mxapi_task_id"] == "task-123"


async def test_run_mxapi_gpt_image_ignores_prompt_text_references(
    tmp_path,
    monkeypatch,
):
    """Connected text nodes should not be submitted as MXAPI reference images."""
    app = make_mxapi_app(tmp_path)
    transport = ASGITransport(app=app)
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(
            self,
            payload: dict[str, object],
            *,
            content: bytes = b"",
            headers: dict[str, str] | None = None,
        ):
            self._payload = payload
            self.content = content
            self.headers = headers or {}

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            requests.append({"type": "client", "kwargs": kwargs})

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            requests.append({"type": "post", "url": url, "kwargs": kwargs})
            return FakeResponse({"code": 200, "data": {"task_id": "task-text"}})

        async def get(self, url, **kwargs):
            requests.append({"type": "get", "url": url, "kwargs": kwargs})
            if "gpt-image/task" in url:
                return FakeResponse(
                    {
                        "data": {
                            "status": "completed",
                            "result": {
                                "images": ["https://cdn.example.test/text.png"],
                            },
                        },
                    },
                )
            return FakeResponse(
                {},
                content=b"text-reference-png-bytes",
                headers={"content-type": "image/png"},
            )

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(aigc_studio.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(aigc_studio, "_mxapi_sleep", no_sleep, raising=False)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "MXAPI text reference board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "mxapi",
                    "model_id": "gpt-image-2",
                    "inputs": {
                        "prompt": "做一张背景图，把第一段参考文本放进去",
                        "reference_nodes": [
                            {
                                "node_id": "prompt-1",
                                "type": "prompt",
                                "title": "文本节点",
                                "preview_url": "prompt",
                                "text": "小明上课睡觉被老师抓到。",
                            }
                        ],
                    },
                    "parameters": {"aspectRatio": "16:9", "resolution": "2K"},
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    assert ran.json()["status"] == "succeeded", ran.json()
    post_call = next(item for item in requests if item["type"] == "post")
    assert "reference_images" not in post_call["kwargs"]["json"]


async def test_run_mxapi_gpt_image_job_fans_out_image_count(
    tmp_path,
    monkeypatch,
):
    """MXAPI single-image task endpoints should fan out imageCount into multiple tasks."""
    app = make_mxapi_app(tmp_path)
    transport = ASGITransport(app=app)
    requests: list[dict[str, object]] = []
    submitted_task_ids: list[str] = []

    class FakeResponse:
        def __init__(
            self,
            payload: dict[str, object],
            *,
            content: bytes = b"",
            headers: dict[str, str] | None = None,
        ):
            self._payload = payload
            self.content = content
            self.headers = headers or {}

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            requests.append({"type": "client", "kwargs": kwargs})

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            task_id = f"task-{len(submitted_task_ids) + 1}"
            submitted_task_ids.append(task_id)
            requests.append({"type": "post", "url": url, "kwargs": kwargs})
            return FakeResponse({"code": 200, "data": {"task_id": task_id}})

        async def get(self, url, **kwargs):
            requests.append({"type": "get", "url": url, "kwargs": kwargs})
            if "gpt-image/task" in url:
                task_id = url.rsplit("task_id=", 1)[-1]
                return FakeResponse(
                    {
                        "data": {
                            "status": "completed",
                            "result": {
                                "images": [f"https://cdn.example.test/{task_id}.png"],
                            },
                        },
                    },
                )
            return FakeResponse(
                {},
                content=f"image-bytes:{url}".encode(),
                headers={"content-type": "image/png"},
            )

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(aigc_studio.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(aigc_studio, "_mxapi_sleep", no_sleep, raising=False)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "MXAPI multi board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "mxapi",
                    "model_id": "gpt-image-2",
                    "inputs": {"prompt": "一位精灵少女"},
                    "parameters": {
                        "aspectRatio": "9:16",
                        "resolution": "2K",
                        "imageCount": 3,
                    },
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    job = ran.json()
    assert job["status"] == "succeeded"
    post_calls = [item for item in requests if item["type"] == "post"]
    assert len(post_calls) == 3
    assert [item["kwargs"]["json"] for item in post_calls] == [
        {
            "prompt": "一位精灵少女",
            "aspect_ratio": "9:16",
            "quality": "auto",
            "resolution": "2K",
        },
        {
            "prompt": "一位精灵少女",
            "aspect_ratio": "9:16",
            "quality": "auto",
            "resolution": "2K",
        },
        {
            "prompt": "一位精灵少女",
            "aspect_ratio": "9:16",
            "quality": "auto",
            "resolution": "2K",
        },
    ]
    assert [asset["name"] for asset in job["outputs"]] == [
        f"image-1-{job['id']}.1.png",
        f"image-1-{job['id']}.2.png",
        f"image-1-{job['id']}.3.png",
    ]
    assert [asset["meta"]["mxapi_task_id"] for asset in job["outputs"]] == [
        "task-1",
        "task-2",
        "task-3",
    ]
    assert [
        (tmp_path / "workspace" / asset["path"]).read_bytes()
        for asset in job["outputs"]
    ] == [
        b"image-bytes:https://cdn.example.test/task-1.png",
        b"image-bytes:https://cdn.example.test/task-2.png",
        b"image-bytes:https://cdn.example.test/task-3.png",
    ]


def test_mxapi_gpt_image_submit_body_uses_gpt_image2_parameters():
    """MXAPI GPT Image 2 should use its documented fields and default-channel quality."""
    job = aigc_studio.AigcJob(
        id="job-1",
        canvas_id="canvas-1",
        node_id="image-1",
        capability="image_edit",
        provider_id="mxapi",
        model_id="gpt-image-2",
        inputs={"prompt": "生成品牌海报"},
        parameters={
            "aspectRatio": "9:16",
            "resolution": "2K",
            "imageQuality": "标准画质",
        },
        status="queued",
        created_at="2026-06-29T00:00:00Z",
        updated_at="2026-06-29T00:00:00Z",
    )

    body = aigc_studio._mxapi_submit_body(
        job,
        prompt="生成品牌海报",
        reference_images=["https://cdn.example.test/reference.png"],
        adapter="mxapi_gpt_image",
    )

    assert body == {
        "prompt": "生成品牌海报",
        "aspect_ratio": "9:16",
        "quality": "auto",
        "resolution": "2K",
        "reference_images": ["https://cdn.example.test/reference.png"],
    }


def test_mxapi_gpt_image_submit_body_normalizes_unsupported_ratio():
    """MXAPI GPT Image 2 should not submit ratios outside its V2 contract."""
    job = aigc_studio.AigcJob(
        id="job-1",
        canvas_id="canvas-1",
        node_id="image-1",
        capability="text_to_image",
        provider_id="mxapi",
        model_id="gpt-image-2",
        inputs={"prompt": "生成品牌海报"},
        parameters={
            "aspectRatio": "4:5",
            "resolution": "2K",
            "imageQuality": "标准画质",
        },
        status="queued",
        created_at="2026-06-29T00:00:00Z",
        updated_at="2026-06-29T00:00:00Z",
    )

    body = aigc_studio._mxapi_submit_body(
        job,
        prompt="生成品牌海报",
        reference_images=[],
        adapter="mxapi_gpt_image",
    )

    assert body["aspect_ratio"] == "1:1"


def test_mxapi_gpt_image_submit_body_keeps_quality_on_official_channel():
    """The official MXAPI GPT Image 2 channel can receive explicit quality settings."""
    job = aigc_studio.AigcJob(
        id="job-1",
        canvas_id="canvas-1",
        node_id="image-1",
        capability="image_edit",
        provider_id="mxapi",
        model_id="gpt-image-2",
        inputs={"prompt": "生成品牌海报"},
        parameters={
            "aspectRatio": "9:16",
            "resolution": "2K",
            "imageQuality": "标准画质",
            "mxapiChannel": "official",
        },
        status="queued",
        created_at="2026-06-29T00:00:00Z",
        updated_at="2026-06-29T00:00:00Z",
    )

    body = aigc_studio._mxapi_submit_body(
        job,
        prompt="生成品牌海报",
        reference_images=[],
        adapter="mxapi_gpt_image",
    )

    assert body["quality"] == "medium"
    assert body["resolution"] == "2K"


async def test_run_mxapi_nano2_job_uses_nano2_protocol(
    tmp_path,
    monkeypatch,
):
    """MXAPI Nano2 should use the nano2 async endpoint and image_size field."""
    app = make_mxapi_app(tmp_path)
    transport = ASGITransport(app=app)
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(
            self,
            payload: dict[str, object],
            *,
            content: bytes = b"",
            headers: dict[str, str] | None = None,
        ):
            self._payload = payload
            self.content = content
            self.headers = headers or {}

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            requests.append({"type": "client", "kwargs": kwargs})

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            requests.append({"type": "post", "url": url, "kwargs": kwargs})
            return FakeResponse({"code": 200, "data": {"task_id": "nano-task"}})

        async def get(self, url, **kwargs):
            requests.append({"type": "get", "url": url, "kwargs": kwargs})
            if "nano/task" in url:
                return FakeResponse(
                    {
                        "data": {
                            "status": "completed",
                            "result": {
                                "images": ["https://cdn.example.test/nano2.png"],
                            },
                        },
                    },
                )
            return FakeResponse(
                {},
                content=b"nano2-png-bytes",
                headers={"content-type": "image/png"},
            )

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(aigc_studio.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(aigc_studio, "_mxapi_sleep", no_sleep, raising=False)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Nano2 board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "mxapi",
                    "model_id": "nano2",
                    "inputs": {"prompt": "一只可爱的猫咪"},
                    "parameters": {
                        "aspectRatio": "16:9",
                        "resolution": "4K",
                        "quality": "high",
                    },
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    job = ran.json()
    assert job["status"] == "succeeded"
    post_call = next(item for item in requests if item["type"] == "post")
    assert post_call["url"] == "https://open.mxapi.org/api/v2/nano2"
    assert post_call["kwargs"]["headers"] == {
        "X-Provider-Trace": "enabled",
        "Authorization": "Bearer mxapi-test-key",
        "Content-Type": "application/json",
        "X-Channel": "official",
    }
    assert post_call["kwargs"]["json"] == {
        "prompt": "一只可爱的猫咪",
        "image_size": "4K",
        "aspect_ratio": "16:9",
    }
    assert any(
        item["type"] == "get"
        and item["url"] == "https://open.mxapi.org/api/v2/nano/task?task_id=nano-task"
        for item in requests
    )
    artifact = tmp_path / "workspace" / job["outputs"][0]["path"]
    assert artifact.suffix == ".png"
    assert artifact.read_bytes() == b"nano2-png-bytes"
    assert job["outputs"][0]["meta"]["adapter"] == "mxapi_nano2"
    assert job["outputs"][0]["meta"]["mxapi_task_id"] == "nano-task"


async def test_run_mxapi_seedance_text_to_video_job_polls_and_saves_video(
    tmp_path,
    monkeypatch,
):
    """MXAPI Seedance should submit an async video task, poll it, and persist MP4 output."""
    app = make_mxapi_app(tmp_path)
    transport = ASGITransport(app=app)
    requests: list[dict[str, object]] = []
    task_payloads = [
        {"code": 200, "data": {"status": "running"}},
        {
            "code": 200,
            "data": {
                "status": "succeeded",
                "content": {"video_url": "https://cdn.example.test/seedance.mp4"},
                "ratio": "16:9",
                "resolution": "720p",
                "duration": 5,
            },
        },
    ]

    class FakeResponse:
        def __init__(
            self,
            payload: dict[str, object],
            *,
            content: bytes = b"",
            headers: dict[str, str] | None = None,
        ):
            self._payload = payload
            self.content = content
            self.headers = headers or {}

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            requests.append({"type": "client", "kwargs": kwargs})

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            requests.append({"type": "post", "url": url, "kwargs": kwargs})
            return FakeResponse({"code": 200, "data": {"task_id": "seedance-task"}})

        async def get(self, url, **kwargs):
            requests.append({"type": "get", "url": url, "kwargs": kwargs})
            if "video/task" in url:
                return FakeResponse(task_payloads.pop(0))
            return FakeResponse(
                {},
                content=b"seedance-mp4-bytes",
                headers={"content-type": "video/mp4"},
            )

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(aigc_studio.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(aigc_studio, "_mxapi_sleep", no_sleep, raising=False)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Seedance board",
                    "nodes": [{"id": "video-1", "type": "video_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "video-1",
                    "capability": "text_to_video",
                    "provider_id": "mxapi",
                    "model_id": "seedance2-fast",
                    "inputs": {"prompt": "一只可爱的小猫在花园里玩耍，阳光明媚"},
                    "parameters": {
                        "aspectRatio": "16:9",
                        "videoResolution": "720P",
                        "videoDuration": 5,
                        "videoAudio": False,
                        "return_last_frame": False,
                    },
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    job = ran.json()
    assert job["status"] == "succeeded"
    post_call = next(item for item in requests if item["type"] == "post")
    assert post_call["url"] == "https://open.mxapi.org/api/v2/video/seedance2-fast"
    assert post_call["kwargs"]["headers"]["Authorization"] == "Bearer mxapi-test-key"
    assert post_call["kwargs"]["headers"]["Content-Type"] == "application/json"
    assert post_call["kwargs"]["json"] == {
        "content": [
            {
                "type": "text",
                "text": "一只可爱的小猫在花园里玩耍，阳光明媚",
            },
        ],
        "resolution": "720p",
        "ratio": "16:9",
        "duration": 5,
        "generate_audio": False,
        "return_last_frame": False,
    }
    assert any(
        item["type"] == "get"
        and item["url"]
        == "https://open.mxapi.org/api/v2/video/task?task_id=seedance-task"
        for item in requests
    )
    assert any(
        item["type"] == "get" and item["url"] == "https://cdn.example.test/seedance.mp4"
        for item in requests
    )
    artifact = tmp_path / "workspace" / job["outputs"][0]["path"]
    assert artifact.suffix == ".mp4"
    assert artifact.read_bytes() == b"seedance-mp4-bytes"
    assert job["outputs"][0]["kind"] == "video"
    assert job["outputs"][0]["mime_type"] == "video/mp4"
    assert job["outputs"][0]["meta"]["adapter"] == "mxapi_seedance2"
    assert job["outputs"][0]["meta"]["seedance_task_id"] == "seedance-task"
    assert (
        job["outputs"][0]["meta"]["source_url"]
        == "https://cdn.example.test/seedance.mp4"
    )


async def test_run_mxapi_seedance_first_last_frames_maps_reference_roles(
    tmp_path,
    monkeypatch,
):
    """Seedance first/last-frame mode should send two image_url entries with frame roles."""
    app = make_mxapi_app(tmp_path)
    transport = ASGITransport(app=app)
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(
            self,
            payload: dict[str, object],
            *,
            content: bytes = b"",
            headers: dict[str, str] | None = None,
        ):
            self._payload = payload
            self.content = content
            self.headers = headers or {}

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            requests.append({"type": "client", "kwargs": kwargs})

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            requests.append({"type": "post", "url": url, "kwargs": kwargs})
            return FakeResponse({"code": 200, "data": {"task_id": "seedance-frames"}})

        async def get(self, url, **kwargs):
            requests.append({"type": "get", "url": url, "kwargs": kwargs})
            if "video/task" in url:
                return FakeResponse(
                    {
                        "code": 200,
                        "data": {
                            "status": "completed",
                            "video_url": "https://cdn.example.test/frames.mp4",
                        },
                    },
                )
            return FakeResponse(
                {},
                content=b"frames-mp4-bytes",
                headers={"content-type": "video/mp4"},
            )

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(aigc_studio.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(aigc_studio, "_mxapi_sleep", no_sleep, raising=False)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Seedance frames board",
                    "nodes": [{"id": "video-1", "type": "video_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "video-1",
                    "capability": "image_to_video",
                    "provider_id": "mxapi",
                    "model_id": "seedance2",
                    "inputs": {"prompt": "小猫从睡觉到跳起来追蝴蝶"},
                    "parameters": {
                        "videoMode": "first_last_frames",
                        "activeVideoTab": "first_frame",
                        "aspectRatio": "Auto",
                        "videoResolution": "1080P",
                        "videoDuration": 5,
                        "videoAudio": False,
                        "videoReferenceAssets": [
                            {
                                "kind": "image",
                                "previewUrl": "https://cdn.example.test/first.jpg",
                            },
                            {
                                "kind": "image",
                                "previewUrl": "https://cdn.example.test/last.jpg",
                                "role": "last_frame",
                            },
                        ],
                    },
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    assert ran.json()["status"] == "succeeded", ran.json()
    post_call = next(item for item in requests if item["type"] == "post")
    assert post_call["kwargs"]["json"]["content"] == [
        {"type": "text", "text": "小猫从睡觉到跳起来追蝴蝶"},
        {
            "type": "image_url",
            "image_url": {"url": "https://cdn.example.test/first.jpg"},
            "role": "first_frame",
        },
        {
            "type": "image_url",
            "image_url": {"url": "https://cdn.example.test/last.jpg"},
            "role": "last_frame",
        },
    ]
    assert post_call["kwargs"]["json"]["ratio"] == "adaptive"
    assert post_call["kwargs"]["json"]["resolution"] == "1080p"


async def test_run_mxapi_seedance_rejects_blob_reference_urls(tmp_path, monkeypatch):
    """Seedance references must be reachable URLs rather than browser-only blobs."""
    app = make_mxapi_app(tmp_path)
    transport = ASGITransport(app=app)
    post_calls: list[str] = []

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **_kwargs):
            post_calls.append(url)
            return None

    monkeypatch.setattr(aigc_studio.httpx, "AsyncClient", FakeAsyncClient)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Seedance blob board",
                    "nodes": [{"id": "video-1", "type": "video_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "video-1",
                    "capability": "image_to_video",
                    "provider_id": "mxapi",
                    "model_id": "seedance2",
                    "inputs": {"prompt": "让这张图片动起来"},
                    "parameters": {
                        "videoMode": "image_to_video",
                        "videoReferenceAssets": [
                            {
                                "kind": "image",
                                "previewUrl": "blob:browser-only-first-frame",
                            },
                        ],
                    },
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    job = ran.json()
    assert job["status"] == "failed"
    assert "browser blob" in job["error"]
    assert post_calls == []


async def test_run_mxapi_gpt_image_rejects_local_reference_urls(
    tmp_path,
    monkeypatch,
):
    """MXAPI reference images must be externally reachable URLs."""
    app = make_mxapi_app(tmp_path)
    transport = ASGITransport(app=app)
    post_calls: list[str] = []

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **_kwargs):
            post_calls.append(url)
            raise AssertionError("MXAPI should not receive private reference URLs")

    monkeypatch.delenv("AIGC_STUDIO_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("QWENPAW_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.setattr(aigc_studio.httpx, "AsyncClient", FakeAsyncClient)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "MXAPI edit board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "image_edit",
                    "provider_id": "mxapi",
                    "model_id": "gpt-image-2",
                    "inputs": {
                        "prompt": "把包装做成高端海报",
                        "reference_nodes": [
                            {
                                "node_id": "source-1",
                                "preview_url": (
                                    "http://127.0.0.1:18088/api/aigc-studio/"
                                    "assets/source/file"
                                ),
                            }
                        ],
                    },
                    "parameters": {"aspectRatio": "9:16", "resolution": "2K"},
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    assert ran.json()["status"] == "failed"
    assert "public image URLs" in ran.json()["error"]
    assert "127.0.0.1" in ran.json()["error"]
    assert post_calls == []


async def test_run_mxapi_gpt_image_rewrites_local_asset_to_signed_public_url(
    tmp_path,
    monkeypatch,
):
    """Public deployments should expose local asset references through signed URLs."""
    app = make_mxapi_app(tmp_path)
    transport = ASGITransport(app=app)
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(
            self,
            payload: dict[str, object],
            *,
            content: bytes = b"",
            headers: dict[str, str] | None = None,
        ):
            self._payload = payload
            self.content = content
            self.headers = headers or {}

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            requests.append({"type": "post", "url": url, "kwargs": kwargs})
            return FakeResponse({"code": 200, "data": {"task_id": "task-edit"}})

        async def get(self, url, **_kwargs):
            requests.append({"type": "get", "url": url})
            if "gpt-image/task" in url:
                return FakeResponse(
                    {
                        "data": {
                            "status": "completed",
                            "result": {
                                "images": ["https://cdn.example.test/edited.png"],
                            },
                        },
                    },
                )
            return FakeResponse(
                {},
                content=b"edited-png-bytes",
                headers={"content-type": "image/png"},
            )

    async def no_sleep(_seconds):
        return None

    monkeypatch.setenv("AIGC_STUDIO_PUBLIC_BASE_URL", "https://aigc.example.com")
    monkeypatch.setenv("AIGC_STUDIO_PUBLIC_ASSET_SECRET", "test-public-secret")
    aigc_studio._public_asset_signing_secret.cache_clear()
    monkeypatch.setattr(aigc_studio.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(aigc_studio, "_mxapi_sleep", no_sleep, raising=False)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "MXAPI public asset board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "image_edit",
                    "provider_id": "mxapi",
                    "model_id": "gpt-image-2",
                    "inputs": {
                        "prompt": "把包装做成高端海报",
                        "reference_nodes": [
                            {
                                "node_id": "source-1",
                                "preview_url": (
                                    "http://127.0.0.1:18088/api/aigc-studio/"
                                    "assets/source-asset/file"
                                ),
                            }
                        ],
                    },
                    "parameters": {"aspectRatio": "9:16", "resolution": "2K"},
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    assert ran.json()["status"] == "succeeded", ran.json()
    post_call = next(item for item in requests if item["type"] == "post")
    reference_images = post_call["kwargs"]["json"]["reference_images"]
    assert len(reference_images) == 1
    assert reference_images[0].startswith(
        "https://aigc.example.com/api/aigc-studio/public-assets/source-asset/file?token="
    )
    assert "/assets/source-asset/file" not in reference_images[0]


async def test_run_mxapi_gpt_image_uses_signed_url_for_cloud_asset_references(
    tmp_path,
    monkeypatch,
):
    """Cloud-backed references should avoid short-lived OSS signatures for model fetches."""
    app = make_mxapi_app(tmp_path)
    transport = ASGITransport(app=app)
    requests: list[dict[str, object]] = []
    signed_gets: list[str] = []

    class FakeObjectStorageClient:
        def signed_get_url(self, object_key: str, **_kwargs) -> str:
            signed_gets.append(object_key)
            return f"https://oss.example.test/{object_key}?Expires=1&Signature=old"

        async def download(self, object_key: str):
            return b"source-png", "image/png"

        async def upload(self, *, relative_path: str, content, mime_type: str):
            return {
                "provider": "aliyun_oss",
                "bucket": "qwenpaw-aigc",
                "endpoint": "https://oss.example.test",
                "object_key": f"aigc/generated/{relative_path}",
                "size": len(content),
            }

    class FakeResponse:
        def __init__(
            self,
            payload: dict[str, object],
            *,
            content: bytes = b"",
            headers: dict[str, str] | None = None,
        ):
            self._payload = payload
            self.content = content
            self.headers = headers or {}

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            requests.append({"type": "post", "url": url, "kwargs": kwargs})
            return FakeResponse({"code": 200, "data": {"task_id": "task-edit"}})

        async def get(self, url, **_kwargs):
            requests.append({"type": "get", "url": url})
            if "gpt-image/task" in url:
                return FakeResponse(
                    {
                        "data": {
                            "status": "completed",
                            "result": {
                                "images": ["https://cdn.example.test/edited.png"],
                            },
                        },
                    },
                )
            return FakeResponse(
                {},
                content=b"edited-png-bytes",
                headers={"content-type": "image/png"},
            )

    async def no_sleep(_seconds):
        return None

    monkeypatch.setenv("AIGC_STUDIO_PUBLIC_BASE_URL", "https://aigc.example.com")
    monkeypatch.setenv("AIGC_STUDIO_PUBLIC_ASSET_SECRET", "test-public-secret")
    aigc_studio._public_asset_signing_secret.cache_clear()
    monkeypatch.setattr(
        aigc_studio,
        "get_object_storage_client",
        lambda **_kwargs: FakeObjectStorageClient(),
        raising=False,
    )
    monkeypatch.setattr(aigc_studio.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(aigc_studio, "_mxapi_sleep", no_sleep, raising=False)

    cloud_asset = aigc_studio.AigcAsset(
        id="source-asset",
        kind="image",
        name="source.png",
        path="oss://qwenpaw-aigc/aigc/generated/source.png",
        url="/api/aigc-studio/assets/source-asset/file",
        mime_type="image/png",
        created_at="2026-07-07T00:00:00Z",
        meta={
            "owner_user_id": "0",
            "storage": {
                "provider": "aliyun_oss",
                "bucket": "qwenpaw-aigc",
                "object_key": "aigc/generated/source.png",
            },
        },
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        aigc_studio._write_json(
            aigc_studio._json_path("assets", cloud_asset.id),
            cloud_asset,
        )
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "MXAPI cloud asset board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "image_edit",
                    "provider_id": "mxapi",
                    "model_id": "gpt-image-2",
                    "inputs": {
                        "prompt": "把包装做成高端海报",
                        "reference_nodes": [
                            {
                                "node_id": "source-1",
                                "preview_url": (
                                    "http://127.0.0.1:18088/api/aigc-studio/"
                                    "assets/source-asset/file"
                                ),
                            }
                        ],
                    },
                    "parameters": {"aspectRatio": "9:16", "resolution": "2K"},
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    assert ran.json()["status"] == "succeeded", ran.json()
    post_call = next(item for item in requests if item["type"] == "post")
    reference_images = post_call["kwargs"]["json"]["reference_images"]
    assert len(reference_images) == 1
    assert reference_images[0].startswith(
        "https://oss.example.test/aigc/generated/source.png?"
    )
    assert signed_gets == ["aigc/generated/source.png"]


async def test_public_asset_file_requires_signed_token(tmp_path, monkeypatch):
    """Signed public asset links should not expose files without a valid token."""
    app = make_mxapi_app(tmp_path)
    transport = ASGITransport(app=app)

    monkeypatch.setenv("AIGC_STUDIO_PUBLIC_ASSET_SECRET", "test-public-secret")
    aigc_studio._public_asset_signing_secret.cache_clear()

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            uploaded = await client.post(
                "/api/aigc-studio/assets/upload",
                files={"file": ("reference.png", b"reference-bytes", "image/png")},
            )
            asset_id = uploaded.json()["id"]

            missing_token = await client.get(
                f"/api/aigc-studio/public-assets/{asset_id}/file",
            )
            valid_token = aigc_studio._public_asset_token(asset_id)
            downloaded = await client.get(
                f"/api/aigc-studio/public-assets/{asset_id}/file",
                params={"token": valid_token},
            )

    assert missing_token.status_code == 403
    assert downloaded.status_code == 200
    assert downloaded.content == b"reference-bytes"


def test_public_asset_url_ttl_defaults_to_full_day(monkeypatch):
    """Model-side asset fetch links should survive ordinary queue and retry delays."""
    monkeypatch.delenv("AIGC_STUDIO_PUBLIC_ASSET_URL_TTL_SECONDS", raising=False)

    assert aigc_studio._mxapi_public_asset_url_ttl_seconds() == 86400


def test_external_asset_reference_url_uses_long_ttl_signed_oss_without_public_base(
    tmp_path,
    monkeypatch,
):
    """OSS fallback URLs sent to external models should not use short preview TTLs."""
    signed_gets: list[tuple[str, int | None]] = []

    class FakeObjectStorageClient:
        def signed_get_url(
            self, object_key: str, ttl_seconds: int | None = None
        ) -> str:
            signed_gets.append((object_key, ttl_seconds))
            return f"https://oss.example.test/{object_key}?Expires={ttl_seconds}"

    monkeypatch.delenv("AIGC_STUDIO_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("QWENPAW_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("AIGC_STUDIO_PUBLIC_ASSET_URL_TTL_SECONDS", raising=False)
    monkeypatch.setattr(
        aigc_studio,
        "get_object_storage_client",
        lambda **_kwargs: FakeObjectStorageClient(),
        raising=False,
    )
    request = SimpleNamespace(
        state=SimpleNamespace(user_id="0", role="user"),
    )
    asset = aigc_studio.AigcAsset(
        id="cloud-ref",
        kind="image",
        name="cloud-ref.png",
        path="oss://qwenpaw-aigc/aigc/generated/cloud-ref.png",
        url="/api/aigc-studio/assets/cloud-ref/file",
        mime_type="image/png",
        created_at="2026-07-07T00:00:00Z",
        meta={
            "owner_user_id": "0",
            "storage": {
                "provider": "aliyun_oss",
                "bucket": "qwenpaw-aigc",
                "object_key": "aigc/generated/cloud-ref.png",
            },
        },
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        aigc_studio._write_json(aigc_studio._json_path("assets", asset.id), asset)

        url = aigc_studio._external_asset_reference_url(request, asset.id)

    assert url == "https://oss.example.test/aigc/generated/cloud-ref.png?Expires=86400"
    assert signed_gets == [("aigc/generated/cloud-ref.png", 86400)]


def test_external_asset_reference_url_falls_back_to_public_provider_source(
    tmp_path,
    monkeypatch,
):
    """Provider-generated media remains usable as a local reference without OSS."""
    monkeypatch.delenv("AIGC_STUDIO_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("QWENPAW_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    request = SimpleNamespace(
        state=SimpleNamespace(user_id="0", role="user"),
    )
    asset = aigc_studio.AigcAsset(
        id="provider-ref",
        kind="image",
        name="provider-ref.png",
        path="aigc_studio/provider-ref.png",
        url="http://127.0.0.1:18088/api/user/aigc-studio/assets/provider-ref/file",
        mime_type="image/png",
        created_at="2026-09-08T00:00:00Z",
        meta={
            "owner_user_id": "0",
            "source_url": "https://media.provider.example/generated/provider-ref.png",
        },
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        aigc_studio._write_json(aigc_studio._json_path("assets", asset.id), asset)

        url = aigc_studio._external_asset_reference_url(request, asset.id)

    assert url == "https://media.provider.example/generated/provider-ref.png"


def test_external_asset_reference_url_rejects_private_provider_source(
    tmp_path,
    monkeypatch,
):
    """Stored provider metadata cannot bypass the external-reference host check."""
    monkeypatch.delenv("AIGC_STUDIO_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("QWENPAW_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    request = SimpleNamespace(
        state=SimpleNamespace(user_id="0", role="user"),
    )
    asset = aigc_studio.AigcAsset(
        id="private-provider-ref",
        kind="image",
        name="private-provider-ref.png",
        path="aigc_studio/private-provider-ref.png",
        url="/api/user/aigc-studio/assets/private-provider-ref/file",
        mime_type="image/png",
        created_at="2026-09-08T00:00:00Z",
        meta={
            "owner_user_id": "0",
            "source_url": "http://127.0.0.1/internal/provider-ref.png",
        },
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        aigc_studio._write_json(aigc_studio._json_path("assets", asset.id), asset)

        url = aigc_studio._external_asset_reference_url(request, asset.id)

    assert url is None


async def test_run_mxapi_gpt_image_surfaces_submit_error_body(
    tmp_path,
    monkeypatch,
):
    """MXAPI HTTP 400 bodies should be visible in the failed job error."""
    app = make_mxapi_app(tmp_path)
    transport = ASGITransport(app=app)

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **_kwargs):
            return httpx.Response(
                400,
                json={"message": "参考图片无法访问或格式不支持"},
                request=httpx.Request("POST", url),
            )

    monkeypatch.setattr(aigc_studio.httpx, "AsyncClient", FakeAsyncClient)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "MXAPI failed board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "mxapi",
                    "model_id": "gpt-image-2",
                    "inputs": {"prompt": "一张商品海报"},
                    "parameters": {"aspectRatio": "1:1", "resolution": "1K"},
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    assert ran.json()["status"] == "failed"
    assert (
        "MXAPI task submission failed: 参考图片无法访问或格式不支持"
        in ran.json()["error"]
    )


async def test_run_mxapi_gpt_image_job_applies_selected_style_to_prompt(
    tmp_path,
    monkeypatch,
):
    """MXAPI GPT Image 2 should receive selected Studio styles as prompt guidance."""
    app = make_mxapi_app(tmp_path)
    transport = ASGITransport(app=app)
    post_body: dict[str, object] = {}

    class FakeResponse:
        def __init__(
            self,
            payload: dict[str, object],
            *,
            content: bytes = b"",
            headers: dict[str, str] | None = None,
        ):
            self._payload = payload
            self.content = content
            self.headers = headers or {}

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, _url, **kwargs):
            post_body.update(kwargs["json"])
            return FakeResponse({"code": 200, "data": {"task_id": "task-style"}})

        async def get(self, url, **_kwargs):
            if "gpt-image/task" in url:
                return FakeResponse(
                    {
                        "data": {
                            "status": "completed",
                            "result": {
                                "images": ["https://cdn.example.test/styled.png"],
                            },
                        },
                    },
                )
            return FakeResponse(
                {},
                content=b"styled-mxapi-png",
                headers={"content-type": "image/png"},
            )

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(aigc_studio.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(aigc_studio, "_mxapi_sleep", no_sleep, raising=False)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "MXAPI style board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "mxapi",
                    "model_id": "gpt-image-2",
                    "inputs": {"prompt": "小女孩"},
                    "parameters": {
                        "aspectRatio": "16:9",
                        "resolution": "2K",
                        "styleRuntimeMode": "native_effect",
                        "styleReferenceName": "一键国漫CGV2",
                        "styleKeywords": "国漫, CG, 角色海报, 冷色调, 金属质感",
                        "styleDescription": "国漫 CG 风格，突出角色轮廓、冷色调光影、金属质感与高对比氛围。",
                        "effectTemplateUuids": ["dbc6dfc0990d46d28215bcdff87d53c3"],
                        "effects": [22910748],
                    },
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    assert ran.json()["status"] == "succeeded"
    assert post_body["prompt"] == (
        "小女孩\n\n"
        "风格参考：一键国漫CGV2。\n"
        "风格描述：国漫 CG 风格，突出角色轮廓、冷色调光影、金属质感与高对比氛围。\n"
        "风格关键词：国漫, CG, 角色海报, 冷色调, 金属质感"
    )
    assert "effectTemplateUuids" not in post_body
    assert "effects" not in post_body


async def test_run_mxapi_gpt_image_job_keeps_polling_after_query_timeout(
    tmp_path,
    monkeypatch,
):
    """A transient MXAPI task-query timeout should not fail the whole image job."""
    app = make_mxapi_app(tmp_path)
    transport = ASGITransport(app=app)
    task_query_count = 0

    class FakeResponse:
        def __init__(
            self,
            payload: dict[str, object],
            *,
            content: bytes = b"",
            headers: dict[str, str] | None = None,
        ):
            self._payload = payload
            self.content = content
            self.headers = headers or {}

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, _url, **_kwargs):
            return FakeResponse({"code": 200, "data": {"task_id": "task-timeout"}})

        async def get(self, url, **_kwargs):
            nonlocal task_query_count
            if "gpt-image/task" in url:
                task_query_count += 1
                if task_query_count == 1:
                    raise httpx.ReadTimeout("")
                return FakeResponse(
                    {
                        "data": {
                            "status": "completed",
                            "result": {
                                "images": ["https://cdn.example.test/mxapi.png"],
                            },
                        },
                    },
                )
            return FakeResponse(
                {},
                content=b"mxapi-png-after-timeout",
                headers={"content-type": "image/png"},
            )

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(aigc_studio.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(aigc_studio, "_mxapi_sleep", no_sleep, raising=False)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "MXAPI timeout board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "mxapi",
                    "model_id": "gpt-image-2",
                    "inputs": {"prompt": "一个小女孩"},
                    "parameters": {"aspectRatio": "16:9", "resolution": "2K"},
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    job = ran.json()
    assert job["status"] == "succeeded"
    assert task_query_count == 2
    artifact = tmp_path / "workspace" / job["outputs"][0]["path"]
    assert artifact.read_bytes() == b"mxapi-png-after-timeout"


async def test_run_job_records_exception_class_when_message_is_empty(
    tmp_path,
    monkeypatch,
):
    """Failed jobs should expose a useful error even when str(exc) is empty."""
    app = make_mxapi_app(tmp_path)
    transport = ASGITransport(app=app)

    async def fail_with_empty_message(_request, _job, _execution=None):
        raise httpx.ReadTimeout("")

    monkeypatch.setattr(aigc_studio, "_execute_job", fail_with_empty_message)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Empty error board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "mxapi",
                    "model_id": "gpt-image-2",
                    "inputs": {"prompt": "一个小女孩"},
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    job = ran.json()
    assert job["status"] == "failed"
    assert job["error"] == "ReadTimeout"
    assert job["logs"][-1] == "Job failed: ReadTimeout"


async def test_seedream_prompt_style_template_is_applied_to_prompt(
    tmp_path,
    monkeypatch,
):
    """Prompt-style templates should affect runtime prompts without sending unsupported effect fields."""
    app = make_seedream_app(tmp_path)
    transport = ASGITransport(app=app)
    calls = {}

    class FakeImages:
        async def generate(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                data=[{"url": "https://cdn.example.test/styled.png"}]
            )

    class FakeOpenAIClient:
        images = FakeImages()

    monkeypatch.setattr(
        aigc_studio,
        "_openai_client",
        lambda api_key, base_url=None: FakeOpenAIClient(),
    )

    async def fake_download(url):
        return b"styled-png", "image/png"

    monkeypatch.setattr(
        aigc_studio,
        "_download_remote_asset",
        fake_download,
        raising=False,
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Image board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "volcengine",
                    "model_id": "doubao-seedream-4-5-251128",
                    "inputs": {"prompt": "把我的照片做风格改造"},
                    "parameters": {
                        "resolution": "2K",
                        "styleRuntimeMode": "prompt_style",
                        "styleReferenceName": "电影感",
                        "styleKeywords": "电影感, 戏剧光影",
                        "styleDescription": "电影级光影与景深，强调主体叙事和画面氛围。",
                        "effectTemplateUuids": ["should-not-be-sent"],
                        "effects": [22910748],
                    },
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    assert calls["prompt"] == (
        "把我的照片做风格改造\n\n"
        "风格参考：电影感。\n"
        "风格描述：电影级光影与景深，强调主体叙事和画面氛围。\n"
        "风格关键词：电影感, 戏剧光影"
    )
    assert calls["extra_body"] == {
        "watermark": True,
    }


async def test_seedream_reference_image_prompt_protects_subject_from_style_override(
    tmp_path,
    monkeypatch,
):
    """Connected image references should stay primary even when a style template is selected."""
    app = make_seedream_app(tmp_path)
    transport = ASGITransport(app=app)
    calls = {}

    class FakeImages:
        async def generate(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                data=[{"url": "https://cdn.example.test/result.png"}]
            )

    class FakeOpenAIClient:
        images = FakeImages()

    async def fake_download(url):
        return b"result-png", "image/png"

    monkeypatch.setattr(
        aigc_studio,
        "_openai_client",
        lambda api_key, base_url=None: FakeOpenAIClient(),
    )
    monkeypatch.setattr(
        aigc_studio, "_download_remote_asset", fake_download, raising=False
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Reference board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "volcengine",
                    "model_id": "doubao-seedream-4-5-251128",
                    "inputs": {
                        "prompt": "基于包装图生成品牌海报",
                        "reference_nodes": [
                            {
                                "node_id": "reference-1",
                                "type": "reference_asset",
                                "asset_name": "package.jpg",
                                "preview_url": "https://cdn.example.test/package.jpg",
                            }
                        ],
                    },
                    "parameters": {
                        "resolution": "2K",
                        "styleRuntimeMode": "prompt_style",
                        "styleReferenceName": "高端品牌海报",
                        "styleDescription": "不要复刻原图文字和具体排版。",
                    },
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    assert "参考图使用规则" in calls["prompt"]
    assert "风格只影响背景、光影、版式和氛围" in calls["prompt"]
    assert "如果参考图是产品或包装" in calls["prompt"]
    assert calls["extra_body"] == {
        "image": "https://cdn.example.test/package.jpg",
        "watermark": True,
        "sequential_image_generation": "disabled",
    }


def test_seedream_annotation_prompt_uses_clean_source_and_region_instruction():
    job = aigc_studio.AigcJob(
        id="job-annotation-1",
        canvas_id="canvas-1",
        node_id="image-1",
        capability="image_to_image",
        provider_id="volcengine",
        model_id="doubao-seedream-4-5-251128",
        inputs={
            "prompt": "脸蛋要加上皮肤质感",
            "reference_nodes": [
                {
                    "node_id": "annotation-1",
                    "type": "reference_asset",
                    "title": "标注",
                    "role": "image_annotation",
                    "asset_name": "face-mark.png",
                    "preview_url": "https://cdn.example.test/clean-face.png",
                    "source_preview_url": "https://cdn.example.test/clean-face.png",
                    "annotated_preview_url": "https://cdn.example.test/marked-face.png",
                    "instruction": "红圈是需要调整肤质的脸部区域",
                }
            ],
            "annotations": [
                {
                    "node_id": "annotation-1",
                    "role": "image_annotation",
                    "source_preview_url": "https://cdn.example.test/clean-face.png",
                    "annotated_preview_url": "https://cdn.example.test/marked-face.png",
                    "instruction": "红圈是需要调整肤质的脸部区域",
                }
            ],
        },
        parameters={
            "annotationSourcePreviewUrl": "https://cdn.example.test/clean-face.png",
            "annotationPreviewUrl": "https://cdn.example.test/marked-face.png",
            "annotationInstruction": "红圈是需要调整肤质的脸部区域",
        },
        status="queued",
        created_at="2026-06-26T00:00:00Z",
        updated_at="2026-06-26T00:00:00Z",
    )

    assert aigc_studio._seedream_reference_candidates(job)[0] == (
        "https://cdn.example.test/clean-face.png"
    )
    prompt = aigc_studio._image_prompt_from_job(job)
    assert "标注使用规则" in prompt
    assert "不要保留标注线条" in prompt
    assert "红圈是需要调整肤质的脸部区域" in prompt


def test_seedream_reference_candidates_include_ordered_reference_images():
    job = aigc_studio.AigcJob(
        id="job-reference-images-1",
        canvas_id="canvas-1",
        node_id="image-1",
        capability="image_to_image",
        provider_id="volcengine",
        model_id="doubao-seedream-4-5-251128",
        inputs={"prompt": "参考第一张参考图和第二张参考图生成海报"},
        parameters={
            "referenceImages": [
                "https://cdn.example.test/front.png",
                "https://cdn.example.test/back.png",
            ],
        },
        status="queued",
        created_at="2026-06-26T00:00:00Z",
        updated_at="2026-06-26T00:00:00Z",
    )

    assert aigc_studio._seedream_reference_candidates(job)[:2] == [
        "https://cdn.example.test/front.png",
        "https://cdn.example.test/back.png",
    ]


async def test_seedream_libtv_style_annotation_runs_as_prompt_guided_edit(
    tmp_path,
    monkeypatch,
):
    """LibTV-style native effects and annotations should degrade to prompt-guided editing."""
    app = make_seedream_app(tmp_path)
    transport = ASGITransport(app=app)
    calls = {}

    class FakeImages:
        async def generate(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                data=[{"url": "https://cdn.example.test/result.png"}]
            )

    class FakeOpenAIClient:
        images = FakeImages()

    async def fake_download(url):
        return b"result-png", "image/png"

    monkeypatch.setattr(
        aigc_studio,
        "_openai_client",
        lambda api_key, base_url=None: FakeOpenAIClient(),
    )
    monkeypatch.setattr(
        aigc_studio, "_download_remote_asset", fake_download, raising=False
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "LibTV annotation board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "volcengine",
                    "model_id": "doubao-seedream-4-5-251128",
                    "inputs": {
                        "prompt": "脸蛋要加上皮肤质感",
                        "reference_nodes": [
                            {
                                "node_id": "annotation-1",
                                "type": "reference_asset",
                                "title": "标注",
                                "role": "image_annotation",
                                "asset_name": "face-mark.png",
                                "preview_url": "https://cdn.example.test/clean-face.png",
                                "source_preview_url": "https://cdn.example.test/clean-face.png",
                                "annotated_preview_url": "https://cdn.example.test/marked-face.png",
                                "instruction": "红圈是需要调整肤质的脸部区域",
                            }
                        ],
                        "annotations": [
                            {
                                "node_id": "annotation-1",
                                "role": "image_annotation",
                                "source_preview_url": "https://cdn.example.test/clean-face.png",
                                "annotated_preview_url": "https://cdn.example.test/marked-face.png",
                                "instruction": "红圈是需要调整肤质的脸部区域",
                            }
                        ],
                    },
                    "parameters": {
                        "resolution": "2K",
                        "styleRuntimeMode": "native_effect",
                        "styleReferenceName": "人像质感微调",
                        "styleKeywords": "真实肤质, 自然光, 保留五官",
                        "styleDescription": "LibTV-style 人像质感调节，强调局部肤质而非改脸。",
                        "effectTemplateUuids": ["libtv-effect-should-not-be-sent"],
                        "effects": [22910748],
                    },
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    assert calls["extra_body"] == {
        "image": "https://cdn.example.test/clean-face.png",
        "watermark": True,
        "sequential_image_generation": "disabled",
    }
    assert "风格参考：人像质感微调。" in calls["prompt"]
    assert "标注使用规则" in calls["prompt"]
    assert "不要保留标注线条" in calls["prompt"]
    assert "红圈是需要调整肤质的脸部区域" in calls["prompt"]
    assert "参考图使用规则" in calls["prompt"]
    assert "effectTemplateUuids" not in calls
    assert "effects" not in calls


async def test_seedream_native_effect_template_falls_back_to_prompt_style(
    tmp_path,
    monkeypatch,
):
    """Native LibTV effects should still guide Ark Seedream through prompt text."""
    app = make_seedream_app(tmp_path)
    transport = ASGITransport(app=app)
    calls = {}

    class FakeImages:
        async def generate(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(data=[{"url": "https://cdn.example.test/cgv2.png"}])

    class FakeOpenAIClient:
        images = FakeImages()

    monkeypatch.setattr(
        aigc_studio,
        "_openai_client",
        lambda api_key, base_url=None: FakeOpenAIClient(),
    )

    async def fake_download(url):
        return b"cgv2-png", "image/png"

    monkeypatch.setattr(
        aigc_studio,
        "_download_remote_asset",
        fake_download,
        raising=False,
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Image board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "volcengine",
                    "model_id": "doubao-seedream-4-5-251128",
                    "inputs": {"prompt": "18岁少女"},
                    "parameters": {
                        "resolution": "2K",
                        "styleRuntimeMode": "native_effect",
                        "styleReferenceName": "一键国漫CGV2",
                        "styleKeywords": "国漫, CG, 角色海报, 冷色调, 金属质感",
                        "styleDescription": "国漫 CG 风格，突出角色轮廓、冷色调光影、金属质感与高对比氛围。",
                        "effectTemplateUuids": ["dbc6dfc0990d46d28215bcdff87d53c3"],
                        "effects": [22910748],
                    },
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    assert calls["prompt"] == (
        "18岁少女\n\n"
        "风格参考：一键国漫CGV2。\n"
        "风格描述：国漫 CG 风格，突出角色轮廓、冷色调光影、金属质感与高对比氛围。\n"
        "风格关键词：国漫, CG, 角色海报, 冷色调, 金属质感"
    )
    assert calls["extra_body"] == {
        "watermark": True,
    }


async def test_run_seedream_group_job_uses_streaming_sequential_request(
    tmp_path,
    monkeypatch,
):
    """Seedream group image generation should match Volcengine's streaming example."""
    app = make_seedream_app(tmp_path)
    transport = ASGITransport(app=app)
    calls = []

    class FakeSeedreamStream:
        def __aiter__(self):
            self._events = iter(
                [
                    SimpleNamespace(
                        type="image_generation.partial_succeeded",
                        b64_json=base64.b64encode(b"first-png").decode("ascii"),
                    ),
                    SimpleNamespace(
                        type="image_generation.partial_succeeded",
                        b64_json=base64.b64encode(b"second-png").decode("ascii"),
                    ),
                    SimpleNamespace(
                        type="image_generation.completed",
                        usage=SimpleNamespace(generated_images=2),
                    ),
                ],
            )
            return self

        async def __anext__(self):
            try:
                return next(self._events)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class FakeImages:
        async def generate(self, **kwargs):
            calls.append(kwargs)
            return FakeSeedreamStream()

    class FakeOpenAIClient:
        images = FakeImages()

    monkeypatch.setattr(
        aigc_studio,
        "_openai_client",
        lambda api_key, base_url=None: FakeOpenAIClient(),
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Group board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "volcengine",
                    "model_id": "doubao-seedream-4-5-251128",
                    "inputs": {"prompt": "生成一组共4张连贯插画"},
                    "parameters": {"resolution": "2K", "imageCount": 4},
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    job = ran.json()
    assert job["status"] == "succeeded"
    assert calls[0] == {
        "model": "doubao-seedream-4-5-251128",
        "prompt": ("生成一组共4张连贯插画\n\n务必一次生成 4 张图片结果（不是 1 张）。"),
        "size": "2K",
        "response_format": "b64_json",
        "stream": True,
        "extra_body": {
            "watermark": True,
            "sequential_image_generation": "auto",
            "sequential_image_generation_options": {"max_images": 4},
        },
    }
    assert len(calls) == 3
    assert all(
        call["extra_body"]["sequential_image_generation"] == "disabled"
        for call in calls[1:]
    )
    assert [asset["name"] for asset in job["outputs"]] == [
        f"image-1-{job['id']}.1.png",
        f"image-1-{job['id']}.2.png",
    ]
    assert (
        tmp_path / "workspace" / job["outputs"][0]["path"]
    ).read_bytes() == b"first-png"
    assert (
        tmp_path / "workspace" / job["outputs"][1]["path"]
    ).read_bytes() == b"second-png"


async def test_run_seedream_reference_job_embeds_uploaded_asset_as_image(
    tmp_path,
    monkeypatch,
):
    """Seedream reference image generation should send an image data URL in extra_body."""
    app = make_seedream_app(tmp_path)
    transport = ASGITransport(app=app)
    calls = {}
    downloads = []

    class FakeImages:
        async def generate(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                data=[{"url": "https://cdn.example.test/result.png"}]
            )

    class FakeOpenAIClient:
        images = FakeImages()

    async def fake_download(url):
        downloads.append(url)
        return b"result-png", "image/png"

    monkeypatch.setattr(
        aigc_studio,
        "_openai_client",
        lambda api_key, base_url=None: FakeOpenAIClient(),
    )
    monkeypatch.setattr(
        aigc_studio, "_download_remote_asset", fake_download, raising=False
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            uploaded = await client.post(
                "/api/aigc-studio/assets/upload",
                files={"file": ("reference.png", b"reference-png", "image/png")},
            )
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Reference board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "volcengine",
                    "model_id": "doubao-seedream-4-5-251128",
                    "inputs": {
                        "prompt": "生成狗狗趴在草地上的近景画面",
                        "reference_nodes": [
                            {
                                "node_id": "reference-1",
                                "type": "reference_asset",
                                "asset_name": "reference.png",
                                "preview_url": uploaded.json()["url"],
                            }
                        ],
                    },
                    "parameters": {"resolution": "2K", "imageCount": 1},
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    job = ran.json()
    assert job["status"] == "succeeded"
    assert calls["model"] == "doubao-seedream-4-5-251128"
    assert calls["prompt"].startswith("生成狗狗趴在草地上的近景画面")
    assert "参考图使用规则" in calls["prompt"]
    assert "如果参考图是产品或包装" in calls["prompt"]
    assert calls["size"] == "2K"
    assert calls["response_format"] == "url"
    assert calls["extra_body"] == {
        "image": "data:image/png;base64,cmVmZXJlbmNlLXBuZw==",
        "watermark": True,
        "sequential_image_generation": "disabled",
    }
    assert downloads == ["https://cdn.example.test/result.png"]
    assert job["outputs"][0]["meta"]["adapter"] == "volcengine_seedream"


def test_seedream_size_uses_documented_recommended_ratios():
    """Seedream should use Volcengine's documented size table for ratio presets."""
    assert (
        aigc_studio._seedream_size_from_image_parameters(
            {"aspectRatio": "16:9", "resolution": "2K"},
        )
        == "2848x1600"
    )
    assert (
        aigc_studio._seedream_size_from_image_parameters(
            {"aspectRatio": "9:16", "resolution": "3K"},
        )
        == "2304x4096"
    )
    assert (
        aigc_studio._seedream_size_from_image_parameters(
            {"aspectRatio": "21:9", "resolution": "4K"},
        )
        == "6240x2656"
    )
    assert (
        aigc_studio._seedream_size_from_image_parameters(
            {"aspectRatio": "9:21", "resolution": "2K"},
        )
        == "1344x3136"
    )
    assert (
        aigc_studio._seedream_size_from_image_parameters({"resolution": "2K"}) == "2K"
    )


async def test_run_openai_image_job_saves_base64_png(tmp_path, monkeypatch):
    """OpenAI image adapter should decode b64_json outputs into workspace artifacts."""
    app = make_openai_app(tmp_path)
    transport = ASGITransport(app=app)
    calls = {}

    class FakeImages:
        async def generate(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(
                        b64_json=base64.b64encode(b"png-bytes").decode("ascii"),
                    ),
                ],
            )

    class FakeOpenAIClient:
        images = FakeImages()

    monkeypatch.setattr(
        aigc_studio,
        "_openai_client",
        lambda api_key, base_url=None: FakeOpenAIClient(),
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Launch film board",
                    "nodes": [
                        {
                            "id": "image-1",
                            "type": "image_generate",
                            "position": {"x": 120, "y": 80},
                            "data": {"text": "A glossy perfume bottle"},
                        }
                    ],
                    "edges": [],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "openai",
                    "model_id": "gpt-image-2",
                    "inputs": {"prompt": "A glossy perfume bottle"},
                    "parameters": {"size": "1024x1024", "quality": "low"},
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    job = ran.json()
    assert job["status"] == "succeeded"
    assert calls == {
        "model": "gpt-image-2",
        "prompt": "A glossy perfume bottle",
        "size": "1024x1024",
        "quality": "low",
    }
    artifact = tmp_path / "workspace" / job["outputs"][0]["path"]
    assert artifact.suffix == ".png"
    assert artifact.read_bytes() == b"png-bytes"
    assert job["outputs"][0]["url"].endswith(
        f"/api/aigc-studio/assets/{job['outputs'][0]['id']}/file",
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            asset_file = await client.get(job["outputs"][0]["url"])

    assert asset_file.status_code == 200
    assert asset_file.headers["content-type"] == "image/png"
    assert asset_file.content == b"png-bytes"


async def test_run_openai_image_job_maps_image_count_to_n(tmp_path, monkeypatch):
    """OpenAI image adapter should honor the Studio imageCount parameter."""
    app = make_openai_app(tmp_path)
    transport = ASGITransport(app=app)
    calls = {}

    class FakeImages:
        async def generate(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                data=[
                    SimpleNamespace(
                        b64_json=base64.b64encode(f"png-{index}".encode()).decode(
                            "ascii",
                        ),
                    )
                    for index in range(int(kwargs.get("n") or 1))
                ],
            )

    class FakeOpenAIClient:
        images = FakeImages()

    monkeypatch.setattr(
        aigc_studio,
        "_openai_client",
        lambda api_key, base_url=None: FakeOpenAIClient(),
    )

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "Launch film board",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            created = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "openai",
                    "model_id": "gpt-image-2",
                    "inputs": {"prompt": "A glossy perfume bottle"},
                    "parameters": {
                        "size": "1024x1024",
                        "quality": "low",
                        "imageCount": 3,
                    },
                },
            )

            ran = await client.post(
                f"/api/aigc-studio/jobs/{created.json()['id']}/run",
            )

    assert ran.status_code == 200
    job = ran.json()
    assert job["status"] == "succeeded"
    assert calls["n"] == 3
    assert [asset["name"] for asset in job["outputs"]] == [
        f"image-1-{job['id']}.1.png",
        f"image-1-{job['id']}.2.png",
        f"image-1-{job['id']}.3.png",
    ]
    assert [
        (tmp_path / "workspace" / asset["path"]).read_bytes()
        for asset in job["outputs"]
    ] == [b"png-0", b"png-1", b"png-2"]


async def test_aigc_lists_support_status_canvas_and_limit_filters(tmp_path):
    app = make_app(tmp_path)
    transport = ASGITransport(app=app)

    with patch("qwenpaw.app.routers.aigc_studio.STUDIO_ROOT", tmp_path / "studio"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            canvas_a = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "A",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            canvas_b = await client.post(
                "/api/aigc-studio/canvases",
                json={
                    "name": "B",
                    "nodes": [{"id": "image-1", "type": "image_generate"}],
                    "edges": [],
                },
            )
            job_a = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas_a.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "stub-aigc",
                    "model_id": "stub-image",
                    "inputs": {"prompt": "A"},
                },
            )
            await client.post(f"/api/aigc-studio/jobs/{job_a.json()['id']}/run")
            job_b = await client.post(
                "/api/aigc-studio/jobs",
                json={
                    "canvas_id": canvas_b.json()["id"],
                    "node_id": "image-1",
                    "capability": "text_to_image",
                    "provider_id": "stub-aigc",
                    "model_id": "stub-image",
                    "inputs": {"prompt": "B"},
                },
            )
            await client.post(f"/api/aigc-studio/jobs/{job_b.json()['id']}/run")

            jobs = await client.get(
                f"/api/aigc-studio/jobs?canvas_id={canvas_a.json()['id']}&status=queued&limit=1",
            )
            assets = await client.get(
                f"/api/aigc-studio/assets?canvas_id={canvas_a.json()['id']}&limit=1",
            )

    assert jobs.status_code == 200
    assert jobs.json()["jobs"] == []
    assert assets.status_code == 200
    assert [asset["meta"]["canvas_id"] for asset in assets.json()["assets"]] == [
        canvas_a.json()["id"],
    ]
