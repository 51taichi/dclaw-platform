# -*- coding: utf-8 -*-
"""API routes for LLM providers and models."""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Literal, Optional
from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
)
from pydantic import BaseModel, Field

from agentscope_runtime.engine.schemas.exception import (
    AppBaseException,
)

from ..agent_context import get_agent_for_request
from ..utils import schedule_agent_reload
from ...config.config import load_agent_config, save_agent_config
from ...providers.provider import (
    ModelInfo,
    ProviderInfo,
    normalize_embedding_model,
)
from ...config.config import ActiveModelsInfo
from ...providers.provider_manager import ProviderManager
from ...providers.openrouter_provider import OpenRouterProvider
from ...config.config import ModelSlotConfig
from ..chat_access import ensure_chat_access
from ..billing.model_publication import ModelPublicationService
from ..storage.engine import get_app_engine
from ..storage.repos.price_catalog_repo import PriceCatalogRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])

ChatModelName = Literal[
    "OpenAIChatModel",
    "AnthropicChatModel",
    "GeminiChatModel",
]
ModelTestType = Literal["auto", "llm", "image", "video", "embedding"]
AUTO_MODEL_PROVIDER_ID = "auto"
AUTO_MODEL_ID = "routing"

# effective: agent-specific if set, otherwise global
# global: the global model only, ignoring any agent-specific setting
# agent: a specific agent's model only, error if not set
# chat: a specific chat's model
ActiveModelReadScope = Literal["effective", "global", "agent", "chat"]
ActiveModelWriteScope = Literal["global", "agent", "chat"]


async def get_provider_manager(request: Request) -> ProviderManager:
    """Get the provider manager from app state.

    Args:
        request: FastAPI request object
    """
    return request.app.state.provider_manager


class ProviderConfigRequest(BaseModel):
    api_key: Optional[str] = Field(default=None)
    base_url: Optional[str] = Field(default=None)
    chat_model: Optional[ChatModelName] = Field(
        default=None,
        description="Chat model class name for protocol selection",
    )
    generate_kwargs: Optional[dict] = Field(
        default_factory=dict,
        description=(
            "Configuration in json format, will be expanded "
            "and passed to generation calls "
            "(e.g., openai.chat.completions, anthropic.messages)."
        ),
    )
    custom_headers: Optional[Dict[str, str]] = Field(
        default=None,
        description="Custom HTTP headers to include in every API request.",
    )
    disabled: Optional[bool] = Field(
        default=None,
        description="Whether this provider should be disabled.",
    )
    auth_mode: Optional[Literal["api_key", "auth_token"]] = Field(
        default=None,
        description=(
            "Authentication mode: 'api_key' or 'auth_token'. "
            "Only applies to Anthropic-compatible providers."
        ),
    )


class ModelSlotRequest(BaseModel):
    provider_id: str = Field(..., description="Provider to use")
    model: str = Field(..., description="Model identifier")
    scope: ActiveModelWriteScope = Field(
        ...,
        description="Whether to update the global model or a specific agent",
    )
    agent_id: Optional[str] = Field(
        default=None,
        description="Target agent ID when scope is 'agent'",
    )
    chat_id: Optional[str] = Field(
        default=None,
        description="Target chat ID when scope is 'chat'",
    )


class EmbeddingSlotRequest(BaseModel):
    provider_id: str = Field(..., description="Embedding provider to use")
    model: str = Field(..., description="Embedding model identifier")


class CreateCustomProviderRequest(BaseModel):
    id: str = Field(...)
    name: str = Field(...)
    default_base_url: str = Field(default="")
    api_key_prefix: str = Field(default="")
    chat_model: ChatModelName = Field(default="OpenAIChatModel")
    models: List[ModelInfo] = Field(default_factory=list)


class AddModelRequest(BaseModel):
    id: str = Field(...)
    name: str = Field(...)
    model_type: Literal["llm", "image", "video", "embedding"] = Field(
        default="llm",
    )
    is_free: bool = Field(
        default=False,
        description="Whether this model is free to use",
    )
    supports_multimodal: Optional[bool] = Field(
        default=None,
        description="Whether the model supports multimodal input",
    )
    supports_image: Optional[bool] = Field(
        default=None,
        description="Whether the model supports image input",
    )
    supports_video: Optional[bool] = Field(
        default=None,
        description="Whether the model supports video input",
    )
    probe_source: Optional[str] = Field(
        default=None,
        description="Source of capability metadata",
    )
    aigc_capabilities: List[str] = Field(
        default_factory=list,
        description=(
            "AIGC Studio capability tags such as text_to_image, "
            "image_edit, text_to_video, or image_to_video."
        ),
    )
    embedding_protocol: Optional[
        Literal["openai_compatible", "dashscope_multimodal"]
    ] = None
    embedding_dimensions: Optional[int] = Field(default=None, ge=1)
    embedding_base_url: Optional[str] = None


class ModelConfigRequest(BaseModel):
    generate_kwargs: Optional[dict] = Field(
        default=None,
        description=(
            "Per-model generation parameters in JSON format. "
            "These override provider-level generate_kwargs."
        ),
    )
    aigc_capabilities: Optional[List[str]] = Field(
        default=None,
        description="AIGC Studio capability tags exposed by this model.",
    )


def _validate_model_slot(
    manager: ProviderManager,
    provider_id: str,
    model_id: str,
) -> None:
    """Validate that the provider and model exist without mutating state."""
    if provider_id == AUTO_MODEL_PROVIDER_ID and model_id == AUTO_MODEL_ID:
        return
    provider = manager.get_provider(provider_id)
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_id}' not found.",
        )
    if provider.disabled:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider_id}' is disabled.",
        )
    if not provider.has_model(model_id):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Model '{model_id}' not found in provider '{provider_id}'."
            ),
        )
    selected_model = _registered_model(provider, model_id)
    if selected_model and selected_model.model_type == "embedding":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Model '{model_id}' is an embedding model and cannot be "
                "used as an LLM."
            ),
        )


async def _load_agent_model(
    request: Request,
    agent_id: str,
) -> ModelSlotConfig | None:
    """Load the model configured for a specific agent."""
    workspace = await get_agent_for_request(request, agent_id=agent_id)
    agent_config = load_agent_config(workspace.agent_id)
    return agent_config.active_model


@router.get(
    "",
    response_model=List[ProviderInfo],
    summary="List all providers",
)
async def list_all_providers(
    request: Request,
    include_unpublished: bool = Query(default=False),
    manager: ProviderManager = Depends(get_provider_manager),
) -> List[ProviderInfo]:
    providers = await manager.list_provider_info()
    if include_unpublished:
        if getattr(request.state, "role", None) != "admin":
            raise HTTPException(status_code=403, detail="Admin required")
        return providers
    published = ModelPublicationService(
        PriceCatalogRepository(get_app_engine())
    ).effective_pairs()
    if published is None:
        return providers
    filtered: list[ProviderInfo] = []
    for provider in providers:
        if provider.id == AUTO_MODEL_PROVIDER_ID:
            filtered.append(provider)
            continue
        models = [
            model
            for model in provider.models
            if (provider.id, model.id) in published
        ]
        extra_models = [
            model
            for model in provider.extra_models
            if (provider.id, model.id) in published
        ]
        if models or extra_models:
            filtered.append(
                provider.model_copy(
                    update={"models": models, "extra_models": extra_models}
                )
            )
    return filtered


@router.put(
    "/{provider_id}/config",
    response_model=ProviderInfo,
    summary="Configure a provider",
)
async def configure_provider(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: ProviderConfigRequest = Body(...),
) -> ProviderInfo:
    ok = manager.update_provider(
        provider_id,
        {
            "api_key": body.api_key,
            "base_url": body.base_url,
            "chat_model": body.chat_model,
            "generate_kwargs": body.generate_kwargs,
            "custom_headers": body.custom_headers,
            "disabled": body.disabled,
            "auth_mode": body.auth_mode,
        },
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_id}' not found",
        )

    provider_info = await manager.get_provider_info(provider_id)
    if provider_info is None:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{provider_id}' not found after update",
        )
    return provider_info


@router.post(
    "/custom-providers",
    response_model=ProviderInfo,
    summary="Create a custom provider",
    status_code=201,
)
async def create_custom_provider_endpoint(
    manager: ProviderManager = Depends(get_provider_manager),
    body: CreateCustomProviderRequest = Body(...),
) -> ProviderInfo:
    try:
        provider_info = await manager.add_custom_provider(
            ProviderInfo(
                id=body.id,
                name=body.name,
                base_url=body.default_base_url,
                api_key_prefix=body.api_key_prefix,
                chat_model=body.chat_model,
                extra_models=body.models,
            ),
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return provider_info


class TestConnectionResponse(BaseModel):
    success: bool = Field(..., description="Whether the test passed")
    message: str = Field(..., description="Human-readable result message")


class TestProviderRequest(BaseModel):
    api_key: Optional[str] = Field(
        default=None,
        description="Optional API key to test",
    )
    base_url: Optional[str] = Field(
        default=None,
        description="Optional Base URL to test",
    )
    chat_model: Optional[ChatModelName] = Field(
        default=None,
        description="Optional chat model class to test protocol behavior",
    )
    custom_headers: Optional[Dict[str, str]] = Field(
        default=None,
        description="Custom headers to use for this test request",
    )
    auth_mode: Optional[Literal["api_key", "auth_token"]] = Field(
        default=None,
        description="Authentication mode to use for this test request",
    )


class TestModelRequest(BaseModel):
    model_id: str = Field(..., description="Model ID to test")
    model_type: ModelTestType = Field(
        default="auto",
        description=(
            "How to validate the model. LLM models use chat ping; "
            "AIGC image/video models skip chat ping because validation "
            "requires paid generation endpoints."
        ),
    )


class DiscoverModelsRequest(BaseModel):
    api_key: Optional[str] = Field(
        default=None,
        description="Optional API key to use for discovery",
    )
    base_url: Optional[str] = Field(
        default=None,
        description="Optional Base URL to use for discovery",
    )
    chat_model: Optional[ChatModelName] = Field(
        default=None,
        description="Optional chat model class to use for discovery",
    )


class DiscoverModelsResponse(BaseModel):
    success: bool = Field(..., description="Whether discovery succeeded")
    models: List[ModelInfo] = Field(
        default_factory=list,
        description="Discovered models",
    )
    message: str = Field(
        default="",
        description="Human-readable result message",
    )
    added_count: int = Field(
        default=0,
        description="How many new models were added into provider config",
    )


IMAGE_MODEL_MARKERS = (
    "seedream",
    "gpt-image",
    "dall-e",
    "qwen-image",
)
VIDEO_MODEL_MARKERS = (
    "seedance",
    "wan",
    "kling",
    "text-to-video",
    "image-to-video",
)
IMAGE_CAPABILITIES = {
    "text_to_image",
    "image_to_image",
    "image_edit",
    "mask_edit",
    "reference_image",
}
VIDEO_CAPABILITIES = {
    "text_to_video",
    "image_to_video",
    "reference_video",
}


def _registered_model(provider, model_id: str) -> ModelInfo | None:
    for model in list(getattr(provider, "models", []) or []) + list(
        getattr(provider, "extra_models", []) or [],
    ):
        if getattr(model, "id", None) == model_id:
            return model
    return None


def _model_test_type(
    provider,
    model_id: str,
    requested: ModelTestType,
) -> ModelTestType:
    if requested != "auto":
        return requested

    model = _registered_model(provider, model_id)
    if model and model.model_type == "embedding":
        return "embedding"
    capabilities = set(getattr(model, "aigc_capabilities", []) or [])
    if capabilities.intersection(IMAGE_CAPABILITIES):
        return "image"
    if capabilities.intersection(VIDEO_CAPABILITIES):
        return "video"

    normalized_id = model_id.lower()
    if any(marker in normalized_id for marker in IMAGE_MODEL_MARKERS):
        return "image"
    if any(marker in normalized_id for marker in VIDEO_MODEL_MARKERS):
        return "video"
    return "llm"


def _aigc_model_test_response(model_type: ModelTestType) -> TestConnectionResponse:
    label = "image" if model_type == "image" else "video"
    return TestConnectionResponse(
        success=True,
        message=(
            f"AIGC {label} model registered; skipped chat ping. "
            "Use an AIGC generation run to validate the provider endpoint."
        ),
    )


def _embedding_model_for_test(provider_id: str, model_id: str) -> ModelInfo:
    normalized = model_id.lower()
    dashscope_multimodal = provider_id == "dashscope" and (
        "vl-embedding" in normalized
        or "embedding-vision" in normalized
        or "multimodal-embedding" in normalized
    )
    model = ModelInfo(
        id=model_id,
        name=model_id,
        model_type="embedding",
        embedding_protocol=(
            "dashscope_multimodal"
            if dashscope_multimodal
            else "openai_compatible"
        ),
    )
    return normalize_embedding_model(provider_id, model)


async def _test_embedding_model(provider, model: ModelInfo) -> tuple[bool, str]:
    from ...mindspace.embeddings import MindspaceEmbedder

    try:
        embedder = MindspaceEmbedder.from_provider_model(provider, model)
        vector = await asyncio.to_thread(
            embedder.embed_query,
            "knowledge embedding connection test",
        )
        if not vector:
            return False, "Embedding API returned an empty vector."
        return True, f"Embedding connection successful ({len(vector)} dimensions)"
    except Exception as exc:
        return False, str(exc)


@router.post(
    "/{provider_id}/test",
    response_model=TestConnectionResponse,
    summary="Test provider connection",
)
async def test_provider(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: Optional[TestProviderRequest] = Body(default=None),
) -> TestConnectionResponse:
    """Test if a provider's URL and API key are valid."""
    try:
        provider = manager.get_provider(provider_id)
        if provider is None:
            raise ValueError(f"Provider '{provider_id}' not found")
        # Build a lightweight Pydantic copy with only the overridden fields;
        # avoids deepcopy which fails when _strip_http_client is cached.
        overrides: dict = {}
        if body and body.api_key:
            overrides["api_key"] = body.api_key
        if body and body.base_url:
            overrides["base_url"] = body.base_url
        if body and body.custom_headers is not None:
            overrides["custom_headers"] = body.custom_headers
        if body and body.auth_mode in ("api_key", "auth_token"):
            overrides["auth_mode"] = body.auth_mode
        tmp_provider = provider.model_copy(update=overrides)
        ok, msg = await tmp_provider.check_connection()
        return TestConnectionResponse(
            success=ok,
            message=(
                "Connection successful" if ok else f"Connection failed: {msg}"
            ),
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{provider_id}/discover",
    response_model=DiscoverModelsResponse,
    summary="Discover available models from provider",
)
async def discover_models(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: Optional[DiscoverModelsRequest] = Body(default=None),
    save: bool = Query(
        default=True,
        description="Save discovered models to provider",
    ),
) -> DiscoverModelsResponse:
    try:
        provider = manager.get_provider(provider_id)
        if provider is None:
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{provider_id}' not found",
            )

        existing_model_ids = {
            model.id for model in provider.models + provider.extra_models
        }

        ok = manager.update_provider(
            provider_id,
            {
                "api_key": body.api_key if body else None,
                "base_url": body.base_url if body else None,
            },
        )
        if not ok:
            raise HTTPException(
                status_code=404,
                detail=f"Provider '{provider_id}' not found",
            )
        try:
            result = await manager.fetch_provider_models(
                provider_id,
                save=save,
            )
            success = True
        except Exception:
            result = []
            success = False

        added_count = 0
        if save and success:
            added_count = sum(
                1 for model in result if model.id not in existing_model_ids
            )

        return DiscoverModelsResponse(
            success=success,
            models=result,
            added_count=added_count,
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/{provider_id}/models/test",
    response_model=TestConnectionResponse,
    summary="Test a specific model",
)
async def test_model(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: TestModelRequest = Body(...),
) -> TestConnectionResponse:
    """Test if a specific model works with the configured provider."""
    try:
        provider = manager.get_provider(provider_id)
        if provider is None:
            raise ValueError(f"Provider '{provider_id}' not found")
        model_type = _model_test_type(
            provider,
            body.model_id,
            body.model_type,
        )
        if model_type in {"image", "video"}:
            return _aigc_model_test_response(model_type)
        if model_type == "embedding":
            model = _registered_model(provider, body.model_id)
            if not model:
                model = _embedding_model_for_test(provider_id, body.model_id)
            else:
                model = normalize_embedding_model(provider_id, model)
            ok, msg = await _test_embedding_model(provider, model)
            if ok and _registered_model(provider, body.model_id):
                await manager.update_model_config(
                    provider_id,
                    body.model_id,
                    {
                        "model_type": model.model_type,
                        "embedding_protocol": model.embedding_protocol,
                        "embedding_dimensions": model.embedding_dimensions,
                    },
                )
            return TestConnectionResponse(success=ok, message=msg)
        ok, msg = await provider.check_model_connection(model_id=body.model_id)
        return TestConnectionResponse(
            success=ok,
            message=(
                "Model connection successful"
                if ok
                else f"Model connection failed: {msg}"
            ),
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/custom-providers/{provider_id}",
    response_model=List[ProviderInfo],
    summary="Delete a custom provider",
)
async def delete_custom_provider_endpoint(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
) -> List[ProviderInfo]:
    try:
        ok = manager.remove_custom_provider(provider_id)
        if not ok:
            raise ValueError(f"Custom Provider '{provider_id}' not found")
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await manager.list_provider_info()


@router.post(
    "/{provider_id}/models",
    response_model=ProviderInfo,
    summary="Add a model to a provider",
    status_code=201,
)
async def add_model_endpoint(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    body: AddModelRequest = Body(...),
) -> ProviderInfo:
    try:
        model_info = normalize_embedding_model(
            provider_id,
            ModelInfo(
                id=body.id,
                name=body.name,
                model_type=body.model_type,
                supports_multimodal=body.supports_multimodal,
                supports_image=body.supports_image,
                supports_video=body.supports_video,
                probe_source=body.probe_source,
                is_free=body.is_free,
                aigc_capabilities=body.aigc_capabilities,
                embedding_protocol=body.embedding_protocol,
                embedding_dimensions=body.embedding_dimensions,
                embedding_base_url=body.embedding_base_url,
            ),
        )
        provider = await manager.add_model_to_provider(
            provider_id=provider_id,
            model_info=model_info,
        )  # Validate provider exists and add model
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return provider


class ProbeMultimodalResponse(BaseModel):
    supports_image: bool = Field(
        default=False,
        description="Whether the model supports image input",
    )
    supports_video: bool = Field(
        default=False,
        description="Whether the model supports video input",
    )
    supports_multimodal: bool = Field(
        default=False,
        description="Whether the model supports any multimodal input",
    )
    image_message: str = Field(
        default="",
        description="Probe result message for image support",
    )
    video_message: str = Field(
        default="",
        description="Probe result message for video support",
    )


@router.post(
    "/{provider_id}/models/{model_id:path}/probe-multimodal",
    response_model=ProbeMultimodalResponse,
    summary="Probe model multimodal capability",
)
async def probe_model_multimodal(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    model_id: str = Path(...),
) -> ProbeMultimodalResponse:
    """Probe image and video support by sending lightweight test requests."""
    result = await manager.probe_model_multimodal(provider_id, model_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return ProbeMultimodalResponse(**result)


@router.delete(
    "/{provider_id}/models/{model_id:path}",
    response_model=ProviderInfo,
    summary="Remove a model from a provider",
)
async def remove_model_endpoint(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    model_id: str = Path(...),
) -> ProviderInfo:
    try:
        provider = await manager.delete_model_from_provider(
            provider_id=provider_id,
            model_id=model_id,
        )  # Validate provider and model exist and delete
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return provider


@router.put(
    "/{provider_id}/models/{model_id:path}/config",
    response_model=ProviderInfo,
    summary="Configure per-model generation parameters",
)
async def configure_model(
    manager: ProviderManager = Depends(get_provider_manager),
    provider_id: str = Path(...),
    model_id: str = Path(...),
    body: ModelConfigRequest = Body(...),
) -> ProviderInfo:
    """Update per-model generate_kwargs that override provider-level
    settings."""
    try:
        config: dict[str, object] = {}
        if body.generate_kwargs is not None:
            config["generate_kwargs"] = body.generate_kwargs
        if body.aigc_capabilities is not None:
            config["aigc_capabilities"] = body.aigc_capabilities
        provider_info = await manager.update_model_config(
            provider_id=provider_id,
            model_id=model_id,
            config=config,
        )
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return provider_info


@router.put(
    "/active-embedding",
    response_model=ActiveModelsInfo,
    summary="Set the global knowledge Embedding model",
)
async def set_active_embedding_model(
    manager: ProviderManager = Depends(get_provider_manager),
    body: EmbeddingSlotRequest = Body(...),
) -> ActiveModelsInfo:
    provider = manager.get_provider(body.provider_id)
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{body.provider_id}' not found",
        )
    if provider.disabled:
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{body.provider_id}' is disabled.",
        )
    model = _registered_model(provider, body.model)
    if model is None or model.model_type != "embedding":
        raise HTTPException(
            status_code=400,
            detail=f"Model '{body.model}' is not classified as embedding.",
        )
    model = normalize_embedding_model(body.provider_id, model)
    ok, message = await _test_embedding_model(provider, model)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    try:
        await manager.update_model_config(
            body.provider_id,
            body.model,
            {
                "model_type": model.model_type,
                "embedding_protocol": model.embedding_protocol,
                "embedding_dimensions": model.embedding_dimensions,
            },
        )
        await manager.activate_embedding_model(body.provider_id, body.model)
    except (ValueError, AppBaseException) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ActiveModelsInfo(
        active_llm=manager.get_active_model(),
        active_embedding=manager.get_active_embedding_model(),
    )


@router.delete(
    "/active-embedding",
    response_model=ActiveModelsInfo,
    summary="Disable semantic Embedding for knowledge search",
)
async def clear_active_embedding_model(
    manager: ProviderManager = Depends(get_provider_manager),
) -> ActiveModelsInfo:
    manager.clear_active_embedding_model()
    return ActiveModelsInfo(
        active_llm=manager.get_active_model(),
        active_embedding=None,
    )


@router.get(
    "/active",
    response_model=ActiveModelsInfo,
    summary="Get effective active LLM",
)
async def get_active_models(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    scope: ActiveModelReadScope = Query(default="effective"),
    agent_id: Optional[str] = Query(default=None),
    chat_id: Optional[str] = Query(default=None),
) -> ActiveModelsInfo:
    """Get active model by scope.

    - effective: agent-specific first, otherwise global fallback
    - global: ProviderManager global model only
    - agent: a specific agent's configured model only
    """
    if scope == "global":
        return ActiveModelsInfo(
            active_llm=manager.get_active_model(),
            active_embedding=manager.get_active_embedding_model(),
        )

    if scope == "agent":
        if not agent_id:
            raise HTTPException(
                status_code=400,
                detail="agent_id is required when scope is 'agent'",
            )
        return ActiveModelsInfo(
            active_llm=await _load_agent_model(request, agent_id),
        )

    if scope in ("chat", "effective") and chat_id:
        workspace = await get_agent_for_request(request)
        chat_row = ensure_chat_access(request, chat_id)
        chat = await workspace.chat_manager.get_chat(str(chat_row["id"]))
        if chat and "active_model" in chat.meta:
            chat_model = chat.meta["active_model"]
            if not chat_model:
                if scope == "chat":
                    return ActiveModelsInfo(active_llm=None)
            elif (
                isinstance(chat_model, dict)
                and chat_model.get("provider_id")
                and chat_model.get("model")
            ):
                return ActiveModelsInfo(
                    active_llm=ModelSlotConfig(
                        provider_id=chat_model.get("provider_id"),
                        model=chat_model.get("model"),
                    )
                )
            elif scope == "chat":
                return ActiveModelsInfo(active_llm=None)

    if scope == "chat":
        # If chat scope is specifically requested but no override exists, fall back to agent
        pass

    try:
        target_agent_id = agent_id
        if target_agent_id is None:
            workspace = await get_agent_for_request(request)
            target_agent_id = workspace.agent_id

        agent_model = await _load_agent_model(request, target_agent_id)
        if agent_model:
            logger.info(
                "Returning agent-specific model for %s: %s",
                target_agent_id,
                agent_model,
            )
            return ActiveModelsInfo(active_llm=agent_model)
    except (
        HTTPException,
        OSError,
        ValueError,
        TypeError,
        AppBaseException,
    ) as exc:
        logger.warning(
            "Failed to get agent-specific model: %s",
            exc,
            exc_info=True,
        )

    global_model = manager.get_active_model()
    logger.info("Returning global model: %s", global_model)
    return ActiveModelsInfo(active_llm=global_model)


@router.put(
    "/active",
    response_model=ActiveModelsInfo,
    summary="Set active LLM",
)
async def set_active_model(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    body: ModelSlotRequest = Body(...),
) -> ActiveModelsInfo:
    """Set active model by scope."""
    is_auto_slot = (
        body.provider_id == AUTO_MODEL_PROVIDER_ID
        and body.model == AUTO_MODEL_ID
    )
    if body.scope == "global":
        if is_auto_slot:
            raise HTTPException(
                status_code=400,
                detail="Auto routing can only be set for agent or chat scope",
            )
        try:
            await manager.activate_model(body.provider_id, body.model)
        except (
            FileNotFoundError,
            RuntimeError,
            ValueError,
            AppBaseException,
        ) as exc:
            message = str(exc)
            lower_msg = message.lower()
            if "provider" in lower_msg and "not found" in lower_msg:
                raise HTTPException(status_code=404, detail=message) from exc
            raise HTTPException(status_code=400, detail=message) from exc
        return ActiveModelsInfo(active_llm=manager.get_active_model())

    if body.scope == "chat":
        if not body.chat_id:
            raise HTTPException(
                status_code=400,
                detail="chat_id is required when scope is 'chat'",
            )

        if not is_auto_slot:
            _validate_model_slot(manager, body.provider_id, body.model)
        workspace = await get_agent_for_request(request)
        chat_row = ensure_chat_access(request, body.chat_id)

        from ..runner.models import ChatUpdate
        await workspace.chat_manager.patch_chat(
            str(chat_row["id"]),
            ChatUpdate(
                meta={
                    "active_model": {
                        "provider_id": body.provider_id,
                        "model": body.model,
                    },
                },
            ),
        )

        if not is_auto_slot:
            manager.maybe_probe_multimodal(body.provider_id, body.model)
        return ActiveModelsInfo(
            active_llm=ModelSlotConfig(
                provider_id=body.provider_id,
                model=body.model,
            ),
        )

    if not body.agent_id:
        raise HTTPException(
            status_code=400,
            detail="agent_id is required when scope is 'agent'",
        )

    if not is_auto_slot:
        _validate_model_slot(manager, body.provider_id, body.model)

    try:
        workspace = await get_agent_for_request(
            request,
            agent_id=body.agent_id,
        )
        agent_config = load_agent_config(workspace.agent_id)
        agent_config.active_model = ModelSlotConfig(
            provider_id=body.provider_id,
            model=body.model,
        )
        save_agent_config(workspace.agent_id, agent_config)
        # Hot reload agent (async, non-blocking)
        schedule_agent_reload(request, workspace.agent_id)

    except (
        HTTPException,
        OSError,
        ValueError,
        TypeError,
        AppBaseException,
    ) as exc:
        logger.warning(
            "Failed to save active model to agent config: %s",
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to save active model to agent config",
        ) from exc

    if not is_auto_slot:
        manager.maybe_probe_multimodal(body.provider_id, body.model)

    return ActiveModelsInfo(
        active_llm=ModelSlotConfig(
            provider_id=body.provider_id,
            model=body.model,
        ),
    )


@router.delete(
    "/active",
    summary="Clear active LLM override",
)
async def clear_active_model(
    request: Request,
    manager: ProviderManager = Depends(get_provider_manager),
    scope: ActiveModelWriteScope = Query(...),
    agent_id: Optional[str] = Query(default=None),
    chat_id: Optional[str] = Query(default=None),
):
    """Clear active model override for a specific chat or agent."""
    if scope == "global":
        raise HTTPException(
            status_code=400,
            detail="Cannot clear global model",
        )

    if scope == "chat":
        if not chat_id:
            raise HTTPException(
                status_code=400,
                detail="chat_id is required when scope is 'chat'",
            )
        workspace = await get_agent_for_request(request)
        chat_row = ensure_chat_access(request, chat_id)
        from ..runner.models import ChatUpdate
        await workspace.chat_manager.patch_chat(
            str(chat_row["id"]),
            ChatUpdate(meta={"active_model": None})
        )
        return {"status": "success"}

    if not agent_id:
        raise HTTPException(
            status_code=400,
            detail="agent_id is required when scope is 'agent'",
        )

    try:
        workspace = await get_agent_for_request(request, agent_id=agent_id)
        agent_config = load_agent_config(workspace.agent_id)
        agent_config.active_model = None
        save_agent_config(workspace.agent_id, agent_config)
        schedule_agent_reload(request, workspace.agent_id)
    except Exception as exc:
        logger.warning(
            "Failed to clear active model from agent config: %s",
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to clear active model from agent config",
        ) from exc

    return {"status": "success"}


# =============================================================================
# OpenRouter-specific endpoints for model discovery with filtering
# =============================================================================


class FilterModelsRequest(BaseModel):
    """Request model for filtering OpenRouter models."""

    providers: List[str] = Field(
        default_factory=list,
        description="Filter by provider/series (e.g., ['openai', 'google'])",
    )
    input_modalities: List[str] = Field(
        default_factory=list,
        description="Required input modalities (e.g., ['image'])",
    )
    output_modalities: List[str] = Field(
        default_factory=list,
        description="Required output modalities (e.g., ['text'])",
    )
    max_prompt_price: Optional[float] = Field(
        default=None,
        description="Maximum prompt price per 1M tokens (e.g., 0.000001)",
    )
    is_free: Optional[bool] = Field(
        default=None,
        description="Whether to return only free models",
    )


class SeriesResponse(BaseModel):
    """Response model for available series/providers."""

    series: List[str] = Field(
        default_factory=list,
        description="Provider series (e.g., ['openai', 'google'])",
    )


class DiscoverExtendedResponse(BaseModel):
    """Response model for extended model discovery."""

    success: bool = Field(..., description="Whether discovery succeeded")
    models: List[dict] = Field(
        default_factory=list,
        description="Discovered models with extended metadata",
    )
    providers: List[str] = Field(
        default_factory=list,
        description="Available provider series",
    )
    total_count: int = Field(
        default=0,
        description="Total number of models discovered",
    )


class FilterModelsResponse(BaseModel):
    """Response model for filtered models."""

    success: bool = Field(..., description="Whether filtering succeeded")
    models: List[dict] = Field(
        default_factory=list,
        description="Filtered models with extended metadata",
    )
    total_count: int = Field(
        default=0,
        description="Total number of models matching filters",
    )


@router.get(
    "/openrouter/series",
    response_model=SeriesResponse,
    summary="Get available OpenRouter provider series",
)
async def get_openrouter_series(
    manager: ProviderManager = Depends(get_provider_manager),
) -> SeriesResponse:
    """Get list of available provider/series from OpenRouter."""
    provider = manager.get_provider("openrouter")
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail="OpenRouter provider not found",
        )

    if not isinstance(provider, OpenRouterProvider):
        raise HTTPException(
            status_code=400,
            detail="Provider is not an OpenRouter provider",
        )

    try:
        series = await provider.get_available_providers()
        return SeriesResponse(series=series)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch series: {str(exc)}",
        ) from exc


@router.post(
    "/openrouter/discover-extended",
    response_model=DiscoverExtendedResponse,
    summary="Discover OpenRouter models with extended metadata",
)
async def discover_openrouter_extended(
    manager: ProviderManager = Depends(get_provider_manager),
    body: Optional[DiscoverModelsRequest] = Body(default=None),
) -> DiscoverExtendedResponse:
    """Discover available models from OpenRouter with full metadata."""
    provider = manager.get_provider("openrouter")
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail="OpenRouter provider not found",
        )

    if not isinstance(provider, OpenRouterProvider):
        raise HTTPException(
            status_code=400,
            detail="Provider is not an OpenRouter provider",
        )

    if body and body.api_key:
        manager.update_provider("openrouter", {"api_key": body.api_key})

    try:
        models = await provider.fetch_extended_models()
        providers = await provider.get_available_providers()

        models_dict = [
            {
                "id": m.id,
                "name": m.name,
                "supports_multimodal": m.supports_multimodal,
                "supports_image": m.supports_image,
                "supports_video": m.supports_video,
                "probe_source": m.probe_source,
                "is_free": m.is_free,
                "provider": m.provider,
                "input_modalities": m.input_modalities,
                "output_modalities": m.output_modalities,
                "pricing": m.pricing,
            }
            for m in models
        ]

        return DiscoverExtendedResponse(
            success=True,
            models=models_dict,
            providers=providers,
            total_count=len(models_dict),
        )
    except Exception:
        return DiscoverExtendedResponse(
            success=False,
            models=[],
            providers=[],
            total_count=0,
        )


@router.post(
    "/openrouter/models/filter",
    response_model=FilterModelsResponse,
    summary="Filter OpenRouter models by criteria",
)
async def filter_openrouter_models(
    manager: ProviderManager = Depends(get_provider_manager),
    body: FilterModelsRequest = Body(...),
) -> FilterModelsResponse:
    """Filter OpenRouter models by provider, modalities, and price."""
    provider = manager.get_provider("openrouter")
    if provider is None:
        raise HTTPException(
            status_code=404,
            detail="OpenRouter provider not found",
        )

    if not isinstance(provider, OpenRouterProvider):
        raise HTTPException(
            status_code=400,
            detail="Provider is not an OpenRouter provider",
        )

    try:
        models = await provider.fetch_extended_models()

        filtered_models = provider.filter_models(
            models=models,
            providers=body.providers if body.providers else None,
            input_modalities=(
                body.input_modalities if body.input_modalities else None
            ),
            output_modalities=(
                body.output_modalities if body.output_modalities else None
            ),
            max_prompt_price=body.max_prompt_price,
            is_free=body.is_free,
        )

        models_dict = [
            {
                "id": m.id,
                "name": m.name,
                "supports_multimodal": m.supports_multimodal,
                "supports_image": m.supports_image,
                "supports_video": m.supports_video,
                "probe_source": m.probe_source,
                "is_free": m.is_free,
                "provider": m.provider,
                "input_modalities": m.input_modalities,
                "output_modalities": m.output_modalities,
                "pricing": m.pricing,
            }
            for m in filtered_models
        ]

        return FilterModelsResponse(
            success=True,
            models=models_dict,
            total_count=len(models_dict),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to filter models: {str(exc)}",
        ) from exc
