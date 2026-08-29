"""Deterministic Decimal policy resolution for retail catalog generation."""
from collections.abc import Mapping
from decimal import ROUND_CEILING, Decimal

from .pricing import PriceRule
from .pricing_models import (
    ModelIdentity,
    PricingDefaults,
    PricingPolicy,
    ResolvedMultiplier,
    RetailComponent,
    TrustedCost,
)


def resolve_multiplier(
    policies: tuple[PricingPolicy, ...], identity: ModelIdentity,
) -> ResolvedMultiplier:
    keys = (
        ("model", f"{identity.provider_id}/{identity.model_key}"),
        ("category", identity.category),
        ("provider", identity.provider_id),
        ("global", "*"),
    )
    for scope_type, scope_key in keys:
        for policy in policies:
            if policy.scope_type == scope_type and policy.scope_key == scope_key:
                return ResolvedMultiplier(policy.multiplier, scope_type, scope_key)
    raise LookupError(f"no multiplier for {identity.provider_id}/{identity.model_key}")


def price_cost(
    cost: TrustedCost, multiplier: Decimal, defaults: PricingDefaults,
) -> RetailComponent:
    applied = max(multiplier, defaults.minimum_multiplier)
    sale = cost.rmb_cost * (Decimal(1) + defaults.risk_buffer) * applied
    credits = int((sale * defaults.credits_per_yuan).to_integral_value(
        rounding=ROUND_CEILING))
    return RetailComponent(cost.unit_key, cost.rmb_cost, applied, sale, credits)


def build_catalog_rules(
    models: tuple[ModelIdentity, ...],
    costs: Mapping[tuple[str, str, str], TrustedCost],
    policies: tuple[PricingPolicy, ...],
    defaults: PricingDefaults,
) -> tuple[PriceRule, ...]:
    rules: list[PriceRule] = []
    for model in models:
        resolved = resolve_multiplier(policies, model)
        base_metadata = {
            "currency": "CNY",
            "risk_buffer": str(defaults.risk_buffer),
            "minimum_multiplier": str(defaults.minimum_multiplier),
            "applied_multiplier": str(max(
                resolved.value, defaults.minimum_multiplier)),
            "multiplier_scope": resolved.scope_type,
            "multiplier_scope_key": resolved.scope_key,
        }
        if model.category == "text":
            input_component = price_cost(costs[(
                model.provider_id, model.model_key, "input_tokens")],
                resolved.value, defaults)
            output_component = price_cost(costs[(
                model.provider_id, model.model_key, "output_tokens")],
                resolved.value, defaults)
            metadata = base_metadata | {
                "input_rmb_cost": str(input_component.rmb_cost),
                "input_rmb_sale_price": str(input_component.rmb_sale_price),
                "output_rmb_cost": str(output_component.rmb_cost),
                "output_rmb_sale_price": str(output_component.rmb_sale_price),
            }
            rules.append(PriceRule(
                id=f"generated:{model.provider_id}:{model.model_key}:tokens",
                provider_id=model.provider_id,
                model_key=model.model_key,
                capability="chat",
                unit_type="tokens",
                input_credits_per_1k=input_component.credits,
                output_credits_per_1k=output_component.credits,
                metadata=metadata,
            ))
            continue
        unit_type = {
            "image": "image_count",
            "video": "video_duration",
        }.get(model.category, "fixed_workflow")
        for key, cost in costs.items():
            if key[:2] != (model.provider_id, model.model_key):
                continue
            component = price_cost(cost, resolved.value, defaults)
            rules.append(PriceRule(
                id=f"generated:{model.provider_id}:{model.model_key}:{cost.unit_key}",
                provider_id=model.provider_id, model_key=model.model_key,
                capability=model.category, unit_type=unit_type,
                credits_per_unit=component.credits,
                parameter_match={"operation": cost.unit_key},
                metadata=base_metadata | {
                    "rmb_cost": str(component.rmb_cost),
                    "rmb_sale_price": str(component.rmb_sale_price),
                },
            ))
    return tuple(rules)
