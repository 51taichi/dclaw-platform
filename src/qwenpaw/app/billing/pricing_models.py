"""Immutable types for RMB cost-derived retail pricing."""
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PricingDefaults:
    credits_per_yuan: int = 100
    risk_buffer: Decimal = Decimal("0.05")
    minimum_multiplier: Decimal = Decimal("1.3")


@dataclass(frozen=True)
class ModelIdentity:
    provider_id: str
    model_key: str
    category: str


@dataclass(frozen=True)
class PricingPolicy:
    scope_type: str
    scope_key: str
    multiplier: Decimal


@dataclass(frozen=True)
class TrustedCost:
    rmb_cost: Decimal
    unit_key: str


@dataclass(frozen=True)
class ResolvedMultiplier:
    value: Decimal
    scope_type: str
    scope_key: str


@dataclass(frozen=True)
class RetailComponent:
    unit_key: str
    rmb_cost: Decimal
    applied_multiplier: Decimal
    rmb_sale_price: Decimal
    credits: int
