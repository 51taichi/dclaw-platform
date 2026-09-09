"""Canonical metering specifications shared by draft export and import."""

import json
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


def normalize_spec(unit_key: str, unit_size: Any, conditions: Any):
    if isinstance(conditions, str):
        conditions = json.loads(conditions or "{}")
    if not isinstance(conditions, dict):
        raise ValueError("conditions must be an object")
    conditions = dict(conditions)
    embedded = conditions.pop("unit_size", None)
    default = 1_000_000 if unit_key in {"input_tokens", "output_tokens"} else 1
    try:
        size = Decimal(
            str(
                unit_size
                if unit_size is not None
                else embedded
                if embedded is not None
                else default
            )
        )
        if not size.is_finite() or size <= 0 or size != size.to_integral_value():
            raise ValueError("unit_size must be a positive integer")
        if embedded is not None and Decimal(str(embedded)) != size:
            raise ValueError("conflicting unit_size")
    except InvalidOperation as exc:
        raise ValueError("invalid unit_size") from exc
    return int(size), conditions


def spec_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    unit = str(row["unit_key"])
    size, conditions = normalize_spec(
        unit,
        row.get("unit_size"),
        row.get("conditions", row.get("conditions_json", {})),
    )
    return (
        str(row["provider_id"]),
        str(row["model_key"]),
        str(row.get("capability") or ""),
        unit,
        json.dumps(
            conditions, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        str(size),
    )
