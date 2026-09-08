"""Durable per-job billing for authenticated AIGC media generation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine

from ..billing.pricing import (
    PriceCatalogService,
    PriceRuleNotFoundError,
    QuoteRequest,
)
from ..billing.usage import ReserveModelCall, SettleModelCall, UsageService
from ..storage.engine import get_app_engine
from ..storage.repos.billing_repo import BillingRepository
from ..storage.repos.price_catalog_repo import PriceCatalogRepository
from ..storage.schema import (
    billing_usage_items,
    billing_usage_orders,
    billing_wallets,
)
from .models import AigcJob

_IMAGE_CAPABILITIES = frozenset(
    {"text_to_image", "image_to_image", "image_edit"},
)
_VIDEO_CAPABILITIES = frozenset(
    {"text_to_video", "image_to_video", "reference_video"},
)
_PRICING_ALIASES = {
    "image_to_image": "text_to_image",
    "image_edit": "text_to_image",
    "image_to_video": "text_to_video",
    "reference_video": "text_to_video",
}


@dataclass(frozen=True)
class AigcBillingReservation:
    """A price-locked hold associated one-to-one with an AIGC job."""

    service: UsageService
    usage_order_id: str
    item_key: str
    job_id: str
    provider_id: str
    model_key: str
    pricing_capability: str
    requested_capability: str
    quoted_credits: int
    item_status: str

    def settle_success(
        self,
        *,
        outputs: Sequence[Any],
        supplier_reference: str | None = None,
    ) -> None:
        self.service.settle_model_call(
            SettleModelCall(
                usage_order_id=self.usage_order_id,
                item_key=self.item_key,
                supplier_reference=(supplier_reference or self.job_id).strip(),
                billability="billable",
                execution_outcome="succeeded",
                evidence={
                    "adapter_version": "aigc-job-v1",
                    "response_class": "success",
                    "job_id": self.job_id,
                    "requested_capability": self.requested_capability,
                    "output_count": len(outputs),
                },
            ),
        )

    def settle_failure(
        self,
        *,
        error: BaseException | str,
        supplier_reference: str | None = None,
        uncertain: bool = False,
    ) -> None:
        error_name = (
            type(error).__name__
            if isinstance(error, BaseException)
            else str(error).strip() or "AigcGenerationError"
        )
        self.service.settle_model_call(
            SettleModelCall(
                usage_order_id=self.usage_order_id,
                item_key=self.item_key,
                supplier_reference=(supplier_reference or self.job_id).strip(),
                billability="unknown" if uncertain else "not_billable",
                execution_outcome="failed",
                evidence={
                    "adapter_version": "aigc-job-v1",
                    "response_class": (
                        "provider_outcome_unknown" if uncertain else "generation_failed"
                    ),
                    "job_id": self.job_id,
                    "requested_capability": self.requested_capability,
                    "error_class": error_name,
                },
            ),
        )


def reserve_aigc_job(
    job: AigcJob,
    owner_user_id: str,
    *,
    engine: Engine | None = None,
) -> AigcBillingReservation | None:
    """Reserve the published retail price before a media provider is called.

    AIGC job-attempt fencing is authoritative for concurrency.  The stable
    job id and item key make quote creation and reservation replay-safe after
    process restarts or async provider polling.
    """
    if job.capability not in _IMAGE_CAPABILITIES | _VIDEO_CAPABILITIES:
        return None
    if not str(owner_user_id).strip() or str(owner_user_id) == "0":
        return None

    active_engine = engine or get_app_engine()
    repository = BillingRepository(active_engine)
    pricing = PriceCatalogService(PriceCatalogRepository(active_engine))
    service = UsageService(repository, pricing, mode="enforced")
    parameters = _pricing_parameters(job)
    pricing_capability = _priced_capability(
        pricing,
        provider_id=job.provider_id,
        model_key=job.model_id,
        requested_capability=job.capability,
        parameters=parameters,
    )
    request = QuoteRequest(
        provider_id=job.provider_id,
        model_key=job.model_id,
        capability=pricing_capability,
        parameters=parameters,
    )
    order = service.create_quote(
        owner_user_id,
        request,
        business_key=f"aigc-job:{job.id}",
        source_type="aigc",
        source_id=job.id,
    )
    item_key = "aigc-generation"
    reserved = service.reserve_model_call(
        ReserveModelCall(
            usage_order_id=str(order["id"]),
            item_key=item_key,
            provider_id=job.provider_id,
            model_key=job.model_id,
            capability=pricing_capability,
            parameters=parameters,
        ),
    )
    return AigcBillingReservation(
        service=service,
        usage_order_id=str(order["id"]),
        item_key=item_key,
        job_id=job.id,
        provider_id=job.provider_id,
        model_key=job.model_id,
        pricing_capability=pricing_capability,
        requested_capability=job.capability,
        quoted_credits=reserved.quoted_credits,
        item_status=reserved.status,
    )


def find_aigc_job_reservation(
    job: AigcJob,
    owner_user_id: str,
    *,
    engine: Engine | None = None,
) -> AigcBillingReservation | None:
    """Load an existing per-job hold without creating a new billing order.

    Cancellation and restart recovery use this path so a cancelled job cannot
    leave credits held merely because the worker that created the reservation
    is no longer in memory.
    """
    owner = str(owner_user_id).strip()
    if not owner or owner == "0":
        return None
    active_engine = engine or get_app_engine()
    statement = (
        select(
            billing_usage_orders.c.id.label("usage_order_id"),
            billing_usage_orders.c.provider_id,
            billing_usage_orders.c.model_key,
            billing_usage_orders.c.capability,
            billing_usage_items.c.item_key,
            billing_usage_items.c.status.label("item_status"),
            billing_usage_items.c.quoted_credits,
        )
        .select_from(
            billing_usage_orders.join(
                billing_wallets,
                billing_wallets.c.id == billing_usage_orders.c.wallet_id,
            ).join(
                billing_usage_items,
                billing_usage_items.c.usage_order_id == billing_usage_orders.c.id,
            ),
        )
        .where(
            billing_usage_orders.c.source_type == "aigc",
            billing_usage_orders.c.source_id == job.id,
            billing_wallets.c.owner_type == "user",
            billing_wallets.c.owner_id == owner,
            billing_usage_items.c.item_key == "aigc-generation",
        )
    )
    with active_engine.connect() as connection:
        rows = connection.execute(statement).mappings().all()
    if not rows:
        return None
    if len(rows) != 1:
        raise RuntimeError("AIGC_BILLING_RESERVATION_CONFLICT")
    row = rows[0]
    service = UsageService(
        BillingRepository(active_engine),
        PriceCatalogService(PriceCatalogRepository(active_engine)),
        mode="enforced",
    )
    return AigcBillingReservation(
        service=service,
        usage_order_id=str(row["usage_order_id"]),
        item_key=str(row["item_key"]),
        job_id=job.id,
        provider_id=str(row["provider_id"]),
        model_key=str(row["model_key"]),
        pricing_capability=str(row["capability"]),
        requested_capability=job.capability,
        quoted_credits=int(row["quoted_credits"]),
        item_status=str(row["item_status"]),
    )


def settle_cancelled_aigc_job(
    job: AigcJob,
    owner_user_id: str,
    *,
    supplier_references: Sequence[str] = (),
    engine: Engine | None = None,
) -> None:
    """Release an unsubmitted job or reconcile an accepted supplier task."""
    reservation = find_aigc_job_reservation(
        job,
        owner_user_id,
        engine=engine,
    )
    if reservation is None or reservation.item_status != "held":
        return
    references = [
        str(value).strip() for value in supplier_references if str(value).strip()
    ]
    reservation.settle_failure(
        error="CancelledError",
        supplier_reference=references[0] if references else job.id,
        uncertain=bool(references),
    )


def _priced_capability(
    pricing: PriceCatalogService,
    *,
    provider_id: str,
    model_key: str,
    requested_capability: str,
    parameters: Mapping[str, Any],
) -> str:
    request = QuoteRequest(
        provider_id=provider_id,
        model_key=model_key,
        capability=requested_capability,
        parameters=parameters,
    )
    try:
        pricing.quote(request)
        return requested_capability
    except PriceRuleNotFoundError:
        alias = _PRICING_ALIASES.get(requested_capability)
        if alias is None:
            raise
        pricing.quote(
            QuoteRequest(
                provider_id=provider_id,
                model_key=model_key,
                capability=alias,
                parameters=parameters,
            ),
        )
        return alias


def _pricing_parameters(job: AigcJob) -> dict[str, Any]:
    raw = job.parameters
    result: dict[str, Any] = {
        "generation_mode": job.capability,
    }
    aliases = {
        "resolution": ("resolution", "videoResolution", "imageResolution"),
        "quality": ("quality", "imageQuality"),
        "aspect_ratio": ("aspect_ratio", "aspectRatio", "ratio"),
        "audio": ("audio", "videoAudio", "generate_audio"),
        "size": ("size",),
        "tier": ("tier",),
    }
    for target, keys in aliases.items():
        value = next((raw.get(key) for key in keys if raw.get(key) is not None), None)
        if isinstance(value, (str, int, float, bool)):
            result[target] = value

    if job.capability in _IMAGE_CAPABILITIES:
        result["count"] = _positive_int(
            raw.get("imageCount", raw.get("n", raw.get("count", 1))),
            default=1,
        )
    if job.capability in _VIDEO_CAPABILITIES:
        result["duration_seconds"] = _positive_int(
            raw.get(
                "video_length",
                raw.get(
                    "videoDuration",
                    raw.get("duration_seconds", raw.get("duration", 5)),
                ),
            ),
            default=5,
        )
        result["count"] = _positive_int(
            raw.get("videoCount", raw.get("count", 1)),
            default=1,
        )
    return result


def _positive_int(value: Any, *, default: int) -> int:
    try:
        normalized = int(float(str(value)))
    except (TypeError, ValueError):
        return default
    return normalized if normalized > 0 else default


__all__ = [
    "AigcBillingReservation",
    "find_aigc_job_reservation",
    "reserve_aigc_job",
    "settle_cancelled_aigc_job",
]
