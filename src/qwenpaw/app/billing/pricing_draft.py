"""Build safe multidimensional pricing drafts from enabled models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from typing import Any, Mapping, Sequence

from .official_pricing import OfficialPriceRegistry
from .pricing_inventory import PriceableModel


@dataclass(frozen=True)
class PricingDraftRow:
    provider_id: str
    provider_name: str
    model_key: str
    model_name: str
    official_provider_id: str | None
    official_model_id: str | None
    category: str
    capability: str
    unit_key: str
    unit_size: int
    conditions: Mapping[str, Any]
    rmb_cost: Decimal | None
    multiplier: Decimal
    rmb_sale_price: Decimal | None
    credits: int | None
    source_type: str
    source_url: str | None
    verification_status: str
    include_in_publish: bool
    exclusion_reason: str | None
    registry_version: str | None
    evidence_level: str = "official_verified"


@dataclass(frozen=True)
class PricingDraftRisk:
    code: str
    provider_id: str
    model_key: str
    unit_key: str | None = None


@dataclass(frozen=True)
class PricingCoverage:
    enabled_models: int
    matched_models: int
    missing_models: int
    excluded_models: int
    blocking_models: int


@dataclass(frozen=True)
class PricingDraftResult:
    rows: tuple[PricingDraftRow, ...]
    risks: tuple[PricingDraftRisk, ...]
    coverage: PricingCoverage


class PricingDraftBuilder:
    def __init__(
        self,
        registry: OfficialPriceRegistry,
        *,
        default_multiplier: Decimal = Decimal("1.5"),
        credits_per_yuan: int = 100,
    ) -> None:
        self.registry = registry
        self.default_multiplier = default_multiplier
        self.credits_per_yuan = credits_per_yuan

    def build(
        self,
        models: Sequence[PriceableModel],
        costs: Sequence[Mapping[str, Any]],
        mappings: Sequence[Mapping[str, Any]],
        exclusions: Sequence[Mapping[str, Any]],
        candidates: Sequence[Mapping[str, Any]] = (),
        decisions: Sequence[Mapping[str, Any]] = (),
    ) -> PricingDraftResult:
        mapping_index = {
            (str(row["provider_id"]), str(row["model_key"])): row
            for row in mappings
        }
        cost_index = {
            (
                str(row["provider_id"]),
                str(row["model_key"]),
                str(row.get("capability") or ""),
                str(row["unit_key"]),
                _conditions_key(row.get("conditions_json", "{}")),
            ): row
            for row in costs
            if row.get("verification_status") == "verified"
        }
        exclusion_index = {
            (str(row["provider_id"]), str(row["model_key"])): row
            for row in exclusions
            if row.get("excluded") is True
        }
        decision_index = {
            (str(row["provider_id"]), str(row["model_key"])): row
            for row in decisions
        }
        candidate_index: dict[
            tuple[str, str, str, str, str], Mapping[str, Any]
        ] = {}
        for row in candidates:
            key = (
                str(row["provider_id"]),
                str(row["official_model_id"]),
                str(row.get("capability") or ""),
                str(row["unit_key"]),
                _conditions_key(row.get("conditions_json", "{}")),
            )
            candidate_index.setdefault(key, row)
        rows: list[PricingDraftRow] = []
        risks: list[PricingDraftRisk] = []
        matched: set[tuple[str, str]] = set()
        missing: set[tuple[str, str]] = set()
        excluded: set[tuple[str, str]] = set()

        for model in models:
            model_key = (model.provider_id, model.model_key)
            mapping = mapping_index.get(model_key)
            official_provider_id = (
                str(mapping["official_provider_id"])
                if mapping and mapping.get("official_provider_id")
                else model.provider_id
                if model.official_model_id
                else None
            )
            official_model_id = (
                str(mapping["official_model_id"])
                if mapping
                else model.official_model_id
            )
            dimensions = (
                tuple(
                    dimension
                    for dimension in self.registry.dimensions(
                        official_provider_id, official_model_id
                    )
                    if _region_matches(
                        dimension.conditions, model.pricing_region
                    )
                )
                if official_provider_id and official_model_id
                else ()
            )
            exclusion = exclusion_index.get(model_key)
            decision = decision_index.get(model_key)
            exclusion_reason = str(exclusion["reason"]) if exclusion else None
            if exclusion:
                excluded.add(model_key)
            if not dimensions:
                candidate_rows = sorted(
                    (
                        row
                        for key, row in candidate_index.items()
                        if key[:2]
                        == (official_provider_id, official_model_id)
                        and _region_matches(
                            json.loads(
                                str(row.get("conditions_json") or "{}")
                            ),
                            model.pricing_region,
                        )
                    ),
                    key=lambda row: (
                        str(row["unit_key"]),
                        str(row.get("conditions_json") or "{}"),
                    ),
                )
                if candidate_rows:
                    matched.add(model_key)
                    for candidate in candidate_rows:
                        conditions = json.loads(
                            str(candidate.get("conditions_json") or "{}")
                        )
                        unit_size = int(conditions.pop("unit_size", 1))
                        evidence_level = str(
                            candidate.get("evidence_level") or "failed"
                        )
                        multiplier_value = candidate.get(
                            "default_multiplier_decimal"
                        )
                        multiplier = (
                            Decimal(str(multiplier_value))
                            if multiplier_value is not None
                            else self.default_multiplier
                        )
                        cost = Decimal(str(candidate["rmb_cost_decimal"]))
                        sale = cost * multiplier
                        include_default = (
                            evidence_level == "official_verified"
                        )
                        include = (
                            bool(decision["include_in_publish"])
                            if decision is not None
                            else include_default
                        ) and not bool(exclusion)
                        reason = (
                            str(decision.get("reason") or "") or None
                            if decision is not None
                            else exclusion_reason
                        )
                        rows.append(
                            PricingDraftRow(
                                model.provider_id,
                                model.provider_name,
                                model.model_key,
                                model.model_name,
                                official_provider_id,
                                official_model_id,
                                model.category,
                                str(candidate.get("capability") or ""),
                                str(candidate["unit_key"]),
                                unit_size,
                                conditions,
                                cost,
                                multiplier,
                                sale,
                                int(
                                    (
                                        sale * self.credits_per_yuan
                                    ).to_integral_value(
                                        rounding=ROUND_CEILING
                                    )
                                ),
                                f"candidate:{evidence_level}",
                                str(candidate.get("source_url") or "")
                                or None,
                                str(
                                    candidate.get("verification_status")
                                    or "candidate"
                                ),
                                include,
                                reason,
                                str(
                                    candidate.get("registry_version") or ""
                                )
                                or None,
                                evidence_level,
                            )
                        )
                    continue
                trusted_rows = sorted(
                    (
                        row
                        for key, row in cost_index.items()
                        if key[:2] == model_key
                        and _region_matches(
                            json.loads(
                                str(row.get("conditions_json") or "{}")
                            ),
                            model.pricing_region,
                        )
                    ),
                    key=lambda row: (
                        str(row["unit_key"]),
                        str(row.get("conditions_json") or "{}"),
                    ),
                )
                if trusted_rows:
                    matched.add(model_key)
                    for trusted in trusted_rows:
                        cost = Decimal(str(trusted["rmb_cost_decimal"]))
                        sale = cost * self.default_multiplier
                        credits = int(
                            (sale * self.credits_per_yuan).to_integral_value(
                                rounding=ROUND_CEILING
                            )
                        )
                        conditions = json.loads(
                            str(trusted.get("conditions_json") or "{}")
                        )
                        unit_size = int(
                            trusted.get("unit_size")
                            or conditions.pop(
                                "unit_size",
                                1000
                                if str(trusted["unit_key"])
                                in {"input_tokens", "output_tokens"}
                                else 1,
                            )
                        )
                        source_reference = str(
                            trusted.get("source_reference") or ""
                        )
                        rows.append(
                            PricingDraftRow(
                                model.provider_id,
                                model.provider_name,
                                model.model_key,
                                model.model_name,
                                official_provider_id,
                                official_model_id,
                                model.category,
                                str(
                                    trusted.get("capability") or model.category
                                ),
                                str(trusted["unit_key"]),
                                unit_size,
                                conditions,
                                cost,
                                self.default_multiplier,
                                sale,
                                credits,
                                "trusted_cost",
                                source_reference
                                if source_reference.startswith("https://")
                                else None,
                                "verified",
                                not bool(exclusion),
                                exclusion_reason,
                                None,
                            )
                        )
                    continue
                missing.add(model_key)
                code = (
                    "official_model_unmatched"
                    if official_model_id is None
                    else "official_price_missing"
                )
                risks.append(
                    PricingDraftRisk(code, model.provider_id, model.model_key)
                )
                rows.append(
                    PricingDraftRow(
                        model.provider_id,
                        model.provider_name,
                        model.model_key,
                        model.model_name,
                        official_provider_id,
                        official_model_id,
                        model.category,
                        "",
                        "",
                        1,
                        {},
                        None,
                        self.default_multiplier,
                        None,
                        None,
                        "missing",
                        None,
                        "unmatched"
                        if official_model_id is None
                        else "missing",
                        False,
                        exclusion_reason,
                        None,
                    )
                )
                continue
            matched.add(model_key)
            for dimension in dimensions:
                override = (
                    cost_index.get(
                        (
                            model.provider_id,
                            model.model_key,
                            dimension.capability,
                            dimension.unit_key,
                            _conditions_key(dimension.conditions),
                        )
                    )
                    or cost_index.get(
                        (
                            model.provider_id,
                            model.model_key,
                            "",
                            dimension.unit_key,
                            _conditions_key(dimension.conditions),
                        )
                    )
                    or cost_index.get(
                        (
                            model.provider_id,
                            model.model_key,
                            dimension.capability,
                            dimension.unit_key,
                            "{}",
                        )
                    )
                    or cost_index.get(
                        (
                            model.provider_id,
                            model.model_key,
                            "",
                            dimension.unit_key,
                            "{}",
                        )
                    )
                )
                rmb_cost = (
                    Decimal(str(override["rmb_cost_decimal"]))
                    if override
                    else dimension.rmb_cost
                )
                source_type = (
                    "trusted_cost" if override else "official_registry"
                )
                sale = rmb_cost * self.default_multiplier
                credits = int(
                    (sale * self.credits_per_yuan).to_integral_value(
                        rounding=ROUND_CEILING
                    )
                )
                conditions = dimension.conditions
                rows.append(
                    PricingDraftRow(
                        model.provider_id,
                        model.provider_name,
                        model.model_key,
                        model.model_name,
                        official_provider_id,
                        official_model_id,
                        model.category,
                        dimension.capability,
                        dimension.unit_key,
                        dimension.unit_size,
                        conditions,
                        rmb_cost,
                        self.default_multiplier,
                        sale,
                        credits,
                        source_type,
                        dimension.source_url,
                        "verified",
                        not bool(exclusion),
                        exclusion_reason,
                        dimension.registry_version,
                    )
                )
        rows.sort(
            key=lambda row: (
                row.provider_id,
                row.category,
                row.model_key,
                row.unit_key,
                json.dumps(row.conditions, sort_keys=True),
            )
        )
        blocking = missing - excluded
        return PricingDraftResult(
            tuple(rows),
            tuple(risks),
            PricingCoverage(
                len(models),
                len(matched),
                len(missing),
                len(excluded),
                len(blocking),
            ),
        )


def _conditions_key(value: Any) -> str:
    parsed = json.loads(value) if isinstance(value, str) else value
    return json.dumps(parsed or {}, sort_keys=True, separators=(",", ":"))


def _region_matches(
    conditions: Mapping[str, Any], pricing_region: str | None
) -> bool:
    official_region = conditions.get("region")
    if official_region is None:
        return True
    return pricing_region is not None and official_region == pricing_region
