"""Production scheduling and normalized HTTP adapters for price checks."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal
from typing import Any
from urllib.request import Request, urlopen

from ..storage.engine import get_app_engine
from ..storage.repos.price_catalog_repo import PriceCatalogRepository
from ..storage.repos.pricing_admin_repo import PricingAdminRepository
from .pricing import PriceCatalogDraft, PriceCatalogService, PriceRule
from .pricing_sync import (
    PricingSource,
    PricingSyncService,
    ProtectionResult,
)

logger = logging.getLogger(__name__)


class NormalizedHttpPricingAdapter:
    """Read already-normalized supplier prices from a controlled JSON feed."""

    def __init__(
        self,
        config: dict[str, Any],
        repository: PricingAdminRepository,
        protection: PricingSyncService,
    ) -> None:
        self.config = config
        self.repository = repository
        self.protection = protection

    def fetch(self) -> tuple[dict[str, Any], ...]:
        headers = {"Accept": "application/json"}
        token_env = self.config.get("token_env")
        if token_env and os.environ.get(str(token_env)):
            headers["Authorization"] = f"Bearer {os.environ[str(token_env)]}"
        request = Request(str(self.config["url"]), headers=headers)
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        rows = payload.get("prices") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise TypeError(
                "normalized pricing feed must contain a prices list"
            )

        trusted = bool(self.config.get("trusted", False))
        previous = {
            (row["provider_id"], row["model_key"], row["unit_key"]): Decimal(
                row["rmb_cost_decimal"]
            )
            for row in self.repository.latest_trusted_costs()
        }
        maximum_raise: dict[str, Decimal] = {}
        accepted: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        for source in rows:
            row = self._normalize(source, now, trusted)
            self.repository.append_cost_snapshot(row)
            accepted.append(row)
            key = (row["provider_id"], row["model_key"], row["unit_key"])
            old = previous.get(key)
            if trusted and old and old > 0:
                increase = Decimal(row["rmb_cost_decimal"]) / old - Decimal(1)
                model = f"{row['provider_id']}/{row['model_key']}"
                maximum_raise[model] = max(
                    maximum_raise.get(model, Decimal(0)), increase
                )
        for model, required_raise in maximum_raise.items():
            if required_raise > 0:
                self.protection.apply_protection(model, required_raise, now)
        return tuple(accepted)

    def _normalize(
        self,
        source: Any,
        now: datetime,
        trusted: bool,
    ) -> dict[str, Any]:
        if not isinstance(source, dict):
            raise TypeError("pricing feed rows must be objects")
        required = (
            "provider_id",
            "model_key",
            "capability",
            "unit_key",
            "rmb_cost_decimal",
        )
        if any(not source.get(name) for name in required):
            raise ValueError("pricing feed row is missing a required field")
        cost = Decimal(str(source["rmb_cost_decimal"]))
        if cost < 0:
            raise ValueError("pricing feed cost must be non-negative")
        return {
            "provider_id": str(source["provider_id"]),
            "model_key": str(source["model_key"]),
            "capability": str(source["capability"]),
            "unit_key": str(source["unit_key"]),
            "source_type": str(self.config.get("source_type", "official_api")),
            "source_reference": str(self.config["url"]),
            "original_currency": "CNY",
            "original_price_decimal": str(cost),
            "fx_rate_decimal": "1",
            "rmb_cost_decimal": str(cost),
            "conditions": source.get("conditions", {}),
            "verification_status": "verified" if trusted else "candidate",
            "verified_at": now,
        }


class AutoProtectionPublisher:
    """Clone the active catalog and raise one model by a bounded percentage."""

    def __init__(self, repository: PricingAdminRepository) -> None:
        self.admin = repository
        self.catalogs = PriceCatalogRepository(repository.engine)

    def __call__(self, result: ProtectionResult) -> None:
        now = result.created_at
        current = self.catalogs.effective_catalog(now)
        provider_id, model_key = result.model_key.split("/", 1)
        factor = Decimal(1) + result.applied_raise

        def raised(value: int) -> int:
            return (
                int(
                    (Decimal(value) * factor).to_integral_value(
                        rounding=ROUND_CEILING
                    )
                )
                if value
                else 0
            )

        def metadata_for(rule: dict[str, Any]) -> dict[str, Any]:
            metadata = dict(rule["metadata"])
            if (rule["provider_id"], rule["model_key"]) != (
                provider_id,
                model_key,
            ):
                return metadata
            for key in (
                "rmb_sale_price",
                "input_rmb_sale_price",
                "output_rmb_sale_price",
            ):
                if metadata.get(key) is not None:
                    metadata[key] = str(Decimal(str(metadata[key])) * factor)
            metadata["auto_protection_raise"] = str(result.applied_raise)
            return metadata

        rules = tuple(
            PriceRule(
                id=rule["id"],
                provider_id=rule["provider_id"],
                model_key=rule["model_key"],
                capability=rule["capability"],
                unit_type=rule["unit_type"],
                priority=rule["priority"],
                unit_size=rule["unit_size"],
                credits_per_unit=(
                    raised(rule["credits_per_unit"])
                    if (rule["provider_id"], rule["model_key"])
                    == (provider_id, model_key)
                    else rule["credits_per_unit"]
                ),
                input_credits_per_1k=(
                    raised(rule["input_credits_per_1k"])
                    if (rule["provider_id"], rule["model_key"])
                    == (provider_id, model_key)
                    else rule["input_credits_per_1k"]
                ),
                output_credits_per_1k=(
                    raised(rule["output_credits_per_1k"])
                    if (rule["provider_id"], rule["model_key"])
                    == (provider_id, model_key)
                    else rule["output_credits_per_1k"]
                ),
                parameter_match=rule["parameter_match"],
                metadata=metadata_for(rule),
            )
            for rule in current["rules"]
        )
        catalog_id = PriceCatalogService(
            self.catalogs,
            clock=lambda: now,
        ).publish(
            PriceCatalogDraft(
                version=f"protect-{now.strftime('%Y%m%d%H%M%S')}",
                effective_at=now,
                rules=rules,
                created_by="system:pricing-protection",
                metadata={
                    "protected_model": result.model_key,
                    "previous_catalog_id": current["id"],
                    "applied_raise": str(result.applied_raise),
                },
            )
        )
        self.admin.append_audit(
            "catalog.auto_protected",
            "system:pricing-protection",
            {"catalog_id": current["id"]},
            {"catalog_id": catalog_id},
            {
                "model_key": result.model_key,
                "remaining_risk": str(result.remaining_risk),
            },
        )


def build_pricing_sync_from_env() -> PricingSyncService | None:
    raw = os.environ.get("DCLAW_PRICING_SYNC_SOURCES_JSON", "").strip()
    if not raw:
        return None
    configs = json.loads(raw)
    if not isinstance(configs, list):
        raise TypeError("DCLAW_PRICING_SYNC_SOURCES_JSON must be a JSON list")
    repository = PricingAdminRepository(get_app_engine())
    service = PricingSyncService(
        (),
        state_store=repository,
        protection_publisher=AutoProtectionPublisher(repository),
    )
    sources = []
    for config in configs:
        interval = config.get("interval_hours")
        sources.append(
            PricingSource(
                str(config["id"]),
                str(config.get("source_type", "official_api")),
                NormalizedHttpPricingAdapter(config, repository, service),
                (
                    timedelta(hours=float(interval))
                    if interval is not None
                    else None
                ),
            )
        )
    service.sources = tuple(sources)
    return service


async def pricing_sync_loop(service: PricingSyncService) -> None:
    while True:
        try:
            await asyncio.to_thread(
                service.check_due_sources,
                datetime.now(timezone.utc),
            )
        except Exception:
            logger.exception(
                "Pricing source check failed; published catalog retained"
            )
        await asyncio.sleep(3600)
