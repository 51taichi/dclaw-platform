"""Validated, versioned official model-price reference data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping


class OfficialPriceRegistryError(ValueError):
    """Bundled official price evidence is invalid or ambiguous."""


@dataclass(frozen=True)
class OfficialPriceDimension:
    provider_id: str
    official_model_id: str
    capability: str
    unit_key: str
    unit_size: int
    conditions: Mapping[str, Any]
    original_currency: str
    original_price: Decimal
    fx_rate: Decimal
    source_url: str
    source_published_at: datetime | None
    collected_at: datetime
    verification_status: str
    registry_version: str

    @property
    def rmb_cost(self) -> Decimal:
        return self.original_price * self.fx_rate


def _decimal_string(record: Mapping[str, Any], key: str) -> Decimal:
    value = record.get(key)
    if not isinstance(value, str):
        raise OfficialPriceRegistryError(f"{key} must be a decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise OfficialPriceRegistryError(
            f"{key} must be a decimal string"
        ) from exc
    if not parsed.is_finite() or parsed < 0:
        raise OfficialPriceRegistryError(f"{key} must be nonnegative")
    return parsed


def _timestamp(value: Any, key: str, *, optional: bool = False):
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise OfficialPriceRegistryError(f"{key} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OfficialPriceRegistryError(
            f"{key} must be an ISO timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise OfficialPriceRegistryError(f"{key} must include timezone")
    return parsed


class OfficialPriceRegistry:
    def __init__(self, records: Iterable[OfficialPriceDimension]) -> None:
        self._records = tuple(records)
        grouped: dict[tuple[str, str], list[OfficialPriceDimension]] = {}
        for record in self._records:
            grouped.setdefault(
                (record.provider_id, record.official_model_id), []
            ).append(record)
        self._grouped = {
            key: tuple(
                sorted(
                    rows,
                    key=lambda row: (
                        row.unit_key,
                        json.dumps(row.conditions, sort_keys=True),
                    ),
                )
            )
            for key, rows in grouped.items()
        }

    @classmethod
    def from_records(
        cls, records: Iterable[Mapping[str, Any]]
    ) -> "OfficialPriceRegistry":
        parsed: list[OfficialPriceDimension] = []
        seen: set[tuple[str, str, str, str]] = set()
        for source in records:
            conditions = source.get("conditions", {})
            if not isinstance(conditions, dict):
                raise OfficialPriceRegistryError(
                    "conditions must be an object"
                )
            provider_id = str(source.get("provider_id", "")).strip()
            model_id = str(source.get("official_model_id", "")).strip()
            unit_key = str(source.get("unit_key", "")).strip()
            source_url = str(source.get("source_url", "")).strip()
            currency = str(source.get("original_currency", "")).upper()
            verification_status = str(
                source.get("verification_status", "")
            ).strip()
            registry_version = str(source.get("registry_version", "")).strip()
            if not provider_id or not model_id or not unit_key:
                raise OfficialPriceRegistryError("model identity is required")
            if not source_url.startswith("https://"):
                raise OfficialPriceRegistryError("source_url must use HTTPS")
            if currency not in {"CNY", "USD"}:
                raise OfficialPriceRegistryError("unsupported currency")
            if verification_status != "verified":
                raise OfficialPriceRegistryError(
                    "official prices must be verified"
                )
            if not registry_version:
                raise OfficialPriceRegistryError(
                    "registry_version is required"
                )
            unit_size = source.get("unit_size")
            if not isinstance(unit_size, int) or unit_size <= 0:
                raise OfficialPriceRegistryError("unit_size must be positive")
            identity = (
                provider_id,
                model_id,
                unit_key,
                json.dumps(conditions, sort_keys=True, separators=(",", ":")),
            )
            if identity in seen:
                raise OfficialPriceRegistryError("duplicate dimension")
            seen.add(identity)
            parsed.append(
                OfficialPriceDimension(
                    provider_id=provider_id,
                    official_model_id=model_id,
                    capability=str(source.get("capability", "")).strip(),
                    unit_key=unit_key,
                    unit_size=unit_size,
                    conditions=conditions,
                    original_currency=currency,
                    original_price=_decimal_string(
                        source, "original_price_decimal"
                    ),
                    fx_rate=_decimal_string(source, "fx_rate_decimal"),
                    source_url=source_url,
                    source_published_at=_timestamp(
                        source.get("source_published_at"),
                        "source_published_at",
                        optional=True,
                    ),
                    collected_at=_timestamp(
                        source.get("collected_at"), "collected_at"
                    ),
                    verification_status=verification_status,
                    registry_version=registry_version,
                )
            )
        return cls(parsed)

    @classmethod
    def load_bundled(cls) -> "OfficialPriceRegistry":
        directory = Path(__file__).with_name("default_prices")
        records: list[Mapping[str, Any]] = []
        for path in sorted(directory.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not isinstance(
                payload.get("records"), list
            ):
                raise OfficialPriceRegistryError(
                    f"invalid registry payload: {path.name}"
                )
            records.extend(payload["records"])
        return cls.from_records(records)

    def dimensions(
        self, provider_id: str, official_model_id: str
    ) -> tuple[OfficialPriceDimension, ...]:
        return self._grouped.get((provider_id, official_model_id), ())

    @property
    def records(self) -> tuple[OfficialPriceDimension, ...]:
        return self._records
