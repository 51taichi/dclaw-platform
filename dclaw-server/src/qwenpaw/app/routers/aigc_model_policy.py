"""Administrator APIs for AIGC Studio model policies."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from ..aigc.model_policy import (
    AIGC_MODEL_CATEGORIES,
    AigcModelCategory,
    AigcModelPolicyService,
)
from ..billing.model_publication import ModelPublicationService
from ..chat_access import current_user_id
from ..storage.engine import get_app_engine
from ..storage.repos.aigc_model_policy_repo import (
    AigcModelPolicyRepository,
    AigcModelPolicyVersionConflict,
)
from ..storage.repos.price_catalog_repo import PriceCatalogRepository
from .providers import get_provider_manager

router = APIRouter(prefix="/aigc-model-policy", tags=["aigc-model-policy"])


class ModelRefRequest(BaseModel):
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)

    @property
    def key(self) -> tuple[str, str]:
        return self.provider_id, self.model_id


class SaveCategoryRequest(BaseModel):
    version: int | None = Field(default=None, ge=1)
    models: list[ModelRefRequest] = Field(min_length=1)
    default_model: ModelRefRequest

    @model_validator(mode="after")
    def validate_models(self) -> SaveCategoryRequest:
        keys = [model.key for model in self.models]
        if len(keys) != len(set(keys)):
            raise ValueError("selected models must be unique")
        if self.default_model.key not in keys:
            raise ValueError("default model must be selected")
        return self


def get_policy_repository() -> AigcModelPolicyRepository:
    return AigcModelPolicyRepository(get_app_engine())


def get_policy_service(
    repository: Annotated[AigcModelPolicyRepository, Depends(get_policy_repository)],
) -> AigcModelPolicyService:
    catalogs = PriceCatalogRepository(get_app_engine())
    effective = ModelPublicationService(catalogs).effective_pairs() or set()
    return AigcModelPolicyService(
        repository,
        published_pairs=effective,
        priced_pairs=effective,
    )


@router.get("/inventory")
async def inventory(
    request: Request,
    service: Annotated[AigcModelPolicyService, Depends(get_policy_service)],
    manager: Annotated[Any, Depends(get_provider_manager)],
) -> dict[str, Any]:
    del request
    result = await service.inventory(manager)
    return {
        "categories": {
            category: [asdict(item) for item in result.categories[category]]
            for category in AIGC_MODEL_CATEGORIES
        },
        "uncategorized": [asdict(item) for item in result.uncategorized],
    }


@router.get("")
async def policies(
    repository: Annotated[AigcModelPolicyRepository, Depends(get_policy_repository)],
) -> dict[str, Any]:
    return {
        "categories": {
            category: repository.get(category) for category in AIGC_MODEL_CATEGORIES
        }
    }


@router.put("/{category}")
async def save_category(
    category: AigcModelCategory,
    body: SaveCategoryRequest,
    request: Request,
    repository: Annotated[AigcModelPolicyRepository, Depends(get_policy_repository)],
    service: Annotated[AigcModelPolicyService, Depends(get_policy_service)],
    manager: Annotated[Any, Depends(get_provider_manager)],
) -> dict[str, Any]:
    current = repository.get(category)
    existing = {
        (str(item["provider_id"]), str(item["model_id"]))
        for item in (current or {}).get("models", ())
    }
    category_inventory = (await service.inventory(manager)).categories[category]
    candidates = {
        (item.provider_id, item.model_id): item for item in category_inventory
    }
    selected = [model.key for model in body.models]

    for key in selected:
        candidate = candidates.get(key)
        if candidate is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "unknown_aigc_model",
                    "category": category,
                    "provider_id": key[0],
                    "model_id": key[1],
                    "reasons": ["unknown"],
                },
            )
        if not candidate.selectable and key not in existing:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "aigc_model_unavailable",
                    "category": category,
                    "provider_id": key[0],
                    "model_id": key[1],
                    "reasons": list(candidate.reasons),
                },
            )

    if not any(candidates[key].selectable for key in selected):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "no_selectable_aigc_model",
                "category": category,
                "reasons": ["no_selectable_model"],
            },
        )

    try:
        actor = int(current_user_id(request))
    except ValueError:
        actor = None
    try:
        return repository.replace(
            category,
            body.version,
            [model.model_dump() for model in body.models],
            body.default_model.model_dump(),
            actor,
        )
    except AigcModelPolicyVersionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "aigc_model_policy_conflict", "category": category},
        ) from exc
