# -*- coding: utf-8 -*-
"""Authenticated user and trusted-admin credit accounting APIs."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..billing.pricing import (
    CatalogImmutableError,
    CatalogNotFoundError,
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
    PriceRuleNotFoundError,
    QuoteRequest,
)
from ..billing.usage import (
    IdempotencyConflictError,
    InsufficientUsageCreditsError,
    UsageOrderConflictError,
    UsageOrderStateError,
    UsageService,
    wallet_balance_dict,
)
from ..storage.engine import get_app_engine
from ..storage.repos.billing_repo import BillingRepository
from ..storage.repos.price_catalog_repo import PriceCatalogRepository
from ..storage.schema import create_all


user_router = APIRouter(prefix="/billing", tags=["billing"])
admin_router = APIRouter(prefix="/billing", tags=["admin-billing"])


class QuoteRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_key: str = Field(min_length=1, max_length=255)
    provider_id: str = Field(min_length=1, max_length=255)
    model_key: str = Field(min_length=1, max_length=255)
    capability: str = Field(min_length=1, max_length=255)
    parameters: dict[str, Any] = Field(default_factory=dict)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class PriceRuleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=255)
    provider_id: str = Field(min_length=1, max_length=255)
    model_key: str = Field(min_length=1, max_length=255)
    capability: str = Field(min_length=1, max_length=255)
    unit_type: str
    priority: int = Field(default=0, ge=0)
    unit_size: int = Field(default=1, gt=0)
    credits_per_unit: int = Field(default=0, ge=0)
    input_credits_per_1k: int = Field(default=0, ge=0)
    output_credits_per_1k: int = Field(default=0, ge=0)
    parameter_match: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_domain(self) -> PriceRule:
        return PriceRule(**self.model_dump())


class CatalogDraftBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=255)
    effective_at: datetime
    rules: list[PriceRuleBody] = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


def get_billing_repository() -> BillingRepository:
    engine = get_app_engine()
    create_all(engine)
    return BillingRepository(engine)


def get_price_catalog_service() -> PriceCatalogService:
    engine = get_app_engine()
    create_all(engine)
    return PriceCatalogService(PriceCatalogRepository(engine))


def get_usage_service() -> UsageService:
    return UsageService(
        get_billing_repository(),
        get_price_catalog_service(),
    )


def _authenticated_owner(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return str(user_id)


def _wallet_for_owner(
    repository: BillingRepository,
    owner_id: str,
) -> dict[str, Any]:
    wallet = repository.get_wallet("user", owner_id)
    if wallet is None:
        raise HTTPException(status_code=404, detail="Wallet not found")
    return wallet


def _ledger_page(
    repository: BillingRepository,
    wallet_id: str,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    try:
        items = repository.list_ledger(wallet_id, limit, cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "items": items,
        "next_cursor": items[-1]["id"] if len(items) == limit else None,
    }


@user_router.get("/wallet")
def get_user_wallet(request: Request) -> dict[str, int]:
    owner_id = _authenticated_owner(request)
    repository = get_billing_repository()
    wallet = repository.ensure_wallet("user", owner_id)
    return wallet_balance_dict(repository.balance(str(wallet["id"])))


@user_router.get("/ledger")
def get_user_ledger(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
) -> dict[str, Any]:
    owner_id = _authenticated_owner(request)
    repository = get_billing_repository()
    wallet = repository.ensure_wallet("user", owner_id)
    return _ledger_page(repository, str(wallet["id"]), limit, cursor)


@user_router.post("/quotes")
def create_user_quote(
    payload: QuoteRequestBody,
    request: Request,
):
    owner_id = _authenticated_owner(request)
    service = get_usage_service()
    quote_request = QuoteRequest(
        payload.provider_id,
        payload.model_key,
        payload.capability,
        payload.parameters,
        input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
    )
    try:
        order = service.create_quote(
            owner_id,
            quote_request,
            business_key=payload.business_key,
        )
        if order["id"] is not None and order["status"] == "quoted":
            order = service.hold(str(order["id"]))
        elif order["id"] is not None and order["status"] not in {
            "held",
            "captured",
            "released",
        }:
            raise UsageOrderStateError(
                f"cannot replay usage order in state: {order['status']}",
            )
        return order
    except InsufficientUsageCreditsError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "code": "insufficient_credits",
                "required_credits": exc.required,
                "available_credits": exc.available,
            },
        )
    except IdempotencyConflictError:
        return JSONResponse(
            status_code=409,
            content={"code": "idempotency_conflict"},
        )
    except UsageOrderStateError as exc:
        return JSONResponse(
            status_code=409,
            content={"code": "usage_state_conflict", "detail": str(exc)},
        )
    except UsageOrderConflictError:
        return JSONResponse(
            status_code=409,
            content={"code": "business_key_conflict"},
        )
    except CatalogNotFoundError:
        return JSONResponse(
            status_code=503,
            content={"code": "catalog_not_ready"},
        )
    except PriceRuleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@admin_router.post("/catalogs/drafts", status_code=201)
def create_catalog_draft(
    payload: CatalogDraftBody,
    request: Request,
) -> dict[str, str]:
    service = get_price_catalog_service()
    actor_id = _authenticated_owner(request)
    draft = PriceCatalogDraft(
        version=payload.version,
        effective_at=payload.effective_at,
        rules=tuple(rule.to_domain() for rule in payload.rules),
        created_by=f"admin:{actor_id}",
        metadata=payload.metadata,
    )
    try:
        return {"id": service.create_draft(draft), "status": "draft"}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@admin_router.post("/catalogs/{catalog_id}/publish")
def publish_catalog(catalog_id: str) -> dict[str, Any]:
    try:
        return get_price_catalog_service().publish_draft(catalog_id)
    except CatalogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CatalogImmutableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@admin_router.get("/catalogs")
def list_catalogs() -> list[dict[str, Any]]:
    return get_price_catalog_service().list_catalogs()


@admin_router.get("/wallets/{owner_id}")
def get_admin_wallet(owner_id: str) -> dict[str, Any]:
    repository = get_billing_repository()
    wallet = _wallet_for_owner(repository, owner_id)
    return {
        "owner": {"type": "user", "id": owner_id},
        "balance": wallet_balance_dict(
            repository.balance(str(wallet["id"])),
        ),
    }


@admin_router.get("/wallets/{owner_id}/ledger")
def get_admin_wallet_ledger(
    owner_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
) -> dict[str, Any]:
    repository = get_billing_repository()
    wallet = _wallet_for_owner(repository, owner_id)
    return _ledger_page(repository, str(wallet["id"]), limit, cursor)


__all__ = ["admin_router", "user_router"]
