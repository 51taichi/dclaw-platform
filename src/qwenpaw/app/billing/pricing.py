# -*- coding: utf-8 -*-
"""Versioned DClaw retail pricing authority and quote calculation."""
from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, NoReturn, TypeGuard

from ..storage.repos.price_catalog_repo import (
    CatalogImmutableError,
    CatalogNotFoundError,
    PriceCatalogRepository,
)


_SUPPORTED_UNITS = {
    "tokens",
    "image_count",
    "video_duration",
    "fixed_workflow",
}
_ALLOWED_SELECTOR_KEYS = frozenset(
    {
        "count",
        "duration_seconds",
        "resolution",
        "quality",
        "generation_mode",
        "audio",
        "aspect_ratio",
        "tier",
        "workflow_key",
        "operation",
        "size",
    },
)


class FrozenJSONDict(dict[str, Any]):
    """JSON-serializable dictionary that rejects every mutation."""

    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise TypeError("JSON snapshot values are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable

    def __copy__(self) -> FrozenJSONDict:
        return self

    def __deepcopy__(self, _memo: dict[int, Any]) -> FrozenJSONDict:
        return self


class FrozenJSONList(list[Any]):
    """JSON-serializable list that rejects every mutation."""

    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise TypeError("JSON snapshot values are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable

    def __copy__(self) -> FrozenJSONList:
        return self

    def __deepcopy__(self, _memo: dict[int, Any]) -> FrozenJSONList:
        return self


class AmbiguousPriceRuleError(ValueError):
    """Two published rules could win with exactly the same precedence."""


class PriceRuleNotFoundError(LookupError):
    """No active rule matches a retail quote request."""


@dataclass(frozen=True)
class QuoteRequest:
    provider_id: str
    model_key: str
    capability: str
    parameters: Mapping[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parameters",
            _strict_json_object(self.parameters, "parameters"),
        )


@dataclass(frozen=True)
class RetailQuote:
    catalog_version: str
    rule_id: str
    credits: int
    unit_breakdown: Mapping[str, int]
    snapshot: Mapping[str, Any]
    request: QuoteRequest

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "unit_breakdown",
            _strict_json_object(self.unit_breakdown, "unit_breakdown"),
        )
        object.__setattr__(
            self,
            "snapshot",
            _strict_json_object(self.snapshot, "snapshot"),
        )


@dataclass(frozen=True)
class PriceRule:
    id: str
    provider_id: str
    model_key: str
    capability: str
    unit_type: str
    priority: int = 0
    unit_size: int = 1
    credits_per_unit: int = 0
    input_credits_per_1k: int = 0
    output_credits_per_1k: int = 0
    parameter_match: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parameter_match",
            _strict_json_object(self.parameter_match, "parameter_match"),
        )
        object.__setattr__(
            self,
            "metadata",
            _strict_json_object(self.metadata, "metadata"),
        )


@dataclass(frozen=True)
class PriceCatalogDraft:
    version: str
    effective_at: datetime
    rules: Sequence[PriceRule]
    created_by: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "rules", tuple(self.rules))
        object.__setattr__(
            self,
            "metadata",
            _strict_json_object(self.metadata, "metadata"),
        )


class PriceCatalogService:
    """Publish retail catalogs and calculate immutable quote values."""

    def __init__(
        self,
        repository: PriceCatalogRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def publish(self, draft: PriceCatalogDraft) -> str:
        """Explicit admin/service command to publish supplied prices."""
        self.validate_draft(draft)
        normalized_draft = replace(
            draft,
            effective_at=_aware_utc(draft.effective_at),
        )
        return self.repository.publish_catalog(
            normalized_draft,
            published_at=_aware_utc(self._clock()),
        )

    def validate_draft(self, draft: PriceCatalogDraft) -> None:
        if not draft.version.strip():
            raise ValueError("catalog version must be non-empty")
        _aware_utc(draft.effective_at)
        if not draft.rules:
            raise ValueError("catalog must contain at least one price rule")

        rule_ids: set[str] = set()
        for rule in draft.rules:
            self._validate_rule(rule)
            if rule.id in rule_ids:
                raise ValueError(f"duplicate price rule id: {rule.id}")
            rule_ids.add(rule.id)

        ordered = sorted(draft.rules, key=lambda rule: rule.id)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                if _rules_are_ambiguous(left, right):
                    raise AmbiguousPriceRuleError(
                        "ambiguous overlapping price rules: "
                        f"{left.id} and {right.id}",
                    )

    def quote(
        self,
        request: QuoteRequest,
        at: datetime | None = None,
    ) -> RetailQuote:
        self._validate_request(request)
        quote_time = _aware_utc(at or self._clock())
        catalog = self.repository.effective_catalog(quote_time)
        candidates = [
            rule
            for rule in catalog["rules"]
            if rule["provider_id"] == request.provider_id
            and rule["model_key"] == request.model_key
            and rule["capability"] == request.capability
            and _parameters_match(rule["parameter_match"], request.parameters)
        ]
        if not candidates:
            raise PriceRuleNotFoundError(
                "no retail price rule for "
                f"{request.provider_id}/{request.model_key}/"
                f"{request.capability}",
            )

        candidates.sort(
            key=lambda rule: (
                len(rule["parameter_match"]),
                int(rule["priority"]),
            ),
            reverse=True,
        )
        winner = candidates[0]
        winning_rank = (
            len(winner["parameter_match"]),
            int(winner["priority"]),
        )
        tied = [
            rule
            for rule in candidates[1:]
            if (
                len(rule["parameter_match"]),
                int(rule["priority"]),
            )
            == winning_rank
        ]
        if tied:
            ids = sorted([winner["id"], *(rule["id"] for rule in tied)])
            raise AmbiguousPriceRuleError(
                f"ambiguous published price rules: {', '.join(ids)}",
            )

        breakdown, usage = _calculate_rule(winner, request)
        total_credits = sum(breakdown.values())
        stable_request = QuoteRequest(
            request.provider_id,
            request.model_key,
            request.capability,
            request.parameters,
            input_tokens=request.input_tokens,
            output_tokens=request.output_tokens,
        )
        snapshot = {
            "catalog_version": catalog["version"],
            "rule": {
                "id": winner["id"],
                "provider_id": winner["provider_id"],
                "model_key": winner["model_key"],
                "capability": winner["capability"],
                "unit_type": winner["unit_type"],
                "priority": int(winner["priority"]),
                "unit_size": int(winner["unit_size"]),
                "credits_per_unit": int(winner["credits_per_unit"]),
                "input_credits_per_1k": int(
                    winner["input_credits_per_1k"],
                ),
                "output_credits_per_1k": int(
                    winner["output_credits_per_1k"],
                ),
                "parameter_match": winner["parameter_match"],
            },
            "request": {
                "provider_id": stable_request.provider_id,
                "model_key": stable_request.model_key,
                "capability": stable_request.capability,
                "parameters": stable_request.parameters,
                "input_tokens": stable_request.input_tokens,
                "output_tokens": stable_request.output_tokens,
            },
            "usage": usage,
            "unit_breakdown": dict(breakdown),
            "credits": total_credits,
        }
        return RetailQuote(
            catalog_version=catalog["version"],
            rule_id=winner["id"],
            credits=total_credits,
            unit_breakdown=breakdown,
            snapshot=snapshot,
            request=stable_request,
        )

    @staticmethod
    def _validate_rule(rule: PriceRule) -> None:
        for name, value in (
            ("id", rule.id),
            ("provider_id", rule.provider_id),
            ("model_key", rule.model_key),
            ("capability", rule.capability),
        ):
            if not value.strip():
                raise ValueError(f"price rule {name} must be non-empty")
        if rule.unit_type not in _SUPPORTED_UNITS:
            raise ValueError(f"unsupported price unit: {rule.unit_type}")
        for name, value in (
            ("priority", rule.priority),
            ("credits_per_unit", rule.credits_per_unit),
            ("input_credits_per_1k", rule.input_credits_per_1k),
            ("output_credits_per_1k", rule.output_credits_per_1k),
        ):
            if not _is_integer(value) or value < 0:
                raise ValueError(
                    f"price rule {name} must be a non-negative integer",
                )
        if not _is_integer(rule.unit_size) or rule.unit_size <= 0:
            raise ValueError("price rule unit_size must be a positive integer")
        if rule.unit_type == "tokens":
            if not (rule.input_credits_per_1k or rule.output_credits_per_1k):
                raise ValueError(
                    "token rule must define an input or output rate",
                )
        elif rule.credits_per_unit <= 0:
            raise ValueError(
                f"{rule.unit_type} rule must define credits_per_unit",
            )
        for key in sorted(rule.parameter_match):
            if key not in _ALLOWED_SELECTOR_KEYS:
                raise ValueError(
                    f"unsupported price selector key: {key}",
                )

    @staticmethod
    def _validate_request(request: QuoteRequest) -> None:
        for name, value in (
            ("provider_id", request.provider_id),
            ("model_key", request.model_key),
            ("capability", request.capability),
        ):
            if not value.strip():
                raise ValueError(f"quote {name} must be non-empty")
        for name, value in (
            ("input_tokens", request.input_tokens),
            ("output_tokens", request.output_tokens),
        ):
            if not _is_integer(value) or value < 0:
                raise ValueError(
                    f"quote {name} must be a non-negative integer",
                )


def _rules_are_ambiguous(left: PriceRule, right: PriceRule) -> bool:
    if (
        left.provider_id,
        left.model_key,
        left.capability,
    ) != (
        right.provider_id,
        right.model_key,
        right.capability,
    ):
        return False
    if (
        len(left.parameter_match),
        left.priority,
    ) != (
        len(right.parameter_match),
        right.priority,
    ):
        return False
    shared_keys = set(left.parameter_match) & set(right.parameter_match)
    return all(
        _json_values_equal(
            left.parameter_match[key],
            right.parameter_match[key],
        )
        for key in shared_keys
    )


def _parameters_match(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> bool:
    return all(
        key in actual and _json_values_equal(actual[key], value)
        for key, value in expected.items()
    )


def _calculate_rule(
    rule: Mapping[str, Any],
    request: QuoteRequest,
) -> tuple[dict[str, int], dict[str, int]]:
    unit_type = rule["unit_type"]
    if unit_type == "tokens":
        input_credits = _ceil_div(
            request.input_tokens * int(rule["input_credits_per_1k"]),
            1_000,
        )
        output_credits = _ceil_div(
            request.output_tokens * int(rule["output_credits_per_1k"]),
            1_000,
        )
        return (
            {
                "input_tokens": input_credits,
                "output_tokens": output_credits,
            },
            {
                "input_tokens": request.input_tokens,
                "output_tokens": request.output_tokens,
            },
        )
    if unit_type == "image_count":
        count = _positive_parameter(request.parameters, "count", default=1)
        return (
            {
                "image_count": _ceil_div(
                    count * int(rule["credits_per_unit"]),
                    int(rule["unit_size"]),
                ),
            },
            {"image_count": count},
        )
    if unit_type == "video_duration":
        duration = _video_duration(request.parameters)
        return (
            {
                "video_duration_seconds": _ceil_div(
                    duration * int(rule["credits_per_unit"]),
                    int(rule["unit_size"]),
                ),
            },
            {"video_duration_seconds": duration},
        )
    if unit_type == "fixed_workflow":
        return (
            {"workflow_invocation": int(rule["credits_per_unit"])},
            {"workflow_invocations": 1},
        )
    raise ValueError(f"unsupported price unit: {unit_type}")


def _video_duration(parameters: Mapping[str, Any]) -> int:
    has_seconds = "duration_seconds" in parameters
    has_legacy = "duration" in parameters
    if has_seconds and has_legacy:
        if parameters["duration_seconds"] != parameters["duration"]:
            raise ValueError("video duration parameters disagree")
    key = "duration_seconds" if has_seconds else "duration"
    if key not in parameters:
        raise ValueError("video quote requires duration_seconds")
    return _positive_parameter(parameters, key)


def _positive_parameter(
    parameters: Mapping[str, Any],
    key: str,
    *,
    default: int | None = None,
) -> int:
    value = parameters.get(key, default)
    if not _is_integer(value) or value <= 0:
        raise ValueError(f"quote parameter {key} must be a positive integer")
    return value


def _ceil_div(numerator: int, denominator: int) -> int:
    return (numerator + denominator - 1) // denominator


def _is_integer(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _strict_json_object(
    value: Mapping[str, Any],
    field_name: str,
) -> FrozenJSONDict:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be strict JSON: expected object")
    try:
        native = _json_native(value, field_name)
        encoded = json.dumps(
            native,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        canonical = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be strict JSON: {exc}") from exc
    return _freeze_json(canonical)


def _json_native(value: Any, path: str) -> Any:
    if value is None or type(value) in {str, bool, int}:  # noqa: E721
        return value
    if type(value) is float:  # noqa: E721
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string object key")
            result[key] = _json_native(item, f"{path}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [
            _json_native(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise ValueError(
        f"{path} contains unsupported type {type(value).__name__}",
    )


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return FrozenJSONDict(
            {key: _freeze_json(item) for key, item in value.items()},
        )
    if isinstance(value, list):
        return FrozenJSONList(_freeze_json(item) for item in value)
    return value


def _json_values_equal(left: Any, right: Any) -> bool:
    return json.dumps(
        _json_native(left, "value"),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ) == json.dumps(
        _json_native(right, "value"),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("catalog and quote times must be timezone-aware")
    return value.astimezone(timezone.utc)


__all__ = [
    "AmbiguousPriceRuleError",
    "CatalogImmutableError",
    "CatalogNotFoundError",
    "PriceCatalogDraft",
    "PriceCatalogService",
    "PriceRule",
    "PriceRuleNotFoundError",
    "QuoteRequest",
    "RetailQuote",
]
