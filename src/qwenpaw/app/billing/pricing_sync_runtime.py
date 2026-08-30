"""Production scheduling and normalized HTTP adapters for price checks."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from urllib.request import Request, urlopen

from ..storage.engine import get_app_engine
from ..storage.repos.pricing_admin_repo import PricingAdminRepository
from .official_pricing import OfficialPriceRegistry
from .pricing_collectors import (
    CollectionStage,
    EVIDENCE_DEFAULTS,
    OfficialRegistryCollector,
    PricingCollectionPipeline,
)
from .pricing_inventory import PricingModelInventory
from .pricing_sync import (
    PricingSource,
    PricingSyncService,
    ProtectionResult,
)

logger = logging.getLogger(__name__)


class PricingCollectionRuntime:
    """Run durable price collection jobs independently of HTTP requests."""

    def __init__(
        self,
        repository: PricingAdminRepository,
        inventory: Any,
        pipeline: Any,
        *,
        clock: Any | None = None,
        lease_seconds: int = 60,
    ) -> None:
        self.repository = repository
        self.inventory = inventory
        self.pipeline = pipeline
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.lease_seconds = lease_seconds

    def enqueue(self, actor_id: str) -> dict[str, Any]:
        models = tuple(self.inventory.list_enabled())
        inventory_digest = hashlib.sha256(
            json.dumps(
                [asdict(model) for model in models],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return self.repository.create_collection_job(
            inventory_digest,
            actor_id,
            self.clock(),
        )

    def get(self, job_id: str) -> dict[str, Any] | None:
        return self.repository.get_collection_job(job_id)

    def list(self) -> list[dict[str, Any]]:
        return self.repository.list_collection_jobs()

    async def run_pending_once(self, worker_id: str) -> str | None:
        now = self.clock()
        job = self.repository.claim_collection_job(
            worker_id,
            now,
            self.lease_seconds,
        )
        if job is None:
            return None
        for model in tuple(self.inventory.list_enabled()):
            try:
                result = await asyncio.to_thread(self.pipeline.collect, model)
            except Exception as exc:
                logger.exception(
                    "Pricing collection failed for %s/%s",
                    model.provider_id,
                    model.model_key,
                )
                self.repository.update_collection_item(
                    str(job["id"]),
                    model.provider_id,
                    model.model_key,
                    model.pricing_region,
                    status="failed",
                    result={"evidence_level": "failed"},
                    candidate_id=None,
                    error_summary=str(exc),
                    now=self.clock(),
                )
                if not self.repository.renew_collection_job(
                    str(job["id"]),
                    worker_id,
                    self.clock(),
                    self.lease_seconds,
                ):
                    raise RuntimeError(
                        "pricing collection job ownership lost"
                    ) from exc
                continue
            candidate_ids = [
                self._persist_candidate(candidate)
                for candidate in result.candidates
            ]
            status = (
                "official_succeeded"
                if result.evidence_level == "official_verified"
                else result.evidence_level
                if result.evidence_level.startswith("ai_")
                else "failed"
            )
            self.repository.update_collection_item(
                str(job["id"]),
                model.provider_id,
                model.model_key,
                model.pricing_region,
                status=status,
                result={
                    "evidence_level": result.evidence_level,
                    "default_multiplier": (
                        str(result.default_multiplier)
                        if result.default_multiplier is not None
                        else None
                    ),
                    "default_include_in_publish": (
                        result.default_include_in_publish
                    ),
                    "attempt_errors": list(result.attempt_errors),
                },
                candidate_id=candidate_ids[0] if candidate_ids else None,
                error_summary=(
                    "; ".join(result.attempt_errors) or None
                ),
                now=self.clock(),
            )
            if not self.repository.renew_collection_job(
                str(job["id"]),
                worker_id,
                self.clock(),
                self.lease_seconds,
            ):
                raise RuntimeError("pricing collection job ownership lost")
        return self.repository.finish_collection_job(
            str(job["id"]), worker_id, self.clock()
        )

    def _persist_candidate(self, candidate: Any) -> str:
        conditions = dict(candidate.conditions) | {
            "unit_size": candidate.unit_size
        }
        conditions_json = json.dumps(
            conditions,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        identity = {
            "provider_id": candidate.provider_id,
            "official_model_id": candidate.official_model_id,
            "pricing_region": candidate.pricing_region,
            "capability": candidate.capability,
            "unit_key": candidate.unit_key,
            "conditions": conditions,
            "original_currency": candidate.original_currency,
            "original_price_decimal": str(candidate.original_price),
            "rmb_cost_decimal": str(candidate.rmb_cost),
            "source_url": candidate.source_url,
            "evidence_level": candidate.evidence_level,
            "collector_version": candidate.collector_version,
        }
        multiplier = EVIDENCE_DEFAULTS[candidate.evidence_level][0]
        fx_rate = (
            candidate.rmb_cost / candidate.original_price
            if candidate.original_price
            else Decimal(1)
        )
        return self.repository.append_official_candidate(
            {
                "content_sha256": hashlib.sha256(
                    json.dumps(
                        identity,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
                "provider_id": candidate.provider_id,
                "official_model_id": candidate.official_model_id,
                "capability": candidate.capability,
                "unit_key": candidate.unit_key,
                "conditions_digest": hashlib.sha256(
                    conditions_json.encode()
                ).hexdigest(),
                "conditions": conditions,
                "source_url": candidate.source_url or "",
                "source_published_at": None,
                "original_currency": candidate.original_currency,
                "original_price_decimal": str(candidate.original_price),
                "fx_rate_decimal": str(fx_rate),
                "rmb_cost_decimal": str(candidate.rmb_cost),
                "verification_status": (
                    "verified"
                    if candidate.evidence_level == "official_verified"
                    else "candidate"
                ),
                "registry_version": candidate.collector_version,
                "evidence_level": candidate.evidence_level,
                "evidence_excerpt": candidate.evidence_excerpt,
                "collector_version": candidate.collector_version,
                "ai_model": candidate.ai_model,
                "prompt_version": candidate.prompt_version,
                "confidence_decimal": (
                    str(candidate.confidence)
                    if candidate.confidence is not None
                    else None
                ),
                "default_multiplier_decimal": (
                    str(multiplier) if multiplier is not None else None
                ),
            }
        )


async def pricing_collection_loop(
    runtime: PricingCollectionRuntime,
    worker_id: str,
    *,
    poll_seconds: float = 5,
) -> None:
    """Continuously drain durable pricing jobs; cancellation is cooperative."""
    while True:
        try:
            await runtime.run_pending_once(worker_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Pricing collection job failed; published catalog retained"
            )
        await asyncio.sleep(poll_seconds)


def build_pricing_collection_runtime(
    provider_manager: Any,
) -> PricingCollectionRuntime:
    official_hosts = {
        "dashscope": frozenset(
            {"help.aliyun.com", "dashscope.aliyun.com"}
        ),
        "volcengine": frozenset(
            {"www.volcengine.com", "ark.cn-beijing.volces.com"}
        ),
    }
    pipeline = PricingCollectionPipeline(
        (
            CollectionStage(
                "bundled-official",
                OfficialRegistryCollector(
                    OfficialPriceRegistry.load_bundled(), official_hosts
                ),
            ),
        )
    )
    return PricingCollectionRuntime(
        PricingAdminRepository(get_app_engine()),
        PricingModelInventory(provider_manager),
        pipeline,
    )


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
    """Record a protection candidate without changing the formal catalog."""

    def __init__(self, repository: PricingAdminRepository) -> None:
        self.admin = repository

    def __call__(self, result: ProtectionResult) -> None:
        self.admin.append_audit(
            "pricing.protection_candidate",
            "system:pricing-protection",
            {},
            {
                "model_key": result.model_key,
                "required_raise": str(result.required_raise),
                "suggested_raise": str(result.applied_raise),
            },
            {
                "remaining_risk": str(result.remaining_risk),
                "alert_level": result.alert_level,
                "created_at": result.created_at.isoformat(),
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
