# -*- coding: utf-8 -*-
"""Authenticated user and trusted-admin credit accounting APIs."""
from __future__ import annotations

from datetime import datetime
import os
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    UsageOrderConflictError,
    UsageOrderStateError,
    UsageService,
    wallet_balance_dict,
)
from ..billing.reporting import (
    BillingReportFilters,
    BillingReportingService,
    ReconciliationConflictError,
    ReconciliationNotFoundError,
    ReconciliationResolution,
    persisted_billing_mode,
)
from ..storage.engine import get_app_engine
from ..storage.repos.billing_repo import BillingRepository
from ..storage.repos.price_catalog_repo import PriceCatalogRepository
from ..storage.schema import create_all


user_router = APIRouter(prefix="/billing", tags=["billing"])
admin_router = APIRouter(prefix="/billing", tags=["admin-billing"])
_MAX_USAGE_TOKENS = 100_000_000
_MAX_USAGE_QUANTITY = 1_000_000


class QuoteRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_key: str = Field(min_length=1, max_length=255)
    provider_id: str = Field(min_length=1, max_length=255)
    model_key: str = Field(min_length=1, max_length=255)
    capability: str = Field(min_length=1, max_length=255)
    parameters: dict[str, Any] = Field(default_factory=dict)
    input_tokens: int = Field(default=0, ge=0, le=_MAX_USAGE_TOKENS)
    output_tokens: int = Field(default=0, ge=0, le=_MAX_USAGE_TOKENS)

    @field_validator("parameters")
    @classmethod
    def validate_usage_quantities(cls, value: dict[str, Any]):
        for key in ("count", "duration", "duration_seconds"):
            amount = value.get(key)
            if (
                isinstance(amount, int)
                and not isinstance(amount, bool)
                and amount > _MAX_USAGE_QUANTITY
            ):
                raise ValueError(f"{key} exceeds the product limit")
        return value


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


class ReconciliationResolutionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    billability: Literal["billable", "not_billable"]
    reason: str = Field(min_length=1, max_length=2000)
    actual_input_tokens: int = Field(default=0, ge=0, le=(1 << 63) - 1)
    actual_output_tokens: int = Field(default=0, ge=0, le=(1 << 63) - 1)


class RolloutActivationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["off", "shadow", "observe", "enforced"]


def get_billing_repository() -> BillingRepository:
    engine = get_app_engine()
    create_all(engine)
    return BillingRepository(engine)


def get_price_catalog_service() -> PriceCatalogService:
    engine = get_app_engine()
    create_all(engine)
    return PriceCatalogService(PriceCatalogRepository(engine))


def get_usage_service() -> UsageService:
    repository = get_billing_repository()
    return UsageService(
        repository,
        get_price_catalog_service(),
        mode=persisted_billing_mode(
            repository,
            fallback=os.environ.get("DCLAW_BILLING_MODE", "shadow"),
        ),
    )


def get_billing_reporting_service() -> BillingReportingService:
    return BillingReportingService(
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


def _report_filters(
    *,
    started_at: datetime | None,
    ended_at: datetime | None,
    model: str | None,
    provider: str | None,
    publication_id: str | None,
    app_id: str | None,
    api_key_id: str | None,
    status: str | None,
    owner_user_id: str | None = None,
) -> BillingReportFilters:
    try:
        return BillingReportFilters(
            started_at=started_at,
            ended_at=ended_at,
            model=model,
            provider=provider,
            publication_id=publication_id,
            app_id=app_id,
            api_key_id=api_key_id,
            status=status,
            owner_user_id=owner_user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _report_page(
    *,
    owner_user_id: str | None,
    filters: BillingReportFilters,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    try:
        return get_billing_reporting_service().list_usage_orders(
            owner_user_id=owner_user_id,
            filters=filters,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
        return service.create_quote(
            owner_id,
            quote_request,
            business_key=payload.business_key,
        )
    except IdempotencyConflictError:
        return JSONResponse(
            status_code=409,
            content={"code": "idempotency_conflict"},
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
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@user_router.get("/usage-orders")
def list_user_usage_orders(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=2048),
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    model: str | None = Query(default=None, min_length=1, max_length=255),
    provider: str | None = Query(default=None, min_length=1, max_length=255),
    publication_id: str
    | None = Query(default=None, min_length=1, max_length=255),
    app_id: str | None = Query(default=None, min_length=1, max_length=255),
    status: str | None = Query(default=None, min_length=1, max_length=64),
) -> dict[str, Any]:
    owner_id = _authenticated_owner(request)
    return _report_page(
        owner_user_id=owner_id,
        filters=_report_filters(
            started_at=started_at,
            ended_at=ended_at,
            model=model,
            provider=provider,
            publication_id=publication_id,
            app_id=app_id,
            api_key_id=None,
            status=status,
        ),
        limit=limit,
        cursor=cursor,
    )


@user_router.get("/usage-orders/{order_id}")
def get_user_usage_order(order_id: str, request: Request) -> dict[str, Any]:
    detail = get_billing_reporting_service().get_usage_order(
        order_id,
        owner_user_id=_authenticated_owner(request),
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Usage order not found")
    return detail


@user_router.get("/open-api-summary")
def get_user_open_api_summary(
    request: Request,
    timezone_name: str = Query(
        default="UTC",
        alias="timezone",
        min_length=1,
        max_length=64,
    ),
) -> dict[str, Any]:
    try:
        return get_billing_reporting_service().open_api_summary(
            _authenticated_owner(request),
            timezone_name=timezone_name,
        )
    except ValueError as exc:
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


@admin_router.get("/usage-orders")
def list_admin_usage_orders(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=2048),
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    model: str | None = Query(default=None, min_length=1, max_length=255),
    provider: str | None = Query(default=None, min_length=1, max_length=255),
    publication_id: str
    | None = Query(default=None, min_length=1, max_length=255),
    app_id: str | None = Query(default=None, min_length=1, max_length=255),
    api_key_id: str | None = Query(default=None, min_length=1, max_length=255),
    owner_user_id: str
    | None = Query(default=None, min_length=1, max_length=255),
    status: str | None = Query(default=None, min_length=1, max_length=64),
) -> dict[str, Any]:
    return _report_page(
        owner_user_id=None,
        filters=_report_filters(
            started_at=started_at,
            ended_at=ended_at,
            model=model,
            provider=provider,
            publication_id=publication_id,
            app_id=app_id,
            api_key_id=api_key_id,
            status=status,
            owner_user_id=owner_user_id,
        ),
        limit=limit,
        cursor=cursor,
    )


@admin_router.get("/usage-orders/{order_id}")
def get_admin_usage_order(order_id: str) -> dict[str, Any]:
    detail = get_billing_reporting_service().get_usage_order(
        order_id,
        owner_user_id=None,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Usage order not found")
    return detail


@admin_router.get("/reconciliation")
def list_admin_reconciliation(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=2048),
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    model: str | None = Query(default=None, min_length=1, max_length=255),
    provider: str | None = Query(default=None, min_length=1, max_length=255),
    publication_id: str
    | None = Query(default=None, min_length=1, max_length=255),
    app_id: str | None = Query(default=None, min_length=1, max_length=255),
    api_key_id: str | None = Query(default=None, min_length=1, max_length=255),
    owner_user_id: str
    | None = Query(default=None, min_length=1, max_length=255),
) -> dict[str, Any]:
    filters = _report_filters(
        started_at=started_at,
        ended_at=ended_at,
        model=model,
        provider=provider,
        publication_id=publication_id,
        app_id=app_id,
        api_key_id=api_key_id,
        status="reconciling",
        owner_user_id=owner_user_id,
    )
    try:
        return get_billing_reporting_service().list_reconciliation(
            filters=filters,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@admin_router.post("/reconciliation/{item_id}/resolve")
def resolve_admin_reconciliation(
    item_id: str,
    payload: ReconciliationResolutionBody,
    request: Request,
    idempotency_key: str = Header(
        min_length=1,
        max_length=255,
        alias="Idempotency-Key",
    ),
) -> dict[str, Any]:
    try:
        return get_billing_reporting_service().resolve_reconciliation(
            item_id,
            actor_id=_authenticated_owner(request),
            resolution=ReconciliationResolution(
                idempotency_key=idempotency_key,
                billability=payload.billability,
                reason=payload.reason,
                actual_input_tokens=payload.actual_input_tokens,
                actual_output_tokens=payload.actual_output_tokens,
            ),
        )
    except ReconciliationNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Reconciliation item not found",
        ) from exc
    except ReconciliationConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail="Idempotency conflict",
        ) from exc
    except UsageOrderConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UsageOrderStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@admin_router.get("/rollout")
def get_admin_rollout() -> dict[str, Any]:
    return get_billing_reporting_service().get_rollout()


@admin_router.post("/rollout/activate")
def activate_admin_rollout(
    payload: RolloutActivationBody,
    request: Request,
) -> dict[str, Any]:
    try:
        return get_billing_reporting_service().activate_rollout(
            payload.mode,
            actor_id=_authenticated_owner(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


__all__ = ["admin_router", "user_router"]
