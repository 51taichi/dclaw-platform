"""Scheduled trusted-cost checks and bounded automatic margin protection."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol


class PricingSourceAdapter(Protocol):
    def fetch(self) -> Sequence[Any]: ...


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


class PricingSyncService:
    def __init__(
        self,
        sources: Sequence[PricingSource],
        *,
        protection_publisher: Callable[[ProtectionResult], None] | None = None,
        maximum_auto_raise: Decimal = Decimal("0.20"),
        protection_interval: timedelta = timedelta(hours=24),
    ) -> None:
        self.sources = tuple(sources)
        self.protection_publisher = protection_publisher or (lambda _result: None)
        self.maximum_auto_raise = maximum_auto_raise
        self.protection_interval = protection_interval
        self._last_fetch: dict[str, datetime] = {}
        self._last_protection: dict[str, datetime] = {}

    def check_due_sources(self, now: datetime) -> tuple[str, ...]:
        fetched: list[str] = []
        for source in self.sources:
            interval = source.interval or DEFAULT_INTERVALS[source.source_type]
            last = self._last_fetch.get(source.source_id)
            if last is not None and now - last < interval:
                continue
            source.adapter.fetch()
            self._last_fetch[source.source_id] = now
            fetched.append(source.source_id)
        return tuple(fetched)

    def apply_protection(
        self, model_key: str, required_raise: Decimal, now: datetime,
    ) -> ProtectionResult:
        if required_raise <= 0:
            return ProtectionResult(
                model_key, required_raise, Decimal(0), Decimal(0),
                "review", True, now,
            )
        last = self._last_protection.get(model_key)
        if last is not None and now - last < self.protection_interval:
            raise ProtectionRateLimited(model_key)
        applied = min(required_raise, self.maximum_auto_raise)
        remaining = max(Decimal(0), required_raise - applied)
        result = ProtectionResult(
            model_key, required_raise, applied, remaining,
            "critical" if remaining else "warning", False, now,
        )
        self.protection_publisher(result)
        self._last_protection[model_key] = now
        return result
