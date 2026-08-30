# -*- coding: utf-8 -*-
"""Authenticated user and trusted-admin credit accounting APIs."""

from __future__ import annotations

from datetime import date, datetime
import os
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..billing.pricing import (
    CatalogNotFoundError,
    ModelNotPricedError,
    PriceCatalogService,
    PriceRuleNotFoundError,
    QuoteRequest,
)
from ..billing.pricing_unlock import (
    PersistentPricingUnlockLimiter,
    PricingUnlockDenied,
    PricingUnlockService,
)
from ..billing.pricing_admin import PricingAdminService
from ..billing.pricing_inventory import PricingModelInventory
from ..billing.pricing_excel import PricingExcelService
from ..billing.official_pricing import OfficialPriceRegistry
from ..billing.pricing_sync import refresh_official_candidates
from ..billing.pricing_sync_runtime import (
    PricingCollectionRuntime,
    build_pricing_collection_runtime,
)
from ..auth import verify_password
from ..billing.usage import (
    IdempotencyConflictError,
    UsageOrderConflictError,
    UsageOrderStateError,
    UsageService,
    wallet_balance_dict,
)
from ..billing.top_up import (
    ReviewCommand,
    SubmitClaimCommand,
    TopUpConflictError,
    TopUpService,
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
from ..storage.repos.pricing_admin_repo import (
    PricingAdminRepository,
    PricingRevisionConflict,
)
from ..storage.repos.user_repo import get_user_repository
from ...providers.provider_manager import ProviderManager
from ..storage.repos.top_up_repo import (
    TopUpIdempotencyConflict,
    TopUpRepository,
)

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


class ReconciliationResolutionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    billability: Literal["billable", "not_billable"]
    reason: str = Field(min_length=1, max_length=2000)
    actual_input_tokens: int = Field(default=0, ge=0, le=(1 << 63) - 1)
    actual_output_tokens: int = Field(default=0, ge=0, le=(1 << 63) - 1)


class RolloutActivationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["off", "shadow", "observe", "enforced"]


class TopUpClaimBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=255)
    payment_channel: Literal["wechat", "alipay", "bank", "other"]
    payer_reference: str = Field(min_length=1, max_length=255)
    customer_note: str | None = Field(default=None, max_length=2000)


class TopUpReviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


class TopUpProductBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    payment_amount_fen: int = Field(gt=0, le=(1 << 63) - 1)
    purchased_credits: int = Field(gt=0, le=(1 << 63) - 1)
    promotional_credits: int = Field(default=0, ge=0, le=(1 << 63) - 1)
    promotional_expiry_days: int | None = Field(default=None, gt=0, le=3650)
    status: Literal["active", "disabled"] = "active"
    display_order: int = Field(default=0, ge=0, le=10000)


class PricingUnlockBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=1024)


class PricingPolicyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_type: Literal["global", "provider", "category", "model"]
    scope_key: str = Field(min_length=1, max_length=512)
    multiplier_decimal: str = Field(pattern=r"^\d+(\.\d+)?$")
    settings: dict[str, Any] = Field(default_factory=dict)
    expected_revision: int = Field(ge=0)


class PricingExclusionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    excluded: bool
    reason: str | None = Field(default=None, max_length=2000)


class PricingModelDecisionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: str = Field(min_length=1, max_length=255)
    model_key: str = Field(min_length=1, max_length=255)
    include_in_publish: bool
    reason: str | None = Field(default=None, max_length=2000)


class PricingModelDecisionsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decisions: list[PricingModelDecisionItem] = Field(min_length=1, max_length=1000)


class PricingBatchDecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_in_publish: bool
    provider_ids: list[str] = Field(default_factory=list, max_length=1000)
    evidence_levels: list[str] = Field(default_factory=list, max_length=10)
    model_keys: list[str] = Field(default_factory=list, max_length=1000)
    reason: str | None = Field(default=None, max_length=2000)


class PricingModelMappingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    official_provider_id: str = Field(min_length=1, max_length=255)
    official_model_id: str = Field(min_length=1, max_length=255)
    expected_revision: int = Field(default=0, ge=0)


def get_billing_repository() -> BillingRepository:
    return BillingRepository(get_app_engine())


def get_price_catalog_service() -> PriceCatalogService:
    return PriceCatalogService(PriceCatalogRepository(get_app_engine()))


def get_pricing_unlock_service() -> PricingUnlockService:
    users = get_user_repository()

    def load_credentials(actor_id: str) -> tuple[str, str, str] | None:
        try:
            user = users.get_user_by_id(int(actor_id))
        except (TypeError, ValueError):
            return None
        if user is None:
            return None
        credentials = users.get_user_credentials(str(user["username"]))
        if credentials is None:
            return None
        return (
            str(credentials["password_hash"]),
            str(credentials["password_salt"]),
            str(user["role"]),
        )

    repository = PricingAdminRepository(get_app_engine())
    return PricingUnlockService(
        repository,
        credential_loader=load_credentials,
        password_verifier=verify_password,
        limiter=PersistentPricingUnlockLimiter(repository),
    )


def get_pricing_admin_service() -> PricingAdminService:
    engine = get_app_engine()
    catalogs = PriceCatalogRepository(engine)
    return PricingAdminService(
        PricingAdminRepository(engine),
        PriceCatalogService(catalogs),
        catalogs,
        PricingModelInventory(ProviderManager.get_instance()),
    )


def get_pricing_collection_runtime() -> PricingCollectionRuntime:
    return build_pricing_collection_runtime(ProviderManager.get_instance())


def get_pricing_excel_service() -> PricingExcelService:
    repository = PricingAdminRepository(get_app_engine())
    admin = get_pricing_admin_service()
    return PricingExcelService(
        repository,
        preview_builder=lambda actor, rows, import_id: (
            admin.preview_initial_catalog(
                actor,
                rows,
                import_id,
                persist=False,
            )
        ),
        confirmation_builder=lambda actor, rows, import_id: (
            admin.preview_initial_catalog(
                actor,
                rows,
                import_id,
                persist=False,
            )
        ),
        draft_builder=admin.preview_initial_catalog,
    )


def require_pricing_unlock(
    request: Request,
    token: str | None = Header(default=None, alias="X-Billing-Unlock"),
) -> str:
    actor_id = _authenticated_owner(request)
    if not token or not get_pricing_unlock_service().is_valid(token, actor_id):
        raise HTTPException(
            status_code=423,
            detail={"code": "pricing_locked", "message": "计费设置尚未解锁"},
        )
    return actor_id


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


def get_top_up_service() -> TopUpService:
    engine = get_app_engine()
    return TopUpService(TopUpRepository(engine), BillingRepository(engine))


def _top_up_product(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row[key]
        for key in (
            "public_id",
            "name",
            "description",
            "payment_amount_fen",
            "purchased_credits",
            "promotional_credits",
            "promotional_expiry_days",
            "status",
            "display_order",
        )
    }


def _top_up_claim(
    row: dict[str, Any],
    *,
    admin: bool = False,
) -> dict[str, Any]:
    result = {
        key: row.get(key)
        for key in (
            "public_id",
            "product_snapshot",
            "payment_amount_fen",
            "payment_channel",
            "payer_reference",
            "customer_note",
            "status",
            "review_reason",
            "reviewed_at",
            "created_at",
            "updated_at",
        )
    }
    if admin:
        result["owner_id"] = row["owner_id"]
        result["reviewed_by"] = row.get("reviewed_by")
    return result


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
    *,
    include_internal: bool,
) -> dict[str, Any]:
    try:
        items = repository.list_ledger(wallet_id, limit, cursor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    serialized = items if include_internal else [_user_ledger_row(row) for row in items]
    return {
        "items": serialized,
        "next_cursor": items[-1]["id"] if len(items) == limit else None,
    }


def _user_ledger_row(row: dict[str, Any]) -> dict[str, Any]:
    """Allowlist the customer ledger view and its non-sensitive metadata."""
    allowed_metadata = {
        "billability",
        "capability",
        "credit_type",
        "expiry_phase",
        "source_type",
        "tier",
    }
    metadata = {
        key: value
        for key, value in dict(row.get("metadata") or {}).items()
        if key in allowed_metadata
        and (value is None or isinstance(value, (str, int, float, bool)))
    }
    return {
        key: row[key]
        for key in (
            "id",
            "event_type",
            "status",
            "credit_delta",
            "cash_delta_fen",
            "business_type",
            "created_at",
        )
    } | {"metadata": metadata}


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
    source: str | None = None,
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
            source=source,
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
    return _ledger_page(
        repository,
        str(wallet["id"]),
        limit,
        cursor,
        include_internal=False,
    )


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
    except ModelNotPricedError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "code": "model_not_priced",
                "provider_id": exc.provider_id,
                "model_key": exc.model_key,
            },
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
    publication_id: str | None = Query(default=None, min_length=1, max_length=255),
    app_id: str | None = Query(default=None, min_length=1, max_length=255),
    status: str | None = Query(default=None, min_length=1, max_length=64),
    source: str | None = Query(default=None, min_length=1, max_length=64),
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
            source=source,
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
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    try:
        return get_billing_reporting_service().open_api_summary(
            _authenticated_owner(request),
            date_from=date_from,
            date_to=date_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@admin_router.post("/pricing/unlock")
def unlock_pricing(
    payload: PricingUnlockBody,
    request: Request,
) -> dict[str, Any]:
    actor_id = _authenticated_owner(request)
    ip_address = request.client.host if request.client else None
    try:
        unlock = get_pricing_unlock_service().unlock(
            actor_id,
            payload.password,
            ip_address,
        )
    except PricingUnlockDenied as exc:
        raise HTTPException(
            status_code=403,
            detail="Invalid admin password",
        ) from exc
    return {"token": unlock.token, "expires_at": unlock.expires_at}


@admin_router.get("/pricing/overview")
def pricing_overview() -> dict[str, Any]:
    return get_pricing_admin_service().overview()


@admin_router.get("/pricing/models")
def pricing_models() -> list[dict[str, Any]]:
    return [
        row.__dict__ for row in get_pricing_admin_service().inventory.list_enabled()
    ]


@admin_router.get("/pricing/history")
def pricing_history() -> list[dict[str, Any]]:
    return get_pricing_admin_service().repository.list_audits()


@admin_router.get("/pricing/policies")
def pricing_policies() -> list[dict[str, Any]]:
    return get_pricing_admin_service().repository.list_policies()


@admin_router.get("/pricing/export")
def export_pricing() -> Response:
    repository = get_pricing_admin_service().repository
    content = get_pricing_excel_service().export_workbook(
        repository.latest_trusted_costs(),
    )
    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": 'attachment; filename="pricing-rmb.xlsx"',
        },
    )


@admin_router.post("/pricing/drafts")
def generate_pricing_draft(
    request: Request,
) -> dict[str, Any]:
    actor_id = _authenticated_owner(request)
    generated = get_pricing_admin_service().generate_draft(actor_id)
    return {key: value for key, value in generated.items() if key != "result"}


@admin_router.get("/pricing/drafts/{draft_key}/export")
def export_pricing_draft(draft_key: str) -> Response:
    generated = get_pricing_admin_service().generate_draft("read-only")
    if generated["draft_key"] != draft_key:
        raise HTTPException(status_code=409, detail="Pricing draft is stale")
    content = get_pricing_excel_service().export_draft(generated["result"])
    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                f'attachment; filename="pricing-draft-{draft_key[:12]}.xlsx"'
            )
        },
    )


@admin_router.put("/pricing/drafts/{draft_key}/exclusions/{provider_id}/{model_key}")
def set_pricing_draft_exclusion(
    draft_key: str,
    provider_id: str,
    model_key: str,
    payload: PricingExclusionBody,
    request: Request,
    actor_id: str = Depends(require_pricing_unlock),
) -> dict[str, Any]:
    try:
        return get_pricing_admin_service().set_exclusion(
            draft_key,
            provider_id,
            model_key,
            payload.excluded,
            payload.reason,
            actor_id,
            request.client.host if request.client else None,
        )
    except ValueError as exc:
        status_code = 409 if "stale" in str(exc) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@admin_router.put("/pricing/drafts/{draft_key}/model-decisions")
def set_pricing_model_decisions(
    draft_key: str,
    payload: PricingModelDecisionsBody,
    request: Request,
    actor_id: str = Depends(require_pricing_unlock),
) -> list[dict[str, Any]]:
    try:
        return get_pricing_admin_service().set_model_decisions(
            draft_key,
            [decision.model_dump() for decision in payload.decisions],
            actor_id,
            request.client.host if request.client else None,
        )
    except ValueError as exc:
        status_code = 409 if "stale" in str(exc) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@admin_router.post("/pricing/drafts/{draft_key}/batch-decision")
def batch_set_pricing_model_decision(
    draft_key: str,
    payload: PricingBatchDecisionBody,
    request: Request,
    actor_id: str = Depends(require_pricing_unlock),
) -> dict[str, Any]:
    try:
        return get_pricing_admin_service().batch_set_model_decision(
            draft_key,
            include_in_publish=payload.include_in_publish,
            provider_ids=payload.provider_ids,
            evidence_levels=payload.evidence_levels,
            model_keys=payload.model_keys,
            reason=payload.reason,
            actor_id=actor_id,
            ip_address=request.client.host if request.client else None,
        )
    except ValueError as exc:
        status_code = 409 if "stale" in str(exc) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@admin_router.post("/pricing/official-candidates/refresh")
def refresh_pricing_candidates(
    _actor_id: str = Depends(require_pricing_unlock),
) -> dict[str, Any]:
    return refresh_official_candidates(
        OfficialPriceRegistry.load_bundled(),
        get_pricing_admin_service().repository,
    )


@admin_router.post("/pricing/collection-jobs", status_code=202)
def start_pricing_collection(request: Request) -> dict[str, Any]:
    return get_pricing_collection_runtime().enqueue(_authenticated_owner(request))


@admin_router.get("/pricing/collection-jobs")
def list_pricing_collection_jobs() -> list[dict[str, Any]]:
    return get_pricing_collection_runtime().list()


@admin_router.get("/pricing/collection-jobs/{job_id}")
def get_pricing_collection_job(job_id: str) -> dict[str, Any]:
    job = get_pricing_collection_runtime().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Pricing collection job not found")
    return job


@admin_router.get("/pricing/model-mappings")
def list_pricing_model_mappings() -> list[dict[str, Any]]:
    return get_pricing_admin_service().repository.list_model_mappings()


@admin_router.put("/pricing/model-mappings/{provider_id}/{model_key}")
def save_pricing_model_mapping(
    provider_id: str,
    model_key: str,
    payload: PricingModelMappingBody,
    request: Request,
    actor_id: str = Depends(require_pricing_unlock),
) -> dict[str, Any]:
    try:
        return get_pricing_admin_service().save_model_mapping(
            provider_id,
            model_key,
            payload.official_provider_id,
            payload.official_model_id,
            payload.expected_revision,
            actor_id,
            request.client.host if request.client else None,
        )
    except PricingRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@admin_router.post("/pricing/imports/preview")
async def preview_pricing_import(
    request: Request,
    filename: str = Query(min_length=1, max_length=255),
) -> dict[str, Any]:
    return get_pricing_excel_service().preview_import(
        await request.body(),
        filename,
        _authenticated_owner(request),
    )


@admin_router.post("/pricing/imports/{import_id}/confirm")
def confirm_pricing_import(
    import_id: str,
    request: Request,
    actor_id: str = Depends(require_pricing_unlock),
) -> dict[str, Any]:
    try:
        return get_pricing_excel_service().confirm_import(
            import_id,
            actor_id,
            request.client.host if request.client else None,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Import not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@admin_router.post("/pricing/policies")
def save_pricing_policy(
    payload: PricingPolicyBody,
    request: Request,
    actor_id: str = Depends(require_pricing_unlock),
) -> dict[str, Any]:
    try:
        return get_pricing_admin_service().save_policy(
            payload.scope_type,
            payload.scope_key,
            payload.multiplier_decimal,
            payload.settings,
            actor_id,
            payload.expected_revision,
            request.client.host if request.client else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PricingRevisionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail="Pricing policy was updated; reload and retry",
        ) from exc


@admin_router.post("/pricing/initialize/preview")
def preview_initial_pricing(
    actor_id: str = Depends(require_pricing_unlock),
) -> dict[str, Any]:
    return get_pricing_admin_service().preview_initial_catalog(actor_id)


@admin_router.post("/pricing/previews/{catalog_id}/publish")
def publish_pricing_preview(
    catalog_id: str,
    request: Request,
    actor_id: str = Depends(require_pricing_unlock),
) -> dict[str, Any]:
    try:
        return get_pricing_admin_service().publish_preview(
            catalog_id,
            actor_id,
            request.client.host if request.client else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@admin_router.post("/pricing/catalogs/{catalog_id}/rollback")
def rollback_pricing_catalog(
    catalog_id: str,
    request: Request,
    actor_id: str = Depends(require_pricing_unlock),
) -> dict[str, Any]:
    try:
        return get_pricing_admin_service().rollback(
            catalog_id,
            actor_id,
            request.client.host if request.client else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
    return _ledger_page(
        repository,
        str(wallet["id"]),
        limit,
        cursor,
        include_internal=True,
    )


@admin_router.get("/usage-orders")
def list_admin_usage_orders(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=2048),
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    model: str | None = Query(default=None, min_length=1, max_length=255),
    provider: str | None = Query(default=None, min_length=1, max_length=255),
    publication_id: str | None = Query(default=None, min_length=1, max_length=255),
    app_id: str | None = Query(default=None, min_length=1, max_length=255),
    api_key_id: str | None = Query(default=None, min_length=1, max_length=255),
    owner_user_id: str | None = Query(default=None, min_length=1, max_length=255),
    status: str | None = Query(default=None, min_length=1, max_length=64),
    source: str | None = Query(default=None, min_length=1, max_length=64),
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
            source=source,
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
    publication_id: str | None = Query(default=None, min_length=1, max_length=255),
    app_id: str | None = Query(default=None, min_length=1, max_length=255),
    api_key_id: str | None = Query(default=None, min_length=1, max_length=255),
    owner_user_id: str | None = Query(default=None, min_length=1, max_length=255),
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


@admin_router.post("/reconciliation/{reconciliation_id}/resolve")
def resolve_admin_reconciliation(
    reconciliation_id: str,
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
            reconciliation_id,
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


@admin_router.get("/reconciliation-audits")
def list_admin_reconciliation_audits(
    actor_id: str | None = Query(default=None, min_length=1, max_length=255),
    reconciliation_id: str | None = Query(default=None, min_length=1, max_length=255),
    order_id: str | None = Query(default=None, min_length=1, max_length=255),
    outcome: str | None = Query(default=None, min_length=1, max_length=64),
    idempotency_key: str | None = Query(default=None, min_length=1, max_length=255),
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=2048),
) -> dict[str, Any]:
    try:
        return get_billing_reporting_service().list_reconciliation_audits(
            actor_id=actor_id,
            reconciliation_id=reconciliation_id,
            order_id=order_id,
            outcome=outcome,
            idempotency_key=idempotency_key,
            started_at=started_at,
            ended_at=ended_at,
            limit=limit,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@admin_router.get("/reconciliation-audits/{audit_id}")
def get_admin_reconciliation_audit(audit_id: str) -> dict[str, Any]:
    result = get_billing_reporting_service().get_reconciliation_audit(
        audit_id,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Audit not found")
    return result


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


@user_router.get("/top-up/config")
def get_top_up_config() -> dict[str, Any]:
    qr_url = os.environ.get("DCLAW_TOP_UP_QR_URL", "").strip()
    enabled = qr_url.startswith("https://")
    return {
        "enabled": enabled,
        "qr_url": qr_url if enabled else None,
        "instructions": os.environ.get(
            "DCLAW_TOP_UP_INSTRUCTIONS",
            "",
        ).strip(),
    }


@user_router.get("/top-up/products")
def list_top_up_products() -> dict[str, Any]:
    rows = get_top_up_service().top_up_repository.list_products(
        active_only=True,
    )
    return {"items": [_top_up_product(row) for row in rows]}


@user_router.get("/top-up/claims")
def list_user_top_up_claims(request: Request) -> dict[str, Any]:
    owner_id = _authenticated_owner(request)
    rows = get_top_up_service().top_up_repository.list_claims(
        owner_id=owner_id,
    )
    return {"items": [_top_up_claim(row) for row in rows]}


@user_router.post("/top-up/claims")
def submit_top_up_claim(
    payload: TopUpClaimBody,
    request: Request,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
    ),
) -> dict[str, Any]:
    try:
        row = get_top_up_service().submit_claim(
            _authenticated_owner(request),
            SubmitClaimCommand(
                product_id=payload.product_id,
                payment_channel=payload.payment_channel,
                payer_reference=payload.payer_reference,
                customer_note=payload.customer_note,
                idempotency_key=idempotency_key,
            ),
        )
        return _top_up_claim(row)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Product not found",
        ) from exc
    except (TopUpIdempotencyConflict, TopUpConflictError) as exc:
        raise HTTPException(
            status_code=409,
            detail="Idempotency conflict",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@admin_router.get("/top-up/claims")
def list_admin_top_up_claims(
    status: Literal["pending", "approved", "rejected"] | None = None,
) -> dict[str, Any]:
    rows = get_top_up_service().top_up_repository.list_claims(status=status)
    return {"items": [_top_up_claim(row, admin=True) for row in rows]}


@admin_router.get("/top-up/products")
def list_admin_top_up_products() -> dict[str, Any]:
    rows = get_top_up_service().top_up_repository.list_products()
    return {"items": [_top_up_product(row) for row in rows]}


@admin_router.post("/top-up/products")
def create_admin_top_up_product(
    payload: TopUpProductBody,
    request: Request,
) -> dict[str, Any]:
    values = payload.model_dump() | {
        "created_by": _authenticated_owner(request),
    }
    row = get_top_up_service().top_up_repository.create_product(values)
    return _top_up_product(row)


@admin_router.put("/top-up/products/{public_id}")
def replace_admin_top_up_product(
    public_id: str,
    payload: TopUpProductBody,
    request: Request,
) -> dict[str, Any]:
    values = payload.model_dump() | {
        "created_by": _authenticated_owner(request),
    }
    try:
        row = get_top_up_service().top_up_repository.replace_product(
            public_id,
            values,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Product not found",
        ) from exc
    return _top_up_product(row)


def _review_top_up_claim(
    *,
    public_id: str,
    payload: TopUpReviewBody,
    request: Request,
    idempotency_key: str,
    approve: bool,
) -> dict[str, Any]:
    service = get_top_up_service()
    command = ReviewCommand(
        idempotency_key=idempotency_key,
        reason=payload.reason,
    )
    try:
        if approve:
            row = service.approve_claim(
                public_id,
                _authenticated_owner(request),
                command,
            )
        else:
            row = service.reject_claim(
                public_id,
                _authenticated_owner(request),
                command,
            )
        return _top_up_claim(row, admin=True)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Claim not found") from exc
    except (TopUpConflictError, TopUpIdempotencyConflict) as exc:
        raise HTTPException(status_code=409, detail="Claim conflict") from exc


@admin_router.post("/top-up/claims/{public_id}/approve")
def approve_top_up_claim(
    public_id: str,
    payload: TopUpReviewBody,
    request: Request,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
    ),
) -> dict[str, Any]:
    return _review_top_up_claim(
        public_id=public_id,
        payload=payload,
        request=request,
        idempotency_key=idempotency_key,
        approve=True,
    )


@admin_router.post("/top-up/claims/{public_id}/reject")
def reject_top_up_claim(
    public_id: str,
    payload: TopUpReviewBody,
    request: Request,
    idempotency_key: str = Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
    ),
) -> dict[str, Any]:
    return _review_top_up_claim(
        public_id=public_id,
        payload=payload,
        request=request,
        idempotency_key=idempotency_key,
        approve=False,
    )


__all__ = ["admin_router", "user_router"]
