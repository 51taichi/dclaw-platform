#!/usr/bin/env python3
"""Publish an audited AIGC retail-price override catalog.

The active catalog is immutable. This command clones every existing rule,
changes only the configured AIGC dimensions, and publishes a new catalog.
Dry-run is the default; ``--apply`` requires the expected active version so a
concurrent admin price change cannot be overwritten accidentally.
"""

from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qwenpaw.app.billing.pricing import (
    PriceCatalogDraft,
    PriceCatalogService,
    PriceRule,
)
from qwenpaw.app.storage.engine import get_app_engine
from qwenpaw.app.storage.repos.price_catalog_repo import PriceCatalogRepository


DEFAULT_CONFIG = (
    Path(__file__).resolve().parents[2]
    / "deploy"
    / "pricing"
    / "aigc-retail-prices.json"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="publish the generated catalog; otherwise only show the diff",
    )
    parser.add_argument(
        "--expect-catalog-version",
        help="required with --apply; abort if the active version differs",
    )
    parser.add_argument(
        "--version",
        help="new catalog version; defaults to an UTC timestamp",
    )
    return parser


def _load_config(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported AIGC retail price schema")
    prices = payload.get("prices")
    if not isinstance(prices, list) or not prices:
        raise ValueError("prices must contain at least one override")
    return payload


def _price_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row["provider_id"]),
        str(row["model_key"]),
        str(row["capability"]),
        str(row["unit_key"]),
    )


def _rule_from_row(row: dict[str, Any], metadata: dict[str, Any]) -> PriceRule:
    return PriceRule(
        id=str(row["id"]),
        provider_id=str(row["provider_id"]),
        model_key=str(row["model_key"]),
        capability=str(row["capability"]),
        unit_type=str(row["unit_type"]),
        priority=int(row["priority"]),
        unit_size=int(row["unit_size"]),
        credits_per_unit=int(row["credits_per_unit"]),
        input_credits_per_1k=int(row["input_credits_per_1k"]),
        output_credits_per_1k=int(row["output_credits_per_1k"]),
        parameter_match=dict(row["parameter_match"]),
        metadata=metadata,
    )


def build_rules(
    catalog: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[tuple[PriceRule, ...], list[dict[str, Any]]]:
    overrides = {_price_key(row): row for row in payload["prices"]}
    if len(overrides) != len(payload["prices"]):
        raise ValueError("duplicate AIGC retail price override")

    matched: set[tuple[str, str, str, str]] = set()
    changes: list[dict[str, Any]] = []
    rules: list[PriceRule] = []
    for row in catalog["rules"]:
        metadata = copy.deepcopy(dict(row["metadata"]))
        dimensions = metadata.get("dimensions")
        if row["unit_type"] == "metered_dimensions" and isinstance(
            dimensions,
            list,
        ):
            for dimension in dimensions:
                key = (
                    str(row["provider_id"]),
                    str(row["model_key"]),
                    str(row["capability"]),
                    str(dimension.get("unit_key") or ""),
                )
                override = overrides.get(key)
                if override is None:
                    continue
                old_credits = int(dimension["credits_per_unit"])
                new_credits = int(override["credits_per_unit"])
                if new_credits <= 0:
                    raise ValueError(f"credits_per_unit must be positive: {key}")
                dimension["credits_per_unit"] = new_credits
                matched.add(key)
                changes.append(
                    {
                        "provider_id": key[0],
                        "model_key": key[1],
                        "capability": key[2],
                        "unit_key": key[3],
                        "old_credits_per_unit": old_credits,
                        "new_credits_per_unit": new_credits,
                    }
                )
                metadata["retail_override"] = {
                    "reason": str(payload.get("change_reason") or "").strip(),
                    "unit_key": key[3],
                    "credits_per_unit": new_credits,
                }
        rules.append(_rule_from_row(row, metadata))

    missing = sorted(set(overrides) - matched)
    if missing:
        raise ValueError(f"price dimensions not found in active catalog: {missing}")
    return tuple(rules), changes


def main() -> int:
    args = _parser().parse_args()
    if args.apply and not args.expect_catalog_version:
        raise SystemExit("--apply requires --expect-catalog-version")

    now = datetime.now(timezone.utc)
    pricing = PriceCatalogService(PriceCatalogRepository(get_app_engine()))
    active = pricing.repository.effective_catalog(now)
    active_version = str(active["version"])
    if args.expect_catalog_version and active_version != args.expect_catalog_version:
        raise SystemExit(
            "active catalog changed: "
            f"expected {args.expect_catalog_version}, got {active_version}",
        )

    payload = _load_config(args.config)
    rules, changes = build_rules(active, payload)
    result = {
        "mode": "apply" if args.apply else "dry-run",
        "source_catalog_version": active_version,
        "changes": changes,
    }
    if args.apply:
        version = args.version or now.strftime("aigc-retail-%Y%m%d%H%M%S")
        catalog_id = pricing.publish(
            PriceCatalogDraft(
                version=version,
                effective_at=now,
                rules=rules,
                created_by="aigc-retail-price-script",
                metadata={
                    **dict(active["metadata"]),
                    "source_catalog_id": str(active["id"]),
                    "source_catalog_version": active_version,
                    "change_reason": str(payload.get("change_reason") or ""),
                    "change_type": "aigc_retail_price_override",
                },
            ),
        )
        result.update({"catalog_id": catalog_id, "catalog_version": version})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
