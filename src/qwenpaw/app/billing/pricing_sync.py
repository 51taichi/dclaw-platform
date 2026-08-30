"""Scheduled trusted-cost checks and bounded automatic margin protection."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from .official_pricing import OfficialPriceRegistry


class PricingSourceAdapter(Protocol):
    def fetch(self) -> Sequence[Any]:
        ...  # noqa: E704


class PricingSyncStateStore(Protocol):
    def get_pricing_sync_time(  # noqa: E704
        self, state_key: str
    ) -> datetime | None:
        ...

    def set_pricing_sync_time(  # noqa: E704
        self, state_key: str, occurred_at: datetime
    ) -> None:
        ...


class ProtectionRateLimited(RuntimeError):
    """A model already received automatic protection in the last 24 hours."""


@dataclass(frozen=True)
class PricingSource:
    source_id: str
    source_type: str
    adapter: PricingSourceAdapter
    interval: timedelta | None = None


@dataclass(frozen=True)
class ProtectionResult:
    model_key: str
    required_raise: Decimal
    applied_raise: Decimal
    remaining_risk: Decimal
    alert_level: str
    requires_review: bool
    created_at: datetime


DEFAULT_INTERVALS = {
    "official_api": timedelta(days=1),
    "aggregator": timedelta(days=7),
    "price_page": timedelta(days=7),
    "manual": timedelta(days=30),
}


def refresh_official_candidates(
    registry: OfficialPriceRegistry,
    repository: Any,
) -> dict[str, Any]:
    candidate_ids: list[str] = []
    for record in registry.records:
        conditions_json = json.dumps(
            record.conditions,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        conditions_digest = hashlib.sha256(
            conditions_json.encode()
        ).hexdigest()
        identity = {
            "provider_id": record.provider_id,
            "official_model_id": record.official_model_id,
            "capability": record.capability,
            "unit_key": record.unit_key,
            "unit_size": record.unit_size,
            "conditions": record.conditions,
            "source_url": record.source_url,
            "original_currency": record.original_currency,
            "original_price_decimal": str(record.original_price),
            "fx_rate_decimal": str(record.fx_rate),
            "registry_version": record.registry_version,
        }
        content_sha256 = hashlib.sha256(
            json.dumps(
                identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        candidate_ids.append(
            repository.append_official_candidate(
                {
                    "content_sha256": content_sha256,
                    "provider_id": record.provider_id,
                    "official_model_id": record.official_model_id,
                    "capability": record.capability,
                    "unit_key": record.unit_key,
                    "conditions_digest": conditions_digest,
                    "conditions": dict(record.conditions)
                    | {"unit_size": record.unit_size},
                    "source_url": record.source_url,
                    "source_published_at": record.source_published_at,
                    "original_currency": record.original_currency,
                    "original_price_decimal": str(record.original_price),
                    "fx_rate_decimal": str(record.fx_rate),
                    "rmb_cost_decimal": str(record.rmb_cost),
                    "verification_status": record.verification_status,
                    "registry_version": record.registry_version,
                }
            )
        )
    return {
        "candidate_count": len(set(candidate_ids)),
        "registry_versions": sorted(
            {record.registry_version for record in registry.records}
        ),
    }


def _comparable(
    value: datetime | None, reference: datetime
) -> datetime | None:
    if (
        value is not None
        and value.tzinfo is None
        and reference.tzinfo is not None
    ):
        return value.replace(tzinfo=reference.tzinfo)
    return value


class PricingSyncService:
    def __init__(
        self,
        sources: Sequence[PricingSource],
        *,
        protection_publisher: Callable[[ProtectionResult], None] | None = None,
        maximum_auto_raise: Decimal = Decimal("0.20"),
        protection_interval: timedelta = timedelta(hours=24),
        state_store: PricingSyncStateStore | None = None,
    ) -> None:
        self.sources = tuple(sources)
        self.protection_publisher = protection_publisher or (
            lambda _result: None
        )
        self.maximum_auto_raise = maximum_auto_raise
        self.protection_interval = protection_interval
        self.state_store = state_store
        self._last_fetch: dict[str, datetime] = {}
        self._last_protection: dict[str, datetime] = {}

    def check_due_sources(self, now: datetime) -> tuple[str, ...]:
        fetched: list[str] = []
        for source in self.sources:
            interval = source.interval or DEFAULT_INTERVALS[source.source_type]
            state_key = f"fetch:{source.source_id}"
            last = (
                self.state_store.get_pricing_sync_time(state_key)
                if self.state_store
                else self._last_fetch.get(source.source_id)
            )
            last = _comparable(last, now)
            if last is not None and now - last < interval:
                continue
            source.adapter.fetch()
            self._last_fetch[source.source_id] = now
            if self.state_store:
                self.state_store.set_pricing_sync_time(state_key, now)
            fetched.append(source.source_id)
        return tuple(fetched)

    def apply_protection(
        self,
        model_key: str,
        required_raise: Decimal,
        now: datetime,
    ) -> ProtectionResult:
        if required_raise <= 0:
            return ProtectionResult(
                model_key,
                required_raise,
                Decimal(0),
                Decimal(0),
                "review",
                True,
                now,
            )
        state_key = f"protection:{model_key}"
        last = (
            self.state_store.get_pricing_sync_time(state_key)
            if self.state_store
            else self._last_protection.get(model_key)
        )
        last = _comparable(last, now)
        if last is not None and now - last < self.protection_interval:
            raise ProtectionRateLimited(model_key)
        applied = min(required_raise, self.maximum_auto_raise)
        remaining = max(Decimal(0), required_raise - applied)
        result = ProtectionResult(
            model_key,
            required_raise,
            applied,
            remaining,
            "critical" if remaining else "warning",
            False,
            now,
        )
        self.protection_publisher(result)
        self._last_protection[model_key] = now
        if self.state_store:
            self.state_store.set_pricing_sync_time(state_key, now)
        return result
